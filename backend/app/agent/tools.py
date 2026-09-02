"""Agent 工具层：确定性函数，LLM 只负责组织语言（项目设计原则）。

每个工具独立开事务、返回结构化结果；空结果/错误也如实返回，
禁止让 LLM 编造素材。
"""
from __future__ import annotations

from ..core.database import SessionLocal
from ..domain.profile import build_profile
from ..models import Asset, Tag
from ..retrieval import search as search_service

TOOL_DESCRIPTIONS: list[dict] = [
    {"name": "search_assets", "description": "按自然语言跨模态检索素材库，返回最相关的素材列表。", "params": {"query": "检索词"}},
    {"name": "get_asset_detail", "description": "查看某个素材的完整信息（描述/标签/OCR/转写）。", "params": {"asset_id": "素材编号"}},
    {"name": "domain_profile", "description": "获取素材库整体领域画像（模态分布/高频标签/总结）。", "params": {}},
    {"name": "generate_image", "description": "根据描述生成一张图片并自动入库。", "params": {"prompt": "画面描述"}},
    {"name": "transform_asset", "description": "处理已有素材（压缩/缩放/转格式），生成新版本入库。", "params": {"asset_id": "素材编号", "operation": "compress|resize|convert", "params": "参数"}},
    {"name": "find_moment", "description": "在音频/视频的转写片段里定位关键词，返回时间戳（用于找\"说过某段话\"）。", "params": {"query": "关键词"}},
]


def _asset_brief(asset: Asset) -> dict:
    return {
        "id": asset.id,
        "name": asset.name,
        "modality": asset.modality,
        "description": asset.description,
        "tags": [t.name for t in asset.tags],
    }


def search_assets(query: str, limit: int = 5) -> dict:
    with SessionLocal() as db:
        hits = search_service.search(db, query, limit=limit)
        assets = [_asset_brief(a) for a, _ in hits]
    return {
        "ok": True,
        "summary": f"找到 {len(assets)} 个相关素材" if assets else "没有找到相关素材",
        "assets": assets,
    }


def get_asset_detail(asset_id: int) -> dict:
    with SessionLocal() as db:
        asset = db.get(Asset, asset_id)
        if asset is None:
            return {"ok": False, "summary": f"素材 #{asset_id} 不存在", "assets": []}
        return {
            "ok": True,
            "summary": f"素材 #{asset.id}（{asset.modality}）",
            "assets": [
                {
                    **_asset_brief(asset),
                    "ocr": asset.ocr_text,
                    "transcript": asset.transcript,
                    "text_content": (asset.text_content or "")[:300],
                }
            ],
        }


def domain_profile() -> dict:
    with SessionLocal() as db:
        p = build_profile(db)
    return {
        "ok": True,
        "summary": p.summary,
        "labels": p.labels,
        "by_modality": p.by_modality,
        "top_tags": [t for t, _ in p.top_tags[:10]],
        "assets": [],
    }


def generate_image(prompt: str) -> dict:
    """文生图：调用 SiliconFlow，产物作为新素材走正常入库管线。"""
    from datetime import datetime

    from ..core.config import settings
    from ..llm.client import client as llm_client
    from ..pipeline.manager import manager
    from ..usage import record_usage

    data = llm_client.generate_image(prompt)
    record_usage(None, settings.image_gen_model, "image_gen")
    if not data:
        return {"ok": False, "summary": "文生图失败（模型不可用或未配置 Key）", "assets": []}

    from pathlib import Path

    import uuid

    stem = f"生成图_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    from pathlib import Path as _Path

    rel_dir = _Path(settings.upload_dir).name  # 与 upload.py 保持一致（upload_dir 名可变）
    rel_path = f"{rel_dir}/image/{uuid.uuid4().hex}.png"
    target = settings.upload_path / "image" / Path(rel_path).name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    with SessionLocal() as db:
        import hashlib

        asset = Asset(
            name=stem,
            original_filename=f"{stem}.png",
            modality="image",
            mime_type="image/png",
            size_bytes=len(data),
            storage_path=rel_path,
            sha256=hashlib.sha256(data).hexdigest(),
            status="pending",
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        aid = asset.id
    try:
        manager.submit_blocking(aid)
    except Exception as e:
        with SessionLocal() as db:
            a = db.get(Asset, aid)
            if a:
                a.status = "failed"
                a.error_message = str(e)
                db.commit()
        return {"ok": False, "summary": f"生成图入库失败: {e}", "assets": []}
    with SessionLocal() as db:
        a = db.get(Asset, aid)
        brief = _asset_brief(a) if a else {}
    return {"ok": True, "summary": f"已生成图片并入库 #{aid}", "assets": [brief] if brief else []}


def transform_asset(asset_id: int, operation: str, params: dict | None = None) -> dict:
    """处理素材生成新版本：复用原素材的理解结果与向量（语义不变，省模型调用）。"""
    import hashlib
    import uuid

    from ..core.config import settings
    from ..llm.client import client as llm_client
    from ..processing import SUPPORTED_OPERATIONS, image_size, transform_file
    from ..retrieval.vector_store import vector_store
    from ..usage import record_usage

    params = params or {}
    with SessionLocal() as db:
        src = db.get(Asset, asset_id)
        if src is None:
            return {"ok": False, "summary": f"素材 #{asset_id} 不存在", "assets": []}
        if operation not in SUPPORTED_OPERATIONS.get(src.modality, []):
            return {"ok": False, "summary": f"{src.modality} 不支持 {operation}", "assets": []}
        src_path = settings.data_dir / src.storage_path
    try:
        stem = f"a{asset_id}_{operation}_{uuid.uuid4().hex[:6]}"
        out = transform_file(src_path, src.modality, operation, params, settings.data_dir / "processed", stem)
    except Exception as e:
        return {"ok": False, "summary": f"处理失败: {e}", "assets": []}

    rel_path = f"processed/{out.name}"
    data = out.read_bytes()
    with SessionLocal() as db:
        src = db.get(Asset, asset_id)  # 重新取，避免跨会话懒加载
        if src is None:
            return {"ok": False, "summary": f"素材 #{asset_id} 不存在", "assets": []}
        width, height = (None, None)
        if src.modality == "image":
            width, height = image_size(out)
        new = Asset(
            name=f"{src.name}_{operation}",
            original_filename=out.name,
            modality=src.modality,
            mime_type="",
            size_bytes=len(data),
            storage_path=rel_path,
            sha256=hashlib.sha256(data).hexdigest(),
            status="ready",
            description=src.description,
            ocr_text=src.ocr_text,
            transcript=src.transcript,
            text_content=src.text_content,
            width=width or src.width,
            height=height or src.height,
            duration=src.duration,
            vision_model=src.vision_model,
        )
        db.add(new)
        db.flush()
        for tag in src.tags:
            db.add(Tag(asset_id=new.id, name=tag.name, source="user"))
        db.commit()
        db.refresh(new)
        brief = _asset_brief(new)
        new_id = new.id

    # 复用语义向量：用相同描述文本重新嵌入（一次调用，记录成本）
    text = " ".join(p for p in [src.description, src.ocr_text, src.transcript, src.text_content] if p)[:1500]
    if text:
        vecs = llm_client.embed_texts([text])
        record_usage(new_id, settings.embedding_model, "embed")
        if vecs:
            vector_store.add(new_id, vecs[0], settings.embedding_model)
    return {"ok": True, "summary": f"已生成处理版本 #{new_id}", "assets": [brief]}


def find_moment(query: str) -> dict:
    """在音视频转写片段里定位关键词，返回时间戳列表。"""
    import json as _json

    with SessionLocal() as db:
        assets = db.query(Asset).filter(Asset.status == "ready").all()
        moments = []
        for a in assets:
            try:
                segs = _json.loads(a.transcript_segments or "[]")
            except Exception:
                segs = []
            for s in segs:
                text = (s.get("text") or "")
                if query and query in text:
                    moments.append({
                        "asset_id": a.id,
                        "name": a.name,
                        "start": s.get("start", 0),
                        "end": s.get("end"),
                        "snippet": text[:120],
                    })
    return {
        "ok": bool(moments),
        "summary": f"找到 {len(moments)} 处相关内容" if moments else "没有找到相关内容",
        "moments": moments[:10],
        "assets": [],
    }


TOOL_REGISTRY: dict[str, callable] = {
    "search_assets": search_assets,
    "get_asset_detail": get_asset_detail,
    "domain_profile": domain_profile,
    "generate_image": generate_image,
    "transform_asset": transform_asset,
    "find_moment": find_moment,
}
