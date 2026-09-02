"""素材处理引擎：图片压缩/缩放/转格式，音视频转码。

设计原则：处理产物作为"新素材"入库（保留原素材）；内容语义不变，
因此新素材直接复用原素材的理解结果与向量，避免重复调用模型（省成本）。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image

SUPPORTED_OPERATIONS: dict[str, list[str]] = {
    "image": ["resize", "compress", "convert"],
    "audio": ["compress", "convert"],
    "video": ["compress", "convert"],
}

_IMAGE_FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def transform_file(
    src: Path,
    modality: str,
    operation: str,
    params: dict,
    out_dir: Path,
    stem: str,
) -> Path:
    """执行一次处理，返回产物路径。不支持的操作抛 ValueError（由工具层转成友好错误）。"""
    if operation not in SUPPORTED_OPERATIONS.get(modality, []):
        raise ValueError(f"{modality} 不支持操作 {operation}，可选: {SUPPORTED_OPERATIONS.get(modality, [])}")
    out_dir.mkdir(parents=True, exist_ok=True)
    if modality == "image":
        return _transform_image(src, operation, params, out_dir, stem)
    return _transform_media(src, modality, operation, params, out_dir, stem)


def _transform_image(src: Path, operation: str, params: dict, out_dir: Path, stem: str) -> Path:
    with Image.open(src) as img:
        img.load()
        if operation == "resize":
            max_side = int(params.get("max_side", 800))
            img.thumbnail((max_side, max_side))
        ext = str(params.get("format", "jpg")).lower() if operation == "convert" else "jpg"
        if ext not in _IMAGE_FORMATS:
            ext = "jpg"
        out = out_dir / f"{stem}.{ext}"
        img.convert("RGB").save(out, _IMAGE_FORMATS[ext], quality=int(params.get("quality", 80)))
        return out


def _transform_media(src: Path, modality: str, operation: str, params: dict, out_dir: Path, stem: str) -> Path:
    ffmpeg = _ffmpeg()
    if modality == "video":
        if operation == "compress":
            out = out_dir / f"{stem}.mp4"
            cmd = [ffmpeg, "-y", "-i", str(src), "-c:v", "libx264", "-crf", str(int(params.get("crf", 28))),
                   "-preset", "fast", str(out)]
        else:
            ext = str(params.get("format", "mp4")).lower()
            out = out_dir / f"{stem}.{ext}"
            cmd = [ffmpeg, "-y", "-i", str(src), str(out)]
    else:
        if operation == "compress":
            out = out_dir / f"{stem}.mp3"
            cmd = [ffmpeg, "-y", "-i", str(src), "-b:a", "96k", str(out)]
        else:
            ext = str(params.get("format", "mp3")).lower()
            out = out_dir / f"{stem}.{ext}"
            cmd = [ffmpeg, "-y", "-i", str(src), str(out)]
    r = _run(cmd)
    if not out.exists() or r.returncode != 0:
        raise ValueError(f"转码失败: {(r.stderr or '')[:200]}")
    return out


def image_size(src: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(src) as img:
            return img.size
    except Exception:
        return None, None
