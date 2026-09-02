"""素材助理 Agent：LangGraph 状态图（深度二期：LLM 结构化任务规划 + 多步循环执行）。

流程：planner（把用户请求拆成工具步骤）→ tool（循环执行）→ answer（汇总组织回答）。
- 工具结果是事实来源，LLM 只负责规划与组织语言；
- 无 LLM Key 或规划失败时走规则规划（单步），功能照常。
"""
from __future__ import annotations

import json
import re
from typing import TypedDict

from langgraph.graph import END, StateGraph

from ..llm.client import client as llm_client, parse_json_text
from .tools import TOOL_DESCRIPTIONS, TOOL_REGISTRY

VALID_TOOLS = set(TOOL_REGISTRY.keys())
_TOOL_INTENT = {
    "search_assets": "search",
    "get_asset_detail": "detail",
    "domain_profile": "profile",
    "generate_image": "generate",
    "transform_asset": "transform",
    "find_moment": "moment",
}

PLANNER_PROMPT = (
    "你是素材库智能助手的任务规划器。可用工具：\n"
    + "\n".join(
        f"- {t['name']}: {t['description']} 参数 {json.dumps(t['params'], ensure_ascii=False)}"
        for t in TOOL_DESCRIPTIONS
    )
    + "\n根据用户请求把任务拆成 1-3 个工具步骤（有明确先后关系才多步，例如「先压缩再生成封面」），"
    "只输出一个 JSON 对象，不要输出其他文字："
    '{"steps": [{"tool": "工具名", "args": {参数}}]}。闲聊或不需要工具时输出 {"steps": []}。'
)

ANSWER_PROMPT = (
    "你是多模态素材库的智能助手。请根据【工具结果】回答用户的问题，规则："
    "1) 只用工具结果里真实存在的素材，禁止编造；"
    "2) 引用素材时带编号，如 #3（名称）；"
    "3) 工具结果为空或失败时如实说明；"
    "4) 涉及时间戳时用 分钟:秒 格式，如 01:23；"
    "5) 语言简洁自然，中文回答。\n\n【工具结果】\n{tool_text}"
)


class AgentState(TypedDict):
    messages: list[dict]
    plan: list[dict]
    step_index: int
    results: list[dict]
    tool_result: dict
    tool_used: str | None
    intent: str
    answer: str


# ---------- 规则规划（兜底） ----------

def _rule_intent(text: str) -> dict:
    if any(k in text for k in ("画像", "领域", "统计", "库里有什么", "总结一下")):
        return {"intent": "profile"}
    if any(k in text for k in ("那段", "说过", "提到", "里面讲了", "说了什么")):
        return {"intent": "moment", "query": text}
    if any(k in text for k in ("生成", "画一", "做一张", "帮我生成")):
        return {"intent": "generate", "query": text}
    if any(k in text for k in ("压缩", "缩放", "转格式", "转换", "转成", "尺寸", "裁剪", "处理")):
        return {"intent": "transform", "query": text}
    if any(k in text for k in ("详情", "看看", "介绍下", "是什么素材")):
        m = re.search(r"#?\s*(\d+)", text)
        if m:
            return {"intent": "detail", "asset_id": int(m.group(1))}
    if any(k in text for k in ("搜", "找", "查", "有哪些", "有没有", "素材", "图")):
        return {"intent": "search", "query": text}
    return {"intent": "chitchat"}


def _clean_prompt(text: str) -> str:
    t = re.sub(r"^(请|帮我|麻烦你|给我)?\s*(生成|画|做|创作)?\s*(一张|一副|一幅|一个)?\s*", "", text.strip())
    return t.strip() or text.strip()


def _parse_transform(text: str) -> tuple[int, str, dict]:
    m = re.search(r"#?\s*(\d+)", text)
    asset_id = int(m.group(1)) if m else 0
    operation = "compress"
    params: dict = {}
    if any(k in text for k in ("转格式", "转换", "转成", "convert")):
        operation = "convert"
        fm = re.search(r"(?:转成|转换成|转格式为|convert to|format)\s*[是为]?\s*([a-zA-Z0-9]+)", text)
        if fm:
            params["format"] = fm.group(1).lower()
    elif any(k in text for k in ("缩放", "尺寸", "裁剪", "最大边长", "resize")):
        operation = "resize"
        sm = re.search(r"(\d{3,4})", text)
        if sm:
            params["max_side"] = int(sm.group(1))
    return asset_id, operation, params


def _rule_plan(text: str) -> list[dict]:
    rule = _rule_intent(text)
    intent = rule["intent"]
    if intent == "search":
        return [{"tool": "search_assets", "args": {"query": rule.get("query") or text}}]
    if intent == "detail":
        return [{"tool": "get_asset_detail", "args": {"asset_id": rule.get("asset_id")}}]
    if intent == "profile":
        return [{"tool": "domain_profile", "args": {}}]
    if intent == "moment":
        return [{"tool": "find_moment", "args": {"query": text}}]
    if intent == "generate":
        return [{"tool": "generate_image", "args": {"prompt": _clean_prompt(text)}}]
    if intent == "transform":
        asset_id, operation, params = _parse_transform(text)
        return [{"tool": "transform_asset", "args": {"asset_id": asset_id, "operation": operation, "params": params}}]
    return []


# ---------- 节点 ----------

def planner_node(state: AgentState) -> dict:
    last = state["messages"][-1]["content"]
    plan: list[dict] = []
    content = llm_client.chat(
        [{"role": "system", "content": PLANNER_PROMPT}, {"role": "user", "content": last}],
        max_tokens=700,
    )
    if content:
        parsed = parse_json_text(content)
        steps = (parsed or {}).get("steps")
        if isinstance(steps, list):
            for s in steps:
                tool = s.get("tool")
                args = s.get("args") if isinstance(s.get("args"), dict) else {}
                if tool in VALID_TOOLS and isinstance(args, dict):
                    plan.append({"tool": tool, "args": args})
    if not plan:
        plan = _rule_plan(last)
    intent = _TOOL_INTENT.get(plan[0]["tool"], "chitchat") if plan else "chitchat"
    return {
        "plan": plan,
        "step_index": 0,
        "results": [],
        "intent": intent,
        "tool_result": {"ok": True, "summary": "", "assets": []},
        "tool_used": None,
    }


def tool_node(state: AgentState) -> dict:
    idx = state["step_index"]
    plan = state.get("plan", [])
    if idx >= len(plan):
        return {"tool_result": {"ok": False, "summary": "没有可执行步骤", "assets": []}, "tool_used": None, "step_index": idx}
    step = plan[idx]
    tool, args = step["tool"], step.get("args", {})
    try:
        if tool == "search_assets":
            result = TOOL_REGISTRY["search_assets"](args.get("query", ""))
        elif tool == "get_asset_detail":
            result = TOOL_REGISTRY["get_asset_detail"](int(args.get("asset_id") or 0))
        elif tool == "domain_profile":
            result = TOOL_REGISTRY["domain_profile"]()
        elif tool == "generate_image":
            result = TOOL_REGISTRY["generate_image"](args.get("prompt", ""))
        elif tool == "transform_asset":
            result = TOOL_REGISTRY["transform_asset"](
                int(args.get("asset_id") or 0), args.get("operation", "compress"), args.get("params") or {}
            )
        elif tool == "find_moment":
            result = TOOL_REGISTRY["find_moment"](args.get("query", ""))
        else:
            result = {"ok": False, "summary": f"未知工具 {tool}", "assets": []}
    except Exception as e:
        result = {"ok": False, "summary": f"工具执行失败: {e}", "assets": []}
    return {
        "tool_result": result,
        "tool_used": tool,
        "results": state.get("results", []) + [result],
        "step_index": idx + 1,
    }


def _fmt_ts(seconds: float | int | None) -> str:
    s = int(seconds or 0)
    return f"{s // 60:02d}:{s % 60:02d}"


def _template_answer(results: list[dict]) -> str:
    lines: list[str] = []
    for r in results:
        if not r.get("ok"):
            lines.append(r.get("summary") or "该步骤未成功。")
            continue
        moments = r.get("moments")
        if moments:
            lines.append(f"找到 {len(moments)} 处相关内容：")
            for m in moments[:5]:
                lines.append(f"- {m['name']}（{_fmt_ts(m['start'])} - {_fmt_ts(m['end'])}）：{m['snippet'][:60]}")
            continue
        assets = r.get("assets") or []
        if assets:
            lines.append(f"相关素材 {len(assets)} 个：")
            for a in assets[:5]:
                desc = f" —— {a['description']}" if a.get("description") else ""
                lines.append(f"- #{a['id']} {a['name']}（{a['modality']}）{desc}")
            continue
        if r.get("summary"):
            lines.append(r["summary"])
    return "\n".join(lines) or "我是你的素材库助手，可以帮你搜素材、看详情、分析领域、找音频里的某段话、生成或处理素材。"


def answer_node(state: AgentState) -> dict:
    results = state.get("results", [])
    tool_text = json.dumps(results, ensure_ascii=False)[:2000]
    history = [{"role": m["role"], "content": m["content"]} for m in state["messages"][-4:]]
    answer = llm_client.chat(
        [{"role": "system", "content": ANSWER_PROMPT.format(tool_text=tool_text)}, *history],
        max_tokens=800,
    )
    if not answer:
        answer = _template_answer(results)
    return {"answer": answer}


def _route(state: AgentState) -> str:
    return "tool" if state["step_index"] < len(state.get("plan", [])) else "answer"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("planner", planner_node)
    graph.add_node("tool", tool_node)
    graph.add_node("answer", answer_node)
    graph.set_entry_point("planner")
    graph.add_conditional_edges("planner", _route, {"tool": "tool", "answer": "answer"})
    graph.add_conditional_edges("tool", _route, {"tool": "tool", "answer": "answer"})
    graph.add_edge("answer", END)
    return graph.compile()


agent_app = build_graph()
