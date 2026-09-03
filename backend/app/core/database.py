"""数据库引擎与会话。测试时通过环境变量 DATABASE_URL=sqlite:// 使用内存库。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    if url == "sqlite://":
        # 内存库：所有连接共享同一实例（测试用）
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """建表（MVP 用 create_all + 轻量列迁移，后续需要再上 Alembic）。"""
    from app import models  # noqa: F401  确保模型注册到 Base.metadata

    Base.metadata.create_all(bind=engine)
    _migrate_columns()


def _migrate_columns() -> None:
    """SQLite 下 create_all 不会给已有表加列，这里做最小迁移。"""
    from sqlalchemy import inspect, text

    try:
        with engine.begin() as conn:
            for table in ("assets", "chat_sessions"):
                try:
                    cols = {c["name"] for c in inspect(engine).get_columns(table)}
                    if "owner" not in cols:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN owner VARCHAR(64) DEFAULT 'local'"))
                except Exception:
                    continue
            cols = {c["name"] for c in inspect(engine).get_columns("assets")}
            if "vision_model" not in cols:
                conn.execute(text("ALTER TABLE assets ADD COLUMN vision_model VARCHAR(120)"))
            if "transcript_segments" not in cols:
                conn.execute(text("ALTER TABLE assets ADD COLUMN transcript_segments TEXT"))
            if "deleted_at" not in cols:
                conn.execute(text("ALTER TABLE assets ADD COLUMN deleted_at DATETIME"))
            try:
                cols = {c["name"] for c in inspect(engine).get_columns("document_chunks")}
                if "modality" not in cols:
                    conn.execute(text("ALTER TABLE document_chunks ADD COLUMN modality VARCHAR(20) DEFAULT 'document'"))
                if "start" not in cols:
                    conn.execute(text("ALTER TABLE document_chunks ADD COLUMN start FLOAT"))
                if "end" not in cols:
                    conn.execute(text("ALTER TABLE document_chunks ADD COLUMN end FLOAT"))
            except Exception:
                pass
            try:
                cols = {c["name"] for c in inspect(engine).get_columns("usage_logs")}
                if "owner" not in cols:
                    conn.execute(text("ALTER TABLE usage_logs ADD COLUMN owner VARCHAR(64) DEFAULT 'local'"))
            except Exception:
                pass
    except Exception:
        # 表不存在或已迁移，忽略
        pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
