"""深度七期测试：长文档分块入库 + 片段级检索（出处）+ Agent 片段工具。"""
import hashlib
import json

from app.agent.tools import find_passage
from app.core.config import settings
from app.core.database import SessionLocal
from app.llm.client import client as llm_client
from app.models import Asset, DocumentChunk
from app.pipeline.chunking import chunk_text
from app.retrieval.bm25 import tokenize
from app.retrieval.chunk_vector import chunk_vector_store

LONG_DOC = (
    "第一段：本文介绍多模态素材中心的产品定位与整体架构，面向设计师与内容团队，"
    "强调统一素材管理、自动理解与跨模态检索。\n\n"
    "第二段：在入库环节，系统会先做去重与模态识别，然后抽取文本、转写语音并生成摘要。"
    "文档正文会按段落自动切分，保留原文出处，方便后续按片段召回。\n\n"
    "第三段：检索方面采用 BM25 与向量融合，再加入重排模型精排。对于长文档，"
    "系统支持片段级检索，可以直接定位到具体段落，而不是只返回整个文件。\n\n"
    "第四段：评测部分包含四十五组真实查询与五种检索策略，并用平均精度等指标量化对比。"
    "系统还提供 P95 延迟与高频查询的实时指标仪表盘。"
) + "\n\n" + (
    "第五段：除了按素材整体召回，长文档还会按段落切分存储，每一段都能作为独立检索单元，"
    "命中后直接给出原文出处，方便审阅与引用，这是传统整篇向量检索做不到的细节。\n\n"
    "第六段：片段检索同样参与重排精排，系统会把候选段落交给重排模型，"
    "再按相关度返回最合适的几个段落，供 Agent 组织带出处的回答。"
    "查询日志里也会记录片段检索的耗时与命中情况，与整篇检索一起纳入可观测体系。\n\n"
    "第七段：人工可以继续修正标签与描述，检索字段权重会随素材分布自适应调整，"
    "让整篇召回与片段召回保持一致的领域感知。"
)


def test_chunk_text_paragraph_smart_and_overlap():
    parts = chunk_text("第一段内容。\n\n第二段内容比较长" * 30)
    assert len(parts) > 1
    assert all(len(p) <= 420 for p in parts)
    # 连续超长文本窗口带重叠：相邻片段存在共同字符
    long = "这是一个很长的段落，" + "核心关键词ABC。" * 120
    pieces = chunk_text(long, max_chars=200, overlap=40)
    assert len(pieces) > 3
    assert len(set(pieces[0]) & set(pieces[1])) > 0


def _upload_doc(client, content: str):
    return client.post(
        "/api/upload",
        files={"files": ("长文档.txt", content.encode("utf-8"), "text/plain")},
    )


def test_document_pipeline_creates_chunks(client):
    r = _upload_doc(client, LONG_DOC)
    assert r.status_code == 200
    aid = r.json()["items"][0]["asset"]["id"]
    with SessionLocal() as db:
        assert db.get(Asset, aid).status == "ready"
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.asset_id == aid)
            .order_by(DocumentChunk.seq.asc())
            .all()
        )
        assert len(chunks) >= 2
        assert any("片段级检索" in c.text for c in chunks)


def test_passages_api_returns_source(client):
    _upload_doc(client, LONG_DOC)
    hits = client.get("/api/search/passages", params={"q": "片段级检索"}).json()["hits"]
    assert hits
    top = hits[0]
    assert top["modality"] == "document"
    assert "片段级检索" in top["text"]
    assert "chunk_id" in top and "seq" in top and "name" in top


def test_passages_lazy_backfill_for_old_docs(client):
    with SessionLocal() as db:
        db.add(Asset(
            owner="local",
            name="历史方案",
            original_filename="old.txt",
            modality="document",
            mime_type="text/plain",
            size_bytes=1,
            storage_path="uploads/document/old.txt",
            sha256="oldchunk1",
            status="ready",
            text_content=LONG_DOC,
        ))
        db.commit()
    hits = client.get("/api/search/passages", params={"q": "实时指标仪表盘"}).json()["hits"]
    assert hits and "指标仪表盘" in hits[0]["text"]
    with SessionLocal() as db:
        assert db.query(DocumentChunk).count() >= 2


def test_agent_find_passage_tool(client):
    _upload_doc(client, LONG_DOC)
    result = find_passage("片段级检索")
    assert result["ok"] is True
    assert result["assets"]
    assert result["passages"][0]["name"] == "长文档"
    assert "片段级检索" in result["passages"][0]["text"]


def _bag_vectors(texts: list[str]) -> list[list[float]]:
    out = []
    for t in texts:
        v = [0.0] * 64
        for tok in tokenize(t):
            v[hashlib.md5(tok.encode("utf-8")).digest()[0] % 64] = 1.0
        out.append(v)
    return out


def test_chunk_vectors_embedded_and_used_in_passages(client, monkeypatch):
    monkeypatch.setattr(llm_client, "embed_texts", _bag_vectors)
    _upload_doc(client, "苹果是一种常见水果，富含维生素与膳食纤维。\n\n食用苹果有助于保持健康。")
    _upload_doc(client, "香蕉种植需要温暖湿润的气候。\n\n采收后需要尽快冷链运输。")

    assert len(chunk_vector_store.keys(settings.embedding_model)) >= 2
    hits = client.get("/api/search/passages", params={"q": "苹果", "rerank": "false"}).json()["hits"]
    assert hits
    assert "苹果" in hits[0]["text"]


def test_transcript_timeline_chunks_semantic_passages(client):
    with SessionLocal() as db:
        db.add(Asset(
            owner="local",
            name="季度复盘录音",
            original_filename="rec.mp3",
            modality="audio",
            mime_type="audio/mpeg",
            size_bytes=1,
            storage_path="uploads/audio/rec.mp3",
            sha256="audioseg1",
            status="ready",
            transcript_segments=json.dumps(
                [
                    {"start": 0.0, "end": 20.0, "text": "先回顾一下本季度产品发布情况。"},
                    {"start": 20.0, "end": 45.0, "text": "增长放缓的主要原因是渠道投放转化不足。"},
                    {"start": 45.0, "end": 70.0, "text": "下阶段重点是留存与复购场景。"},
                ],
                ensure_ascii=False,
            ),
        ))
        db.commit()

    hits = client.get("/api/search/passages", params={"q": "渠道转化不足", "rerank": "false"}).json()["hits"]
    assert hits and hits[0]["modality"] == "audio"
    assert hits[0]["start"] == 20.0
    assert "渠道投放转化不足" in hits[0]["text"]

    with SessionLocal() as db:
        chunk = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.modality == "audio")
            .order_by(DocumentChunk.seq.asc())
            .first()
        )
        assert chunk is not None and chunk.start == 0.0
