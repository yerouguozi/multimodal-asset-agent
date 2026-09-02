"""入库流水线管理器：异步任务队列 + 重试 + 并发控制。

阶段结构：
  1) 模态处理器（预览/理解/OCR/转录）
  2) 向量化入库
IngestionMode=sync 时同步执行（测试与小型演示）；async 时后台 worker 消费队列。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..core.config import settings
from ..core.database import SessionLocal
from ..llm.client import client as llm_client
from ..models import Asset, IngestionJob, Tag
from ..retrieval.vector_store import vector_store
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
        if settings.ingestion_mode == "async" and not self._workers:
            for _ in range(settings.worker_count):
                self._workers.append(asyncio.create_task(self._worker(), name="ingestion-worker"))

    async def stop(self) -> None:
        for w in self._workers:
            w.cancel()
        self._workers.clear()

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
