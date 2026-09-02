"""多模态 LLM 客户端。

设计原则（项目规范 02 章）：
- 优雅降级：没有 API Key 时返回 None，调用方走确定性兜底（不打标、仅关键词检索）；
- 所有网络调用统一超时 + 指数退避重试；
- 模型 ID 全部走配置，可在 .env 替换。
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


def parse_json_text(text: str) -> dict | None:
    """宽容解析 LLM 输出：去掉代码围栏，取第一个 JSON 对象。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


@dataclass
class VisionResult:
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    ocr: str | None = None


@dataclass
class SummaryResult:
    summary: str | None = None
    tags: list[str] = field(default_factory=list)


VISION_PROMPT = (
    "你是多模态素材管理系统的图像理解模块。请分析这张图片，"
    "只输出一个 JSON 对象，不要输出任何其他文字。格式："
    '{"description": "一句话中文描述，包含主体、场景、风格、氛围", '
    '"tags": ["3-8个中文关键词标签"], "ocr": "图片中出现的所有文字，没有则为空字符串"}'
)

SUMMARY_PROMPT = (
    "你是多模态素材管理系统的文档理解模块。请阅读下面的素材文本，"
    "只输出一个 JSON 对象，不要输出任何其他文字。格式："
    '{"summary": "3-5句话中文摘要，说明主题和关键信息", "tags": ["3-8个中文关键词标签"]}'
)


class MultimodalClient:
    def __init__(self) -> None:
        self.settings = settings

    # ---------- 网络基座 ----------

    def _post(self, url: str, payload: dict, headers: dict, timeout: float | None = None) -> dict:
        last_err: Exception | None = None
        for attempt in range(1, self.settings.llm_max_retries + 1):
            try:
                resp = httpx.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=timeout or self.settings.llm_timeout,
                )
                if resp.status_code >= 400:
                    raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                return resp.json()
            except (httpx.TimeoutException, httpx.TransportError, LLMError) as e:
                last_err = e
                if attempt < self.settings.llm_max_retries:
                    time.sleep(1.5**attempt)
        raise last_err if last_err else LLMError("unknown error")

    # ---------- 视觉理解 ----------

    def vision_describe(self, image_b64: str, mime: str = "image/jpeg") -> VisionResult | None:
        if not self.settings.siliconflow_api_key:
            return None
        payload = {
            "model": self.settings.vision_model,
            "temperature": 0.2,
            "max_tokens": 600,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                        {"type": "text", "text": VISION_PROMPT},
                    ],
                }
            ],
        }
        try:
            data = self._post(
                f"{self.settings.siliconflow_base_url}/chat/completions",
                payload,
                {"Authorization": f"Bearer {self.settings.siliconflow_api_key}"},
            )
        except Exception as e:
            logger.warning("vision_describe 失败（已降级）: %s", e)
            return None
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        parsed = parse_json_text(content)
        if not parsed:
            return VisionResult(description=content.strip() or None)
        return VisionResult(
            description=(parsed.get("description") or "").strip() or None,
            tags=[str(t).strip() for t in parsed.get("tags", []) if str(t).strip()],
            ocr=(parsed.get("ocr") or "").strip() or None,
        )

    # ---------- Embedding ----------

    def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        if not self.settings.siliconflow_api_key:
            return None
        try:
            data = self._post(
                f"{self.settings.siliconflow_base_url}/embeddings",
                {"model": self.settings.embedding_model, "input": texts},
                {"Authorization": f"Bearer {self.settings.siliconflow_api_key}"},
            )
        except Exception as e:
            logger.warning("embed_texts 失败（已降级为仅关键词检索）: %s", e)
            return None
        return [d["embedding"] for d in data.get("data", [])]

    # ---------- 文档摘要 ----------

    def summarize_text(self, text: str) -> SummaryResult | None:
        if not self.settings.deepseek_api_key:
            return None
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.2,
            "max_tokens": 500,
            "messages": [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": text[:3000]},
            ],
        }
        try:
            data = self._post(
                f"{self.settings.deepseek_base_url}/chat/completions",
                payload,
                {"Authorization": f"Bearer {self.settings.deepseek_api_key}"},
            )
        except Exception as e:
            logger.warning("summarize_text 失败（已降级）: %s", e)
            return None
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        parsed = parse_json_text(content)
        if not parsed:
            return SummaryResult(summary=content.strip() or None)
        return SummaryResult(
            summary=(parsed.get("summary") or "").strip() or None,
            tags=[str(t).strip() for t in parsed.get("tags", []) if str(t).strip()],
        )


client = MultimodalClient()
