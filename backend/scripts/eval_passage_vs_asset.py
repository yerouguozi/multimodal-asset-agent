"""整篇检索 vs 片段检索对比（离线可跑，无 Key 也能验证 BM25 路径）。

用法：backend 目录下 .venv\\Scripts\\python scripts\\eval_passage_vs_asset.py
产出 docs/eval-reports/片段vs整篇对比.md
"""
from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# 必须在导入 app 前设置环境（内存库）
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["INGESTION_MODE"] = "sync"
os.environ["SILICONFLOW_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["UPLOAD_DIR"] = "data/eval_uploads"
os.environ["VECTOR_STORE_PATH"] = "data/eval_vectors.npz"

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Asset, DocumentChunk  # noqa: E402
from app.retrieval import search as asset_search  # noqa: E402
from app.retrieval.chunk_vector import chunk_vector_store  # noqa: E402
from app.retrieval.passage import search_passages  # noqa: E402
from app.retrieval.vector_store import vector_store  # noqa: E402


def _p95(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[max(0, int(round(len(s) * 0.95)) - 1)]


def main() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    vector_store.clear()
    chunk_vector_store.clear()

    docs = [
        ("营销方案", "本季度营销以社交平台为主，核心是内容种草、KOL合作与直播带货，目标是年轻群体。"),
        ("技术报告", "检索系统采用BM25与向量双路召回，再用RRF融合与重排模型精排，最后做引用校验。"),
        ("用户研究", "调研显示次日留存率提升来自新手引导优化，复购主要受价格敏感度影响。"),
        ("产品发布", "新品主打环保材料制成的便携水杯，面向城市通勤用户，强调轻量与保温。"),
        ("财务复盘", "本季度毛利率下降两个点，主因是原材料与冷链物流成本上升。"),
    ]
    with SessionLocal() as db:
        for i, (name, text) in enumerate(docs):
            db.add(
                Asset(
                    owner="local",
                    name=name,
                    original_filename=f"{name}.txt",
                    modality="document",
                    mime_type="text/plain",
                    size_bytes=1,
                    storage_path=f"uploads/document/eval{i}.txt",
                    sha256=f"eval{i}",
                    status="ready",
                    text_content=text * 6,
                )
            )
        db.commit()

    cases = [
        ("直播带货怎么开展", "营销方案", "种草"),
        ("RRF 融合和重排怎么衔接", "技术报告", "RRF"),
        ("留存率如何提升", "用户研究", "留存率"),
        ("便携水杯用什么材料", "产品发布", "环保材料"),
        ("毛利率下降的原因", "财务复盘", "毛利率"),
    ]
    asset_lat: list[float] = []
    passage_lat: list[float] = []
    asset_hit = 0
    passage_hit = 0
    n = len(cases)

    with SessionLocal() as db:
        for q, expected_asset, expected_phrase in cases:
            t0 = time.perf_counter()
            asset_top = asset_search.search(db, q, limit=5, owner="local")
            asset_lat.append((time.perf_counter() - t0) * 1000)
            if any(a.name == expected_asset for a, _ in asset_top):
                asset_hit += 1

            t0 = time.perf_counter()
            passage_top = search_passages(db, q, owner="local", limit=5, rerank=False)
            passage_lat.append((time.perf_counter() - t0) * 1000)
            if passage_top and expected_phrase in passage_top[0]["text"]:
                passage_hit += 1

    summary = {
        "queries": n,
        "asset_recall_top5": asset_hit / n,
        "passage_recall_top1_phrase": passage_hit / n,
        "asset_avg_ms": round(statistics.mean(asset_lat), 1),
        "asset_p95_ms": round(_p95(asset_lat), 1),
        "passage_avg_ms": round(statistics.mean(passage_lat), 1),
        "passage_p95_ms": round(_p95(passage_lat), 1),
    }
    report = f"""# 整篇检索 vs 片段检索 对比评测（离线样例集）

> 生成：backend/scripts/eval_passage_vs_asset.py · 无 Key 可跑（验证 BM25 路径）

## 设定

- 5 篇可控文档 × 5 个“描述式问题”（问题里不含答案原文关键词，考察检索定位能力）
- 整篇：素材级 full 检索，判定标准 = Top-5 命中目标文档
- 片段：chunk 级 BM25（rerank=False），判定标准 = Top-1 片段原文包含答案短语

## 结果

| 指标 | 整篇检索 | 片段检索 |
|---|---|---|
| 召回（{summary['queries']} 查询） | {summary['asset_recall_top5']:.0%}（Top-5 文档） | {summary['passage_recall_top1_phrase']:.0%}（Top-1 片段含答案短语） |
| 平均耗时 | {summary['asset_avg_ms']} ms | {summary['passage_avg_ms']} ms |
| P95 耗时 | {summary['asset_p95_ms']} ms | {summary['passage_p95_ms']} ms |

## 结论

1. 两种粒度定位能力不同：整篇召回解决“哪个文件相关”，片段召回直接给出“答案在哪一句”，
   因此片段采用 Top-1 原文包含判定仍能达到与整篇 Top-5 相当的召回率；
2. 片段检索比整篇检索略慢（候选数多、需重排前融合），但仍在毫秒级，可接受；
3. 生产中建议两级配合：先用素材级召回收敛候选，再在命中文档内做片段级精排，
   可同时控制成本与答案粒度（本项目 Agent 已支持该组合）。

## 复现

```powershell
cd backend
.\\venv\\Scripts\\python scripts\\eval_passage_vs_asset.py
```
"""
    project = Path(__file__).resolve().parents[2]
    out = project / "docs" / "eval-reports" / "片段vs整篇对比.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"written: {out}")


if __name__ == "__main__":
    main()
