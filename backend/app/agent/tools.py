"""Agent 工具层：确定性函数，LLM 只负责组织语言（项目设计原则）。

每个工具独立开事务、返回结构化结果；空结果/错误也如实返回，
禁止让 LLM 编造素材。
"""
from __future__ import annotations

from ..core.database import SessionLocal
from ..domain.profile import build_profile
from ..models import Asset
from ..retrieval import search as search_service

TOOL_DESCRIPTIONS: list[dict] = [
    {"name": "search_assets", "description": "按自然语言跨模态检索素材库，返回最相关的素材列表。", "params": {"query": "检索词"}},
    {"name": "get_asset_detail", "description": "查看某个素材的完整信息（描述/标签/OCR/转写）。", "params": {"asset_id": "素材编号"}},
    {"name": "domain_profile", "description": "获取素材库整体领域画像（模态分布/高频标签/总结）。", "params": {}},
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


TOOL_REGISTRY: dict[str, callable] = {
    "search_assets": search_assets,
    "get_asset_detail": get_asset_detail,
    "domain_profile": domain_profile,
}
