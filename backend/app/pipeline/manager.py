"""入库流水线管理器：异步任务队列 + 重试 + 并发控制。

阶段结构：
  1) 模态处理器（预览/理解/OCR/转录）
  2) 向量化入库
IngestionMode=sync 时同步执行（测试与小型演示）；async 时后台 worker 消费队列。
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from ..core.config import settings
from ..core.database import SessionLocal
from ..llm.client import client as llm_client
from ..models import Asset, DocumentChunk, IngestionJob, Tag
from ..retrieval.vector_store import vector_store
from ..retrieval.chunk_vector import chunk_vector_store
from .chunking import chunk_text
from .processors import build_embed_text, resolve_processor
from ..usage import record_usage

logger = logging.getLogger(__name__)


class IngestionManager:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._sem = asyncio.Semaphore(settings.worker_count)
        self._loop: asyncio.AbstractEventLoop | None = None

    # ---------- 生命周期 ----------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        # 上次进程退出会丢掉队列，先把卡在 pending/processing 的素材救回来
        recovered = self.recover_interrupted()
        if settings.ingestion_mode == "async" and not self._workers:
            for _ in range(settings.worker_count):
                self._workers.append(asyncio.create_task(self._worker(), name="ingestion-worker"))
        if recovered:
            logger.info("启动恢复：%d 个中断素材已重新入队", recovered)

    async def stop(self) -> None:
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    def recover_interrupted(self) -> int:
        """把上次进程退出时卡在 pending/processing 的素材恢复。

        async 模式重新入队自动续跑；sync 模式没有后台 worker，
        标记为 failed 走既有的重试入口，避免永远停在 processing。
        """
        with SessionLocal() as db:
            stuck = db.query(Asset).filter(Asset.status.in_(["pending", "processing"])).all()
            ids = [a.id for a in stuck]
            if settings.ingestion_mode == "async":
                for a in stuck:
                    a.status = "pending"
                    a.error_message = None
            else:
                for a in stuck:
                    a.status = "failed"
                    a.error_message = "服务重启导致处理中断，可点击重试"
            db.commit()
        if settings.ingestion_mode == "async":
            for aid in ids:
                self._queue.put_nowait(aid)
        return len(ids)

    # ---------- 入口 ----------

    async def submit(self, asset_id: int) -> None:
        if settings.ingestion_mode == "sync":
            await self._process(asset_id)
        else:
            await self._queue.put(asset_id)

    def submit_blocking(self, asset_id: int) -> None:
        """给后台线程（Agent 工具）用的同步入队：跨线程安全投递到主事件循环。"""
        if settings.ingestion_mode == "sync":
            asyncio.run(self._process(asset_id))
            return
        if self._loop is None:
            raise RuntimeError("入库管理器未启动")
        fut = asyncio.run_coroutine_threadsafe(self._queue.put(asset_id), self._loop)
        fut.result(timeout=15)

    async def _worker(self) -> None:
        while True:
            asset_id = await self._queue.get()
            try:
                async with self._sem:
                    await self._process(asset_id)
            except asyncio.CancelledError:
                self._queue.task_done()
                raise
            except Exception:
                logger.exception("worker 处理异常 asset_id=%s", asset_id)
            finally:
                self._queue.task_done()

    # ---------- 处理主流程 ----------

    async def _process(self, asset_id: int) -> None:
        data_root = settings.data_dir
        for attempt in range(1, settings.max_retries + 1):
            with SessionLocal() as db:
                asset = db.get(Asset, asset_id)
                if asset is None:
                    return
                asset.status = "processing"
                job = IngestionJob(asset_id=asset_id, stage="understand", status="running", attempts=attempt)
                db.add(job)
                db.commit()
                modality = asset.modality

            try:
                processor = resolve_processor(modality)
                result = await asyncio.to_thread(processor, asset, llm_client, data_root)

                with SessionLocal() as db:
                    asset = db.get(Asset, asset_id)
                    if asset is None:
                        return
                    self._apply_result(db, asset, result)
                    asset.status = "ready"
                    asset.error_message = None
                    job.status = "done"
                    db.commit()
                    embed_text = build_embed_text(result)

                # 统一分块：文档按段落切，音视频按转写时间片切（都保留原文出处）
                chunk_rows: list[DocumentChunk] = []
                if modality == "document" and result.text_content:
                    built = [
                        {"modality": "document", "text": t}
                        for t in chunk_text(result.text_content)
                    ]
                elif modality in ("audio", "video") and result.transcript_segments:
                    try:
                        segs = json.loads(result.transcript_segments or "[]")
                    except Exception:
                        segs = []
                    built = [
                        {
                            "modality": modality,
                            "text": (s.get("text") or "")[:1000],
                            "start": s.get("start"),
                            "end": s.get("end"),
                        }
                        for s in segs
                        if s.get("text")
                    ]
                else:
                    built = []
                if built:
                    with SessionLocal() as db:
                        asset = db.get(Asset, asset_id)
                        if asset is None:
                            return
                        db.query(DocumentChunk).filter(DocumentChunk.asset_id == asset_id).delete()
                        for seq, item in enumerate(built):
                            db.add(
                                DocumentChunk(
                                    asset_id=asset_id,
                                    modality=item["modality"],
                                    seq=seq,
                                    text=item["text"],
                                    start=item.get("start"),
                                    end=item.get("end"),
                                )
                            )
                        db.commit()
                        chunk_rows = (
                            db.query(DocumentChunk)
                            .filter(DocumentChunk.asset_id == asset_id)
                            .order_by(DocumentChunk.seq.asc())
                            .all()
                        )

                # 片段向量化（bge-m3 分批；失败仅降级关键词片段检索，不影响入库）
                if chunk_rows:
                    try:
                        texts = [c.text for c in chunk_rows]
                        vecs = await asyncio.to_thread(llm_client.embed_texts_batched, texts)
                        if vecs:
                            for c, v in zip(chunk_rows, vecs):
                                chunk_vector_store.add(c.id, v, settings.embedding_model)
                            record_usage(asset_id, settings.embedding_model, "chunk_embed")
                    except Exception as e:
                        logger.warning("片段向量化失败（已降级）asset_id=%s: %s", asset_id, e)

                # 向量化（有 Key 才做；失败不影响入库）
                if embed_text:
                    try:
                        vecs = await asyncio.to_thread(llm_client.embed_texts, [embed_text])
                        if vecs:
                            vector_store.add(asset_id, vecs[0], settings.embedding_model)
                            record_usage(asset_id, settings.embedding_model, "embed")
                    except Exception as e:
                        logger.warning("向量化失败（已降级）asset_id=%s: %s", asset_id, e)
                return

            except Exception as e:
                logger.exception("入库处理失败 asset_id=%s attempt=%s", asset_id, attempt)
                with SessionLocal() as db:
                    asset = db.get(Asset, asset_id)
                    if asset is None:
                        return
                    job = db.get(IngestionJob, job.id)
                    if job is not None:
                        job.status = "failed"
                        job.error = str(e)
                    if attempt >= settings.max_retries:
                        asset.status = "failed"
                        asset.error_message = str(e)
                    db.commit()
                if attempt < settings.max_retries:
                    await asyncio.sleep(1.5**attempt)

    def _apply_result(self, db, asset: Asset, result) -> None:
        asset.thumbnail_path = result.thumbnail_path
        asset.phash = result.phash
        asset.description = result.description
        asset.ocr_text = result.ocr_text
        asset.transcript = result.transcript
        asset.transcript_segments = result.transcript_segments
        asset.text_content = result.text_content
        asset.width = result.width
        asset.height = result.height
        asset.duration = result.duration
        asset.vision_model = result.vision_model
        # 标签整体替换（LLM 来源）
        for t in list(asset.tags):
            if t.source == "llm":
                db.delete(t)
        for name in result.tags:
            db.add(Tag(asset_id=asset.id, name=name, source="llm"))


manager = IngestionManager()
