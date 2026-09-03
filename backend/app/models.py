"""统一数据模型：Asset + Tag + IngestionJob + Embedding。

设计要点：
- Asset 是所有模态的统一入口，模态差异只体现在可空字段上；
- Tag 来源区分 llm/auto/user，方便日后人工修正；
- IngestionJob 记录每次处理尝试，支撑"任务队列/重试/进度"这类工程叙事。
"""
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .core.database import Base

# 合法取值（与检测逻辑保持一致）
MODALITIES = ("image", "video", "audio", "document")
STATUSES = ("pending", "processing", "ready", "failed", "duplicate")
TAG_SOURCES = ("llm", "auto", "user")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="local", index=True)
    name: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    modality: Mapped[str] = mapped_column(String(20), index=True)
    mime_type: Mapped[str] = mapped_column(String(120), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    # 相对 data_dir 的路径：uploads/... 与 thumbnails/...
    storage_path: Mapped[str] = mapped_column(String(500))
    thumbnail_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    sha256: Mapped[str] = mapped_column(String(64), index=True)
    phash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vision_model: Mapped[str | None] = mapped_column(String(120), nullable=True)  # 实际用的视觉模型（路由记录）

    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)

    # 理解结果（按模态填充）
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_segments: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: [{start,end,text}]
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)  # 文档正文（截断）

    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    tags: Mapped[list["Tag"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )

    @property
    def thumbnail_url(self) -> str | None:
        return f"/media/{self.thumbnail_path}" if self.thumbnail_path else None

    @property
    def media_url(self) -> str | None:
        return f"/media/{self.storage_path}" if self.storage_path else None


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(10), default="llm")

    asset: Mapped[Asset] = relationship(back_populates="tags")


class IngestionJob(Base):
    """一次处理尝试的记录（重试会追加新行），供进度查询。"""

    __tablename__ = "ingestion_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    stage: Mapped[str] = mapped_column(String(50), default="understand")
    status: Mapped[str] = mapped_column(String(20), default="running")  # running/done/failed
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ChatSession(Base):
    """对话会话（记忆落库，重启不丢）。"""

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="local", index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class User(Base):
    """极简用户（供外部评测/后续扩展接入）。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class UsageLog(Base):
    """模型调用记录（成本追踪）。cost_estimate 为按调用次数的估算值。"""

    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    model: Mapped[str] = mapped_column(String(120))
    operation: Mapped[str] = mapped_column(String(50))
    cost_estimate: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class Embedding(Base):
    """向量记录（本地向量库的落盘依据；保留表结构，后续可换 Milvus）。"""

    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), unique=True, index=True)
    model: Mapped[str] = mapped_column(String(120))
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)
