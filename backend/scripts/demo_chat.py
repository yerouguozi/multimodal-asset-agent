"""素材助理对话演示：依次问几个典型问题并打印回答。

用法（后端运行中，默认 8000 端口）：
    .\.venv\Scripts\python scripts\demo_chat.py [base_url]
"""
from __future__ import annotations

import sys

import httpx


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    questions = [
        "帮我搜复古游戏",
        "我的素材库是什么领域",
        "看看 #1",
        "帮我生成一张星空下的城市插画",
    ]
    for q in questions:
        print(f"\n>>> {q}")
        with httpx.stream(
            "POST",
            f"{base}/api/chat",
            json={"message": q, "session_id": "demo"},
            timeout=180,
        ) as resp:
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    print("   ", line[6:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
