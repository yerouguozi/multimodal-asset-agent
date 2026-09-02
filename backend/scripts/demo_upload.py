r"""一键演示：生成四种模态测试素材 → 上传 → 等待真实模型处理 → 打印理解结果。

用法（需后端已启动）：
    .\.venv\Scripts\python scripts\demo_upload.py [base_url]
默认 http://127.0.0.1:8000
"""
from __future__ import annotations

import math
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import httpx
from PIL import Image, ImageDraw


def make_image(p: Path) -> None:
    img = Image.new("RGB", (640, 480), (25, 42, 86))
    d = ImageDraw.Draw(img)
    d.rectangle([80, 120, 560, 360], fill=(60, 90, 160))
    d.polygon([(120, 200), (320, 90), (520, 200)], fill=(180, 190, 220))
    for i in range(8):
        x = 80 + i * 62
        d.rectangle([x, 250, x + 45, 350], fill=(240, 230, 200))
    d.text((20, 20), "City Night", fill=(255, 255, 255))
    img.save(p, "PNG")


def make_video(p: Path) -> None:
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=660:duration=4",
            "-shortest", "-c:v", "mpeg4", "-q:v", "5",
            "-c:a", "aac", "-b:a", "32k", str(p),
        ],
        capture_output=True,
        timeout=90,
    )


def make_audio(p: Path) -> None:
    rate = 16000
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(5000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(rate * 3)
        )
        w.writeframes(frames)


def make_doc(p: Path) -> None:
    p.write_text(
        "本季度产品营销方案：目标用户是年轻群体，主打社交媒体推广。"
        "核心策略包括内容种草、KOL 合作与直播带货。",
        encoding="utf-8",
    )


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    tmp = Path(tempfile.mkdtemp(prefix="mma_demo_"))
    try:
        make_image(tmp / "城市夜景.png")
        make_video(tmp / "演示视频.mp4")
        make_audio(tmp / "音效.wav")
        make_doc(tmp / "营销方案.txt")

        files = [
            ("files", ("城市夜景.png", (tmp / "城市夜景.png").read_bytes(), "image/png")),
            ("files", ("演示视频.mp4", (tmp / "演示视频.mp4").read_bytes(), "video/mp4")),
            ("files", ("音效.wav", (tmp / "音效.wav").read_bytes(), "audio/wav")),
            ("files", ("营销方案.txt", (tmp / "营销方案.txt").read_bytes(), "text/plain")),
        ]
        print("== 上传 4 种模态素材 ==")
        r = httpx.post(f"{base}/api/upload", files=files, timeout=120)
        r.raise_for_status()
        items = r.json()["items"]
        ids = [it["asset"]["id"] for it in items]
        print("已提交:", ", ".join(f"#{i}" for i in ids))

        print("\n== 等待真实模型处理（视觉/转写/摘要）==")
        results = {}
        deadline = time.time() + 180
        while time.time() < deadline:
            done = True
            for aid in ids:
                if aid in results:
                    continue
                d = httpx.get(f"{base}/api/assets/{aid}", timeout=30).json()
                if d["status"] in ("ready", "failed"):
                    results[aid] = d
                else:
                    done = False
            if done:
                break
            time.sleep(2)

        print("\n== 理解结果 ==")
        for it in items:
            aid = it["asset"]["id"]
            d = results.get(aid, {})
            if not d:
                print(f"#{aid} 处理超时")
                continue
            print("-" * 56)
            print(f"#{aid} [{d['modality']}] {d['name']}  状态: {d['status']}")
            print(f"  描述: {d['description']}")
            tags = ", ".join(t["name"] for t in d.get("tags", []))
            print(f"  标签: {tags or '（无）'}")
            if d.get("transcript"):
                print(f"  转写: {d['transcript'][:150]}")
            if d.get("ocr_text"):
                print(f"  OCR: {d['ocr_text'][:100]}")
            if d.get("thumbnail_url"):
                print(f"  封面: {base}{d['thumbnail_url']}")
        return 0
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
