"""语义检索接口：文本检索 / 以图搜图 / 转写片段时间戳检索。"""
import base64
import json
import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import get_db
from ..llm.client import client as llm_client
from ..models import Asset
from ..retrieval import search as search_service
from ..retrieval.search_log import record_search
from ..retrieval.vector_store import vector_store
from ..schemas import AssetOut, SearchHit, SearchResponse
from .auth import resolve_owner

router = APIRouter(prefix="/api/search", tags=["search"])

VALID_STRATEGIES = ("full", "rrf", "gate", "tri", "bm25")


@router.get("", response_model=SearchResponse)
def search(
    q: str,
    modality: str | None = None,
    tag: str | None = None,
    limit: int = 20,
    strategy: str = "full",
    db: Session = Depends(get_db),
    owner: str = Depends(resolve_owner),
):
    if strategy not in VALID_STRATEGIES:
        raise HTTPException(422, f"strategy 可选：{', '.join(VALID_STRATEGIES)}")
    t0 = time.perf_counter()
    hits = search_service.search(db, q, modality=modality, tag=tag, limit=limit, strategy=strategy, owner=owner)
    record_search(
        db,
        owner=owner,
        query=q,
        hits_count=len(hits),
        latency_ms=int((time.perf_counter() - t0) * 1000),
        modality=modality or "",
        strategy=strategy,
        top_ids=[a.id for a, _ in hits],
    )
    return SearchResponse(
        query=q,
        hits=[SearchHit(asset=AssetOut.model_validate(a), score=round(s, 4)) for a, s in hits],
    )

@router.post("/image")
async def search_by_image(
    file: UploadFile = File(...),
    limit: int = 20,
    db: Session = Depends(get_db),
    owner: str = Depends(resolve_owner),
):
    """以图搜图：上传参考图，按视觉相似度检索。"""
    content = await file.read()
    if not content:
        raise HTTPException(400, "空文件")
    b64 = base64.b64encode(content).decode("ascii")
    vec = llm_client.embed_image(b64, file.content_type or "image/jpeg")
    if not vec:
        raise HTTPException(503, "多模态向量不可用（未配置 Key 或模型不可用）")
    hits = vector_store.search(vec, settings.vl_embedding_model, top_k=limit)
    out = []
    for aid, score in hits.items():
        asset = db.query(Asset).filter(Asset.id == aid, Asset.owner == owner).first()
        if asset:
            out.append({"asset": AssetOut.model_validate(asset), "score": round(score, 4)})
    return {"hits": out}


@router.get("/transcript")
def search_transcript(
    q: str,
    modality: str | None = None,
    limit: int = 10,
    db: Session = Depends(get_db),
    owner: str = Depends(resolve_owner),
):
    """在音频/视频转写片段里定位关键词，返回时间戳（找"说过某段话"）。"""
    q = (q or "").strip()
    if not q:
        raise HTTPException(400, "q 不能为空")
    assets = db.query(Asset).filter(Asset.status == "ready", Asset.owner == owner).all()
    if modality:
        assets = [a for a in assets if a.modality == modality]
    hits = []
    for a in assets:
        try:
            segs = json.loads(a.transcript_segments or "[]")
        except Exception:
            continue
        for s in segs:
            text = s.get("text") or ""
            if q in text:
                hits.append({
                    "asset_id": a.id,
                    "name": a.name,
                    "modality": a.modality,
                    "start": s.get("start", 0),
                    "end": s.get("end"),
                    "snippet": text[:150],
                })
    return {"query": q, "hits": hits[:limit]}
