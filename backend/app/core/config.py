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

    # CORS
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # SiliconFlow（视觉理解 / Embedding）
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    vision_model: str = "Qwen/Qwen2.5-VL-32B-Instruct"
    embedding_model: str = "BAAI/bge-m3"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
