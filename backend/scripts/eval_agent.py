r"""Agent 回答质量评测：规划命中 / 引用合法 / 忠实度（LLM 裁判）/ 延迟。

用法（backend/ 下）：
    .\.venv\Scripts\python scripts\eval_agent.py

说明：
- 使用临时数据库，与开发数据隔离，评测可复现；
- 需要 DEEPSEEK_API_KEY（规划与回答）+ SILICONFLOW_API_KEY（检索向量/重排）；
  无 Key 时自动降级为规则规划 + 模板回答，报告会注明（忠实度裁判需要 LLM，跳过）；
- "防幻觉两道防线"从设计描述变成数字：引用合法率 + 忠实度通过率；
- 报告输出到 docs/eval-reports/Agent质量评测.md。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="mma_agent_eval_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'eval.db'}"
os.environ["VECTOR_STORE_PATH"] = str(_TMP / "vectors.npz")
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal, init_db  # noqa: E402
from app.llm.client import client as llm_client, parse_json_text  # noqa: E402
from app.agent.graph import agent_app  # noqa: E402
from app.models import Asset, Tag  # noqa: E402
from scripts.eval_data import CORPUS  # noqa: E402

REPORT_PATH = Path(__file__).resolve().parents[2] / "docs" / "eval-reports" / "Agent质量评测.md"

FAITHFULNESS_PROMPT = (
    "你是评测裁判。根据【工具结果】判断【回答】里的事实性内容是否全部被工具结果支撑："
    "允许换说法和组织语言，不允许编造素材、编号、数字、时间戳或工具结果里没有的能力。"
    "只输出一个 JSON 对象，不要输出其他文字："
    '{"supported": true 或 false, "reason": "一句话理由"}'
)

# (查询, 预期工具, 期望带引用, 期望如实说空)
CASES: list[dict] = [
    {"query": "找一些城市夜景的图片", "tool": "search_assets", "cite": True},
    {"query": "有没有适合助眠的音频", "tool": "search_assets", "cite": True},
    {"query": "深度学习相关的资料有哪些", "tool": "search_assets", "cite": True},
    {"query": "white noise for sleep", "tool": "search_assets", "cite": True},
    {"query": "库里都有些什么素材", "tool": "domain_profile", "cite": False},
    {"query": "会议录音里提到了什么", "tool": "find_moment", "cite": False},
    {"query": "从招聘简章里找一下岗位要求那段", "tool": "find_passage", "cite": False},
    {"query": "量子物理相关的素材", "tool": "search_assets", "cite": False, "empty": True},
    {"query": "#1 这个素材的详情", "tool": "get_asset_detail", "cite": True},
]

_EMPTY_HINTS = ("没有找到", "未找到", "没有相关", "暂无", "没有符合", "找不到", "没有检索到")


def seed_corpus() -> None:
    init_db()
    with SessionLocal() as db:
        for item in CORPUS:
            asset = Asset(
                name=item["name"],
                original_filename=item["name"],
                modality=item["modality"],
                mime_type="",
                size_bytes=0,
                storage_path=f"uploads/{item['modality']}/{item['name']}",
                sha256=item["name"],
                status="ready",
                description=item.get("description"),
                ocr_text=item.get("ocr"),
                transcript=item.get("transcript"),
                text_content=item.get("text_content"),
            )
            db.add(asset)
            db.flush()
            for t in item["tags"]:
                db.add(Tag(asset_id=asset.id, name=t, source="llm"))
        db.commit()


def run_case(case: dict) -> dict:
    t0 = time.perf_counter()
    final = agent_app.invoke(
        {
            "messages": [{"role": "user", "content": case["query"]}],
            "plan": [],
            "step_index": 0,
            "results": [],
            "tool_result": {},
            "tool_used": None,
            "intent": "",
            "answer": "",
        }
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    answer = final.get("answer") or ""
    tools = [s["tool"] for s in final.get("plan", [])]
    results = final.get("results", [])
    tool_text = json.dumps(results, ensure_ascii=False)[:1500]

    cited = "#1" in answer or "#2" in answer or "#3" in answer or "#4" in answer or "#5" in answer
    citation_ok = "不在本轮工具结果中" not in answer  # 引用校验未触发 = 引用全部合法
    honest_empty = True
    if case.get("empty"):
        honest_empty = any(h in answer for h in _EMPTY_HINTS) and not (
            cited and "不在本轮工具结果中" not in answer
        )

    out = {
        "query": case["query"],
        "expect_tool": case["tool"],
        "tools": tools,
        "tool_ok": case["tool"] in tools,
        "answer_len": len(answer),
        "cited": cited,
        "citation_ok": citation_ok,
        "honest_empty": honest_empty,
        "latency_ms": latency_ms,
        "answer": answer,
        "faithful": None,
        "judge_reason": "",
    }
    # 忠实度裁判：有工具结果且有回答时，让 LLM 判断答案是否被结果支撑
    if results and answer and llm_client.settings.deepseek_api_key:
        try:
            content = llm_client.chat(
                [
                    {"role": "system", "content": FAITHFULNESS_PROMPT},
                    {"role": "user", "content": f"【工具结果】\n{tool_text}\n\n【回答】\n{answer[:1200]}"},
                ],
                temperature=0.0,
                max_tokens=300,
            )
            parsed = parse_json_text(content or "")
            if parsed and "supported" in parsed:
                out["faithful"] = bool(parsed["supported"])
                out["judge_reason"] = str(parsed.get("reason", ""))[:200]
        except Exception as e:  # 裁判失败不影响其他指标
            out["judge_reason"] = f"裁判失败: {e}"
    return out


def write_report(rows: list[dict], llm_mode: bool) -> None:
    n = len(rows)
    tool_hits = sum(1 for r in rows if r["tool_ok"])
    cite_cases = [r for r, c in zip(rows, CASES) if c["cite"]]
    cite_ok = sum(1 for r in cite_cases if r["citation_ok"] and r["cited"])
    empty_cases = [r for r, c in zip(rows, CASES) if c.get("empty")]
    honest_ok = sum(1 for r in empty_cases if r["honest_empty"])
    judged = [r for r in rows if r["faithful"] is not None]
    faithful_ok = sum(1 for r in judged if r["faithful"])
    latencies = sorted(r["latency_ms"] for r in rows)
    p95 = latencies[max(0, int(round(len(latencies) * 0.95)) - 1)] if latencies else 0

    lines = [
        "# Agent 回答质量评测",
        "",
        f"- 生成时间：{date.today().isoformat()}",
        f"- 规划模型：{settings.llm_model}（{'LLM 规划' if llm_mode else '规则规划兜底（无 DEEPSEEK_API_KEY）'}）",
        f"- 用例：{n} 条（检索 4 / 画像 1 / 时间戳定位 1 / 片段定位 1 / 库外反例 1 / 详情 1）",
        "",
        "## 逐用例结果",
        "",
        "| 查询 | 预期工具 | 实际工具 | 工具命中 | 引用 | 忠实度 | 延迟 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        faithful = "—" if r["faithful"] is None else ("✓" if r["faithful"] else f"✗ {r['judge_reason'][:40]}")
        lines.append(
            f"| {r['query']} | {r['expect_tool']} | {'→'.join(r['tools']) or '—'} | "
            f"{'✓' if r['tool_ok'] else '✗'} | {'✓' if r['citation_ok'] and r['cited'] else ('合法' if r['citation_ok'] else '✗ 违规')} | "
            f"{faithful} | {r['latency_ms']}ms |"
        )
    lines += [
        "",
        "## 汇总",
        "",
        f"- 工具规划命中：{tool_hits}/{n}",
        f"- 引用合法率：{cite_ok}/{len(cite_cases)}（期望引用的用例中，引用存在且全部通过硬校验）",
        f"- 库外反例如实说空：{honest_ok}/{len(empty_cases)}",
        f"- 忠实度通过（LLM 裁判）：{faithful_ok}/{len(judged)}"
        + ("" if judged else "（裁判不可用，跳过）"),
        f"- 延迟：平均 {sum(latencies) // max(1, len(latencies))}ms / P95 {p95}ms",
        "",
        "## 结论",
        "",
        "- 防幻觉第二道防线（引用硬校验）可用数字说话：引用合法率即上方指标；",
        "- 忠实度裁判衡量「答案是否被工具结果支撑」，是 Prompt 约束之外的可量化补充；",
        "- 库外反例验证「工具结果为空时如实说明」，防编造话术落地。",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入: {REPORT_PATH}")


def main() -> int:
    print("== 初始化隔离评测环境 ==")
    seed_corpus()
    llm_mode = bool(settings.deepseek_api_key)
    print(f"语料: {len(CORPUS)} 素材, 用例: {len(CASES)}, 模式: {'LLM 规划' if llm_mode else '规则兜底'}")

    rows: list[dict] = []
    for i, case in enumerate(CASES, 1):
        print(f"\n[{i}/{len(CASES)}] {case['query']}")
        r = run_case(case)
        rows.append(r)
        faithful = "—" if r["faithful"] is None else ("✓" if r["faithful"] else "✗")
        print(f"  工具={'✓' if r['tool_ok'] else '✗'}({','.join(r['tools']) or '无'}) "
              f"引用={'✓' if r['citation_ok'] else '✗'} 忠实度={faithful} 延迟={r['latency_ms']}ms")

    write_report(rows, llm_mode)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
