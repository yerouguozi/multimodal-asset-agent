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
from pathlib import Path

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


@dataclass
class DomainInsight:
    labels: list[str] = field(default_factory=list)
    summary: str | None = None


DOMAIN_PROMPT = (
    "你是素材库分析模块。根据模态分布和热门标签，判断这个素材库主要属于什么领域。"
    "只输出一个 JSON 对象，不要输出任何其他文字。格式："
    '{"labels": ["2-4个领域名称，如 电商设计素材库"], "summary": "一句话总结这个素材库的特点"}'
)

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

    def vision_describe(self, image_b64: str, mime: str = "image/jpeg", model: str | None = None) -> VisionResult | None:
        """视觉理解；model 为空时用 settings.vision_model（默认大模型），调用方可按需路由。"""
        if not self.settings.siliconflow_api_key:
            return None
        payload = {
            "model": model or self.settings.vision_model,
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

    # ---------- 重排 ----------

    def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        """SiliconFlow /rerank：给候选文档按相关性重新打分。失败降级返回 None。"""
        if not self.settings.siliconflow_api_key or not documents:
            return None
        payload = {
            "model": self.settings.rerank_model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        }
        try:
            data = self._post(
                f"{self.settings.siliconflow_base_url}/rerank",
                payload,
                {"Authorization": f"Bearer {self.settings.siliconflow_api_key}"},
            )
        except Exception as e:
            logger.warning("rerank 失败（已降级）: %s", e)
            return None
        results = data.get("results", [])
        if not results:
            return None
        scores = [0.0] * len(documents)
        for r in results:
            idx = r.get("index")
            if isinstance(idx, int) and 0 <= idx < len(documents):
                scores[idx] = float(r.get("relevance_score", 0.0))
        return scores

    # ---------- 通用对话 ----------

    def chat(self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 800) -> str | None:
        """通用对话补全（DeepSeek）。无 Key 或失败返回 None，供 Agent 走确定性兜底。"""
        if not self.settings.deepseek_api_key:
            return None
        payload = {
            "model": self.settings.llm_model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        try:
            data = self._post(
                f"{self.settings.deepseek_base_url}/chat/completions",
                payload,
                {"Authorization": f"Bearer {self.settings.deepseek_api_key}"},
            )
        except Exception as e:
            logger.warning("chat 失败（已降级）: %s", e)
            return None
        message = (data.get("choices") or [{}])[0].get("message", {})
        content = message.get("content", "") or message.get("reasoning_content", "") or ""
        return content.strip() or None
    # ---------- 多模态 embedding ----------

    def _embed(self, input, model: str) -> list[list[float]] | None:
        if not self.settings.siliconflow_api_key:
            return None
        try:
            data = self._post(
                f"{self.settings.siliconflow_base_url}/embeddings",
                {"model": model, "input": input},
                {"Authorization": f"Bearer {self.settings.siliconflow_api_key}"},
            )
        except Exception as e:
            logger.warning("embedding 失败（模型 %s）: %s", model, e)
            return None
        return [d["embedding"] for d in data.get("data", [])]

    def embed_texts_vl(self, texts: list[str]) -> list[list[float]] | None:
        """用多模态 embedding 模型嵌入文本查询，与图片向量同一空间。"""
        if not self.settings.vl_embed_enabled:
            return None
        return self._embed(texts, self.settings.vl_embedding_model)

    def embed_image(self, image_b64: str, mime: str = "image/jpeg") -> list[float] | None:
        """用多模态 embedding 模型嵌入图片（data URL 输入）。"""
        if not self.settings.vl_embed_enabled:
            return None
        vecs = self._embed(f"data:{mime};base64,{image_b64}", self.settings.vl_embedding_model)
        return vecs[0] if vecs else None


    def generate_image(self, prompt: str) -> bytes | None:
        """SiliconFlow /images/generations：返回图片二进制；失败降级返回 None。"""
        if not self.settings.siliconflow_api_key:
            return None
        url = f"{self.settings.siliconflow_base_url}/images/generations"
        payload = {
            "model": self.settings.image_gen_model,
            "prompt": prompt,
            "image_size": self.settings.image_gen_size,
            "batch_size": 1,
        }
        try:
            data = self._post(
                url,
                payload,
                {"Authorization": f"Bearer {self.settings.siliconflow_api_key}"},
                timeout=180.0,
            )
        except Exception as e:
            logger.warning("generate_image 失败（已降级）: %s", e)
            return None
        item = (data.get("data") or [{}])[0]
        b64 = item.get("b64_json")
        if b64:
            return base64.b64decode(b64)
        image_url = item.get("url")
        if image_url:
            try:
                resp = httpx.get(image_url, timeout=180.0)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                logger.warning("下载生成图片失败: %s", e)
                return None
        return None
    # ---------- 领域洞察 ----------

    def domain_insight(self, modality_summary: str, top_tags: list[str]) -> DomainInsight | None:
        """根据模态分布与标签，让 LLM 给出领域名称与一句话总结。"""
        if not self.settings.deepseek_api_key:
            return None
        text = f"模态分布：{modality_summary}\n热门标签：{'、'.join(top_tags)}"
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.2,
            "max_tokens": 1200,
            "messages": [
                {"role": "system", "content": DOMAIN_PROMPT},
                {"role": "user", "content": text[:1500]},
            ],
        }
        try:
            data = self._post(
                f"{self.settings.deepseek_base_url}/chat/completions",
                payload,
                {"Authorization": f"Bearer {self.settings.deepseek_api_key}"},
            )
        except Exception as e:
            logger.warning("domain_insight 失败（已降级）: %s", e)
            return None
        message = (data.get("choices") or [{}])[0].get("message", {})
        # 推理模型可能把答案写进 reasoning_content 而 content 为空，做兜底
        content = message.get("content", "") or message.get("reasoning_content", "") or ""
        parsed = parse_json_text(content)
        if not parsed:
            return None
        return DomainInsight(
            labels=[str(x).strip() for x in parsed.get("labels", []) if str(x).strip()],
            summary=(parsed.get("summary") or "").strip() or None,
        )
    # ---------- 语音转写 ----------

    def _post_multipart(self, url: str, data: dict, files: dict, headers: dict) -> dict:
        last_err: Exception | None = None
        for attempt in range(1, self.settings.llm_max_retries + 1):
            try:
                resp = httpx.post(
                    url,
                    data=data,
                    files=files,
                    headers=headers,
                    timeout=self.settings.llm_timeout,
                )
                if resp.status_code >= 400:
                    raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                return resp.json()
            except (httpx.TimeoutException, httpx.TransportError, LLMError) as e:
                last_err = e
                if attempt < self.settings.llm_max_retries:
                    time.sleep(1.5**attempt)
        raise last_err if last_err else LLMError("unknown error")

    def transcribe_audio(self, path: Path) -> str | None:
        """音频转写（SiliconFlow /audio/transcriptions）。失败降级返回 None，不影响入库。"""
        if not self.settings.siliconflow_api_key:
            return None
        url = f"{self.settings.siliconflow_base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.settings.siliconflow_api_key}"}
        try:
            with open(path, "rb") as f:
                data = self._post_multipart(
                    url,
                    {"model": self.settings.asr_model},
                    {"file": (path.name, f, "application/octet-stream")},
                    headers,
                )
        except Exception as e:
            logger.warning("transcribe_audio 失败（已降级）: %s", e)
            return None
        text = (data.get("text") or "").strip()
        return text or None
    # ---------- 文档摘要 ----------

    def summarize_text(self, text: str) -> SummaryResult | None:
        if not self.settings.deepseek_api_key:
            return None
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.2,
            "max_tokens": 800,
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
        message = (data.get("choices") or [{}])[0].get("message", {})
        content = message.get("content", "") or message.get("reasoning_content", "") or ""
        parsed = parse_json_text(content)
        if not parsed:
            return SummaryResult(summary=content.strip() or None)
        return SummaryResult(
            summary=(parsed.get("summary") or "").strip() or None,
            tags=[str(t).strip() for t in parsed.get("tags", []) if str(t).strip()],
        )


client = MultimodalClient()
