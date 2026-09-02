r"""实测 SiliconFlow / DeepSeek 接口连通性与模型 ID。

用法（在 backend/ 下）：
    .\.venv\Scripts\python scripts\check_llm_apis.py

前置：backend/.env 中已填写 SILICONFLOW_API_KEY（可选 DEEPSEEK_API_KEY）。
"""
from __future__ import annotations

import base64
import io
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.llm.client import client  # noqa: E402


def main() -> int:
    print("VISION_MODEL    =", settings.vision_model)
    print("EMBEDDING_MODEL =", settings.embedding_model)
    print("ASR_MODEL       =", settings.asr_model)
    print("LLM_MODEL       =", settings.llm_model)
    print()

    if not settings.siliconflow_api_key:
        print("[跳过] 未配置 SILICONFLOW_API_KEY，请先填写 backend/.env")
        return 1

    # 1) Embedding
    vecs = client.embed_texts(["测试句子"])
    if vecs:
        print("[embedding] OK dim =", len(vecs[0]))
    else:
        print("[embedding] FAILED")
        return 1

    # 2) 视觉理解
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 40, 90)).save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    vision = client.vision_describe(b64, "image/png")
    if vision and vision.description:
        print("[vision] OK desc =", vision.description[:40])
    else:
        print("[vision] FAILED")
        return 1

    # 3) 语音转写（1 秒静音 wav；静音可能返回空，属正常现象）
    tmp = Path(tempfile.mkdtemp()) / "silence.wav"
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    text = client.transcribe_audio(tmp)
    print("[asr] OK text =", repr(text) if text else "（空，静音属正常）")

    # 4) DeepSeek 摘要
    if settings.deepseek_api_key:
        s = client.summarize_text("深度学习与多模态检索技术")
        print("[summary] OK" if s and s.summary else "[summary] FAILED")
    else:
        print("[summary] 跳过（未配置 DEEPSEEK_API_KEY）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
