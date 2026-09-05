"""全局配置：从 .env / 环境变量读取，全部可覆盖。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录（app/core/config.py 向上三级）
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Multimodal Asset Agent"

    # 数据库
    database_url: str = "sqlite:///./data/assets.db"

    # 存储与入库
    upload_dir: str = "./data/uploads"
    vector_store_path: str = "./data/vectors.npz"
    ingestion_mode: str = "async"  # async | sync
    worker_count: int = 2
    max_retries: int = 3
    max_upload_mb: int = 100  # 单文件大小上限（上传时流式校验，超限 413）

    # CORS
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # SiliconFlow（视觉理解 / Embedding）
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    vision_model: str = "Qwen/Qwen2.5-VL-32B-Instruct"
    embedding_model: str = "BAAI/bge-m3"

    # 多模态处理参数（阶段 2：视频/音频）
    asr_model: str = "FunAudioLLM/SenseVoiceSmall"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

    # 模型路由：简单图片走轻量模型，复杂走大模型（成本优化）
    vision_model_cheap: str = "Qwen/Qwen3-VL-8B-Instruct"
    vision_model_pro: str = "Qwen/Qwen3-VL-32B-Instruct"
    simple_image_max_side: int = 640

    # 多模态 embedding（图片直接嵌入，与文本嵌入同一向量空间做融合）
    vl_embedding_model: str = "Qwen/Qwen3-VL-Embedding-8B"
    vl_embed_enabled: bool = True

    # 文生图
    image_gen_model: str = "Qwen/Qwen-Image"
    image_gen_size: str = "1024x1024"

    # 音视频时间戳分片转写：上限必须覆盖 audio_max_seconds 的提取窗口
    # （600 秒 / 30 秒 = 20 段），否则长音频后半段永远搜不到
    asr_chunk_seconds: int = 30
    max_asr_chunks: int = 20

    # 向量后端：local（默认，零依赖）| milvus（可选）
    vector_backend: str = "local"
    milvus_uri: str = "http://localhost:19530"

    # 每用户模型调用配额（按 UsageLog 实际记录 + 预检估算）
    usage_daily_limit: int = 200
    usage_monthly_limit: int = 2000
    usage_hourly_limit: int = 100

    # JWT（质控平台等外部评测接入）
    jwt_secret: str = "dev-secret-change-me-please-override-32bytes-min"
    jwt_expire_minutes: int = 1440
    video_max_frames: int = 4
    audio_max_seconds: int = 600

    # DeepSeek（文本摘要 / 标签）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_timeout: float = 60.0
    llm_max_retries: int = 3

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def data_dir(self) -> Path:
        """素材/缩略图/向量的共同根目录（相对路径基于 backend/）。"""
        p = Path(self.upload_dir)
        if not p.is_absolute():
            p = BASE_DIR / p
        return p.parent

    @property
    def upload_path(self) -> Path:
        p = self.data_dir / Path(self.upload_dir).name
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def thumbnail_path(self) -> Path:
        p = self.data_dir / "thumbnails"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def vector_store_file(self) -> Path:
        p = Path(self.vector_store_path)
        if not p.is_absolute():
            p = BASE_DIR / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def chunk_vector_file(self) -> Path:
        """片段向量库独立于素材向量库（同一 data 目录，文件名错开）。"""
        f = self.vector_store_file
        return f.with_name(f"{f.stem}_chunks.npz")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
