"""Pydantic 接口模型（from_attributes 直接从 ORM 对象序列化）。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source: str


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    original_filename: str
    modality: str
    mime_type: str
    size_bytes: int
    status: str
    description: str | None = None
    ocr_text: str | None = None
    transcript: str | None = None
    text_content: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    thumbnail_url: str | None = None
    error_message: str | None = None
    created_at: datetime
    tags: list[TagOut] = []


class AssetListOut(BaseModel):
    items: list[AssetOut]
    total: int
    page: int
    page_size: int


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_id: int
    stage: str
    status: str
    attempts: int
    error: str | None = None
    updated_at: datetime


class UploadItem(BaseModel):
    asset: AssetOut | None = None
    duplicate_of: int | None = None
    error: str | None = None


class UploadResult(BaseModel):
    items: list[UploadItem]


class SearchHit(BaseModel):
    asset: AssetOut
    score: float


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]


class AssetPatch(BaseModel):
    """目前支持人工增补标签。"""

    add_tags: list[str] = []


class AssetStatsOut(BaseModel):
    total: int
    by_modality: dict[str, int]
    by_status: dict[str, int]
    top_tags: list[dict[str, object]]
