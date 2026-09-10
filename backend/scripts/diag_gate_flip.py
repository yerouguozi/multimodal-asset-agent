"""一次性诊断：E1 vs E2 逐查询 Recall@1 对比，定位跨语言查询上的翻转。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="mma_diag_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'diag.db'}"
os.environ["VECTOR_STORE_PATH"] = str(_TMP / "vectors.npz")
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import base64  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal, init_db  # noqa: E402
from app.llm.client import client as llm_client  # noqa: E402
from app.models import Asset, Tag  # noqa: E402
from app.retrieval import search as search_service  # noqa: E402
from app.retrieval import gate as gate_module  # noqa: E402
from app.retrieval.vector_store import vector_store  # noqa: E402
from scripts.eval_data import CORPUS, IMAGE_DRAWERS, QUERIES, VISUAL_QUERIES  # noqa: E402


def main() -> int:
    init_db()
    with SessionLocal() as db:
        for item in CORPUS:
            asset = Asset(
                name=item["name"], original_filename=item["name"], modality=item["modality"],
                mime_type="", size_bytes=0,
                storage_path=f"uploads/{item['modality']}/{item['name']}",
                sha256=item["name"], status="ready",
                description=item.get("description"), ocr_text=item.get("ocr"),
                transcript=item.get("transcript"), text_content=item.get("text_content"),
            )
            db.add(asset)
            db.flush()
            for t in item["tags"]:
                db.add(Tag(asset_id=asset.id, name=t, source="llm"))
        db.commit()
    for item in CORPUS:
        drawer = IMAGE_DRAWERS.get(item["name"])
        if drawer:
            f = _TMP / "uploads" / item["modality"] / item["name"]
            f.parent.mkdir(parents=True, exist_ok=True)
            drawer(f)
    with SessionLocal() as db:
        assets = db.query(Asset).all()
        id_by_name = {a.name: a.id for a in assets}
        texts = [" ".join(p for p in [a.description, a.ocr_text, a.transcript, a.text_content] if p)[:1500] for a in assets]
        vecs = llm_client.embed_texts(texts)
        if vecs:
            for a, v in zip(assets, vecs):
                vector_store.add(a.id, v, settings.embedding_model)
        vl = 0
        for a in assets:
            if a.modality != "image":
                continue
            f = _TMP / "uploads" / "image" / a.name
            if not f.exists():
                continue
            v = llm_client.embed_image(base64.b64encode(f.read_bytes()).decode("ascii"), "image/png")
            if v:
                vector_store.add(a.id, v, settings.vl_embedding_model)
                vl += 1
    g = gate_module.build_gate(llm_client.embed_texts)
    gate_module.set_gate(g)
    print(f"向量就绪，VL {vl} 张，阈值 {g.threshold:+.4f}\n")

    print(f"{'查询':<24} {'E1@1':>5} {'E2@1':>5}  门控(v2)  margin")
    flips = []
    with SessionLocal() as db:
        for q in QUERIES:
            name_id = {n: id_by_name[n] for n in q["relevant"] if n in id_by_name}
            hits1 = [h[0].id for h in search_service.search(db, q["query"], limit=10, strategy="gate_kw")]
            hits2 = [h[0].id for h in search_service.search(db, q["query"], limit=10, strategy="gate")]
            rel = set(name_id.values())
            r1 = 1 if (hits1 and hits1[0] in rel) else 0
            r2 = 1 if (hits2 and hits2[0] in rel) else 0
            if r1 != r2:
                d = gate_module.decide(q["query"], llm_client.embed_texts([q["query"]])[0])
                print(f"{q['query']:<24} {r1:>5} {r2:>5}  {'视觉' if d.is_visual else '非视觉':^8}  {d.margin:+.3f}")
                flips.append((q["query"], r1, r2))
    print(f"\n翻转 {len(flips)} 条")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
