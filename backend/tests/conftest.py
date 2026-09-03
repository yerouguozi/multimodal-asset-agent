"""测试基座：内存数据库 + 同步入库模式 + 关闭外部 API。

必须在导入 app 之前设置环境变量。
"""
import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["INGESTION_MODE"] = "sync"
os.environ["SILICONFLOW_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["UPLOAD_DIR"] = "data/test_uploads"
os.environ["VECTOR_STORE_PATH"] = "data/test_vectors.npz"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.retrieval.vector_store import vector_store  # noqa: E402
from app.retrieval.chunk_vector import chunk_vector_store  # noqa: E402
from app import models  # noqa: E402,F401


@pytest.fixture(autouse=True)
def clean_state():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    vector_store.clear()
    chunk_vector_store.clear()
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
