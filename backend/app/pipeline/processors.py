"""模态适配器：把"理解素材"这件事按模态拆成可插拔的处理器。

新增模态 = 新增一个 process_xxx 函数并注册，核心引擎不变
（沿用 agent-qc-platform 的驱动适配器模式）。
"""
from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

import imagehash

from ..core.config import settings
from ..llm.client import MultimodalClient
from ..models import Asset

logger = logging.getLogger(__name__)

MAX_VISION_SIDE = 1280  # 发给视觉模型前的最大边长（控制 token/费用）
MAX_THUMB_SIDE = 320
TEXT_LIMIT = 5000  # 入库保存的正文上限（字符）


@dataclass
class ProcessingResult:
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    ocr_text: str | None = None
    transcript: str | None = None
    text_content: str | None = None
    thumbnail_path: str | None = None
    phash: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None


# ---------- 图片 ----------

def process_image(asset: Asset, llm: MultimodalClient, data_root: Path) -> ProcessingResult:
    path = data_root / asset.storage_path
    result = ProcessingResult()

    with Image.open(path) as img:
        img.load()
        result.width, result.height = img.size
        result.phash = str(imagehash.phash(img, hash_size=16))

        # 缩略图
        thumb = img.copy()
        thumb.thumbnail((MAX_THUMB_SIDE, MAX_THUMB_SIDE))
        thumb_dir = data_root / "thumbnails"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        thumb_path = thumb_dir / f"{asset.id}.jpg"
        thumb.convert("RGB").save(thumb_path, "JPEG", quality=80)
        result.thumbnail_path = f"thumbnails/{thumb_path.name}"

        # 视觉理解（先压缩到上限边长）
        probe = img.copy()
        probe.thumbnail((MAX_VISION_SIDE, MAX_VISION_SIDE))
        buf = io.BytesIO()
        probe.convert("RGB").save(buf, "JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    vision = llm.vision_describe(b64, "image/jpeg")
    if vision:
        result.description = vision.description
        result.tags = vision.tags
        result.ocr_text = vision.ocr
    return result


# ---------- 文档 ----------

def process_document(asset: Asset, llm: MultimodalClient, data_root: Path) -> ProcessingResult:
    path = data_root / asset.storage_path
    result = ProcessingResult()
    text = _extract_text(path, asset.mime_type)

    if text:
        result.text_content = text[:TEXT_LIMIT]
        summary = llm.summarize_text(text[:3000])
        if summary:
            result.description = summary.summary
            result.tags = summary.tags
        else:
            result.description = None  # 无 Key 时不编造
    else:
        result.description = "（未提取到文本，可能是扫描件；OCR 支持将在后续阶段补充）"
    return result


def _extract_text(path: Path, mime: str) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            return _extract_pdf(path)
        if suffix in (".docx", ".doc"):
            return _extract_docx(path)
        if suffix in (".xlsx", ".xlsm", ".xls"):
            return _extract_xlsx(path)
        if suffix in (".txt", ".md", ".json", ".csv", ".log"):
            data = path.read_bytes()
            return data[:200_000].decode("utf-8", errors="ignore")
    except Exception as e:
        logger.warning("文档文本抽取失败 %s: %s", path.name, e)
        return ""
    return ""


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages[:50]:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def _extract_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()


def _extract_xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    lines = []
    for ws in wb.worksheets[:3]:
        for row in ws.iter_rows(max_row=50, values_only=True):
            vals = [str(v) for v in row if v is not None]
            if vals:
                lines.append(" | ".join(vals))
    return "\n".join(lines).strip()


# ---------- 视频 / 音频（阶段 2） ----------

def process_video(asset: Asset, llm: MultimodalClient, data_root: Path) -> ProcessingResult:
    raise NotImplementedError("视频处理将在阶段 2 上线")


def process_audio(asset: Asset, llm: MultimodalClient, data_root: Path) -> ProcessingResult:
    raise NotImplementedError("音频处理将在阶段 2 上线")


_PROCESSORS = {
    "image": process_image,
    "document": process_document,
    "video": process_video,
    "audio": process_audio,
}


def resolve_processor(modality: str):
    return _PROCESSORS[modality]


def build_embed_text(result: ProcessingResult) -> str:
    parts = [result.description, result.ocr_text, result.transcript, result.text_content]
    return " ".join(p for p in parts if p)[:1500]
