# Multimodal Asset Agent（多模态素材 Agent）

> 不预设领域的多模态素材管理 Agent——上传什么素材，它就自动"长成"什么方向的素材中心。

图片 / 视频 / 音频 / 文档统一入库，自动理解、打标、索引；自然语言跨模态检索；Agent 帮你搜素材、生成素材、处理素材。

## 核心能力

- 多模态入库自动化（去重、预览、描述、标签、OCR、转录、统一向量化）
- 跨模态语义检索（文字搜图/搜视频/搜音频/搜文档，混合检索 + 重排）
- 领域自适应（分类体系与领域画像从数据自动浮现，无需配置）
- 素材助理 Agent（LangGraph 工具调用：搜索 / 生成 / 处理 / 画像）

## 文档导航

- [00-项目概述](docs/00-项目概述.md)
- [01-功能设计](docs/01-功能设计.md)
- [02-架构设计](docs/02-架构设计.md)
- [03-开发规范](docs/03-开发规范.md)
- [04-开发计划](docs/04-开发计划.md)
- [检索评测报告](docs/eval-reports/检索评测报告.md)

## 技术栈

FastAPI · SQLAlchemy · SQLite · LangGraph · SiliconFlow（多模态）· DeepSeek · React + Vite + TS · pytest · Docker

## 开发进度

见 [docs/04-开发计划.md](docs/04-开发计划.md)，当前阶段：4（检索评测：Recall@1 0.705→0.833）已完成。

## 快速开始

### 1. 后端

`powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # 可选：填入 SILICONFLOW_API_KEY / DEEPSEEK_API_KEY
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
`

打开 <http://127.0.0.1:8000> 使用内置演示页；接口文档 <http://127.0.0.1:8000/docs>。

> 不填 API Key 也能跑：图片/文档自动入库、缩略图、去重、关键词检索照常工作；
> 填入 Key 后自动启用视觉理解打标、文档摘要和语义检索。
