"""视频/音频管线测试：真实 ffmpeg 抽帧/转码 + LLM 全部 mock。"""
from __future__ import annotations

import math
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from app.llm.client import SummaryResult, VisionResult, client as llm_client
from app.models import Asset
from app.pipeline import processors
from app.pipeline.processors import ProcessingResult, process_audio, process_video


def make_mp4(path: Path, with_audio: bool = True) -> None:
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x48:d=2"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest", "-c:a", "aac", "-b:a", "32k"]
    cmd += ["-c:v", "mpeg4", "-q:v", "5", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    assert path.exists(), r.stderr


def make_wav(path: Path, seconds: float = 1.0) -> None:
    rate = 8000
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(int(rate * seconds))
        )
        w.writeframes(frames)


def make_asset(storage_path: str, modality: str) -> Asset:
    return Asset(
        id=1,
        name="test",
        original_filename=storage_path.rsplit("/", 1)[-1],
        modality=modality,
        mime_type="video/mp4" if modality == "video" else "audio/wav",
        size_bytes=1,
        storage_path=storage_path,
        sha256="test",
        status="pending",
    )


# ---------- 视频处理器 ----------

def test_video_processor_real_ffmpeg(tmp_path, monkeypatch):
    src = tmp_path / "uploads" / "video" / "demo.mp4"
    src.parent.mkdir(parents=True)
    make_mp4(src)

    monkeypatch.setattr(
        llm_client, "vision_describe",
        lambda b64, mime, model=None: VisionResult(description="蓝色测试画面", tags=["测试", "蓝色"], ocr=""),
    )
    monkeypatch.setattr(llm_client, "transcribe_audio", lambda path: "这是一段测试语音转写内容")

    asset = make_asset("uploads/video/demo.mp4", "video")
    result = process_video(asset, llm_client, tmp_path)

    assert result.thumbnail_path and result.thumbnail_path.endswith(".jpg")
    assert result.transcript == "这是一段测试语音转写内容"
    assert result.description == "蓝色测试画面"
    assert {"测试", "蓝色"} <= set(result.tags)
    assert result.duration and result.duration > 0
    # 临时工作目录应被清理
    assert not (tmp_path / "_work").exists()


def test_video_processor_no_llm(tmp_path, monkeypatch):
    """无 Key 场景：视觉/转写返回 None，不崩，保留封面与元数据。"""
    src = tmp_path / "uploads" / "video" / "demo.mp4"
    src.parent.mkdir(parents=True)
    make_mp4(src)

    monkeypatch.setattr(llm_client, "vision_describe", lambda b64, mime, model=None: None)
    monkeypatch.setattr(llm_client, "transcribe_audio", lambda path: None)

    asset = make_asset("uploads/video/demo.mp4", "video")
    result = process_video(asset, llm_client, tmp_path)

    assert result.thumbnail_path
    assert result.description and "未启用" in result.description


# ---------- 音频处理器 ----------

def test_audio_processor_real_wav(tmp_path, monkeypatch):
    src = tmp_path / "uploads" / "audio" / "demo.wav"
    src.parent.mkdir(parents=True)
    make_wav(src)

    monkeypatch.setattr(llm_client, "transcribe_audio", lambda path: "大家好，这是一段音频内容")
    monkeypatch.setattr(
        llm_client, "summarize_text",
        lambda text: SummaryResult(summary="测试音频摘要", tags=["音频", "测试"]),
    )

    asset = make_asset("uploads/audio/demo.wav", "audio")
    result = process_audio(asset, llm_client, tmp_path)

    assert result.transcript == "大家好，这是一段音频内容"
    assert result.description == "测试音频摘要"
    assert {"音频", "测试"} <= set(result.tags)
    assert result.thumbnail_path and result.thumbnail_path.endswith(".jpg")
    assert result.duration and result.duration > 0


# ---------- 转写客户端 ----------

def test_transcribe_client(monkeypatch, tmp_path):
    class FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return {"text": "转写结果"}

    monkeypatch.setattr(llm_client.settings, "siliconflow_api_key", "test-key")
    import app.llm.client as llm_module

    monkeypatch.setattr(llm_module.httpx, "post", lambda *a, **k: FakeResp())

    wav = tmp_path / "a.wav"
    make_wav(wav)
    assert llm_client.transcribe_audio(wav) == "转写结果"


# ---------- 上传接受性（视频/音频不再被拒） ----------

def test_upload_video_accepted(client, monkeypatch):
    fake = lambda asset, llm, data_root: ProcessingResult(  # noqa: E731
        description="测试视频", tags=["视频"], thumbnail_path="thumbnails/v.jpg", duration=1.0
    )
    monkeypatch.setitem(processors._PROCESSORS, "video", fake)
    r = client.post("/api/upload", files={"files": ("clip.mp4", b"fake", "video/mp4")})
    assert r.status_code == 200
    item = r.json()["items"][0]["asset"]
    assert item["modality"] == "video"
    assert item["status"] == "ready"
    assert item["description"] == "测试视频"


def test_upload_audio_accepted(client, monkeypatch):
    fake = lambda asset, llm, data_root: ProcessingResult(  # noqa: E731
        description="测试音频", tags=["音频"], thumbnail_path="thumbnails/a.jpg"
    )
    monkeypatch.setitem(processors._PROCESSORS, "audio", fake)
    r = client.post("/api/upload", files={"files": ("voice.mp3", b"fake", "audio/mpeg")})
    assert r.status_code == 200
    item = r.json()["items"][0]["asset"]
    assert item["modality"] == "audio"
    assert item["status"] == "ready"
