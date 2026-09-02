"""素材助理 Agent：LangGraph 状态图。

流程：意图识别 → （按意图路由）工具调用 → 组织回答。
- 工具结果是事实来源，LLM 只负责把结果讲清楚；
- 无 LLM Key 时走规则意图 + 模板回答，功能照常（优雅降级）。
"""
from __future__ import annotations

import json
from typing import TypedDict

from langgraph.graph import END, StateGraph

from ..core.config import settings
from ..llm.client import client as llm_client, parse_json_text
from .tools import TOOL_REGISTRY

VALID_INTENTS = {"search", "detail", "profile", "generate", "transform", "chitchat"}

INTENT_PROMPT = (
    "你是素材库智能助手的意图识别模块。根据用户最后一条消息判断意图，只输出一个 JSON 对象，不要输出其他文字。格式："
    '{"intent": "search|detail|profile|generate|transform|chitchat", "query": "检索词（search 时填写，否则为空字符串）", '
    '"asset_id": 素材编号数字或 null}。'
    "说明：搜/找/查素材=search；问某个素材详情=detail；问整个库是什么领域/有什么=profile；"
    "生成图片/处理素材=generate/transform；闲聊=chitchat。"
)

ANSWER_PROMPT = (
    "你是多模态素材库的智能助手。请根据【工具结果】回答用户的问题，规则："
    "1) 只用工具结果里真实存在的素材，禁止编造；"
    "2) 引用素材时带编号，如 #3（名称）；"
    "3) 工具结果为空或失败时如实说明；"
    "4) 语言简洁自然，中文回答。\n\n【工具结果】\n{tool_text}"
)


class AgentState(TypedDict):
    messages: list[dict]
    intent: str
    params: dict
    tool_result: dict
    tool_used: str | None
    answer: str


# ---------- 意图识别 ----------

def _llm_intent(text: str) -> dict | None:
    content = llm_client.chat(
        [{"role": "system", "content": INTENT_PROMPT}, {"role": "user", "content": text}],
        max_tokens=600,
    )
    if not content:
        return None
    parsed = parse_json_text(content)
    if not parsed or parsed.get("intent") not in VALID_INTENTS:
        return None
    return parsed


def _rule_intent(text: str) -> dict:
    if any(k in text for k in ("画像", "领域", "统计", "库里有什么", "总结一下")):
        return {"intent": "profile"}
    if any(k in text for k in ("生成", "画一", "做一张", "帮我生成")):
        return {"intent": "generate", "query": text}
    if any(k in text for k in ("详情", "看看", "介绍下", "是什么素材")):
        import re

        m = re.search(r"#?\s*(\d+)", text)
        if m:
            return {"intent": "detail", "asset_id": int(m.group(1))}
    if any(k in text for k in ("搜", "找", "查", "有哪些", "有没有", "素材", "图")):
        return {"intent": "search", "query": text}
    return {"intent": "chitchat"}


def intent_node(state: AgentState) -> dict:
    last = state["messages"][-1]["content"]
    parsed = _llm_intent(last)
    if parsed is None:
        parsed = _rule_intent(last)
    return {
        "intent": parsed.get("intent", "chitchat"),
        "params": {
            "query": (parsed.get("query") or "").strip() or last,
            "asset_id": parsed.get("asset_id"),
        },
    }


# ---------- 工具调用 ----------

def _clean_prompt(text: str) -> str:
    """去掉"帮我/生成一张"这类指令前缀，把剩下的当画面描述。"""
    import re

    t = re.sub(r"^(请|帮我|麻烦你|给我)?\s*(生成|画|做|创作)?\s*(一张|一副|一幅|一个)?\s*", "", text.strip())
    return t.strip() or text.strip()


def _parse_transform(text: str) -> tuple[int, str, dict]:
    """从"压缩 #3""把#2转成mp4，最大边长800"这类指令里解析参数。"""
    import re

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


_TOOL_BY_INTENT = {
    "search": "search_assets",
    "detail": "get_asset_detail",
    "profile": "domain_profile",
    "generate": "generate_image",
    "transform": "transform_asset",
}


def tool_node(state: AgentState) -> dict:
    intent = state["intent"]
    params = state.get("params", {})
    if intent == "generate":
        result = TOOL_REGISTRY["generate_image"](_clean_prompt(params.get("query", "")))
    elif intent == "transform":
        asset_id, operation, tparams = _parse_transform(params.get("query", ""))
        result = TOOL_REGISTRY["transform_asset"](asset_id, operation, tparams)
    elif intent == "search":
        result = TOOL_REGISTRY["search_assets"](params.get("query", ""))
    elif intent == "detail":
        result = TOOL_REGISTRY["get_asset_detail"](int(params.get("asset_id") or 0))
    elif intent == "profile":
        result = TOOL_REGISTRY["domain_profile"]()
    else:
        result = {"ok": True, "summary": "", "assets": []}
    return {"tool_result": result, "tool_used": _TOOL_BY_INTENT.get(intent)}


# ---------- 组织回答 ----------

def _template_answer(message: str, tool_result: dict) -> str:
    if not tool_result.get("ok"):
        return tool_result.get("summary") or "抱歉，我暂时无法处理这个请求。"
    assets = tool_result.get("assets") or []
    if assets:
        lines = [f"找到 {len(assets)} 个相关素材："]
        for a in assets:
            desc = f" —— {a['description']}" if a.get("description") else ""
            lines.append(f"- #{a['id']} {a['name']}（{a['modality']}）{desc}")
        return "\n".join(lines)
    summary = tool_result.get("summary", "")
    if summary:
        return summary
    return "我是你的素材库助手，可以帮你搜素材、看素材详情、分析素材库领域。试试对我说：帮我搜夜景。"


def answer_node(state: AgentState) -> dict:
    tool_result = state.get("tool_result", {})
    tool_text = json.dumps(tool_result, ensure_ascii=False)[:1500]
    history = [{"role": m["role"], "content": m["content"]} for m in state["messages"][-4:]]
    answer = llm_client.chat(
        [{"role": "system", "content": ANSWER_PROMPT.format(tool_text=tool_text)}, *history],
        max_tokens=800,
    )
    if not answer:
        answer = _template_answer(state["messages"][-1]["content"], tool_result)
    return {"answer": answer}


def _route(state: AgentState) -> str:
    return "tool" if state["intent"] in {"search", "detail", "profile", "generate", "transform"} else "direct"


# ---------- 构建图 ----------

def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("intent", intent_node)
    graph.add_node("tool", tool_node)
    graph.add_node("answer", answer_node)
    graph.set_entry_point("intent")
    graph.add_conditional_edges("intent", _route, {"tool": "tool", "direct": "answer"})
    graph.add_edge("tool", "answer")
    graph.add_edge("answer", END)
    return graph.compile()


agent_app = build_graph()
