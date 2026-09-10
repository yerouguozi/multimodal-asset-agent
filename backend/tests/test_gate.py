"""查询意图门控测试：校准数学 / 判定 / 降级链 / 检索接线，全部离线（toy 嵌入）。"""
import pytest

from app.retrieval import gate
from app.retrieval.gate import GateDecision


@pytest.fixture(autouse=True)
def reset_gate_state():
    """门控是进程级缓存，测试间必须清掉，避免互相污染。"""
    gate.set_gate(None)
    gate._GATE_RETRY_AT = 0.0
    yield
    gate.set_gate(None)


def _seed_asset(name: str, modality: str = "image"):
    from app import models
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        db.add(
            models.Asset(
                name=name,
                original_filename=name,
                modality=modality,
                mime_type="image/png",
                size_bytes=1,
                storage_path=f"uploads/{modality}/{name}",
                sha256=name,
                status="ready",
            )
        )
        db.commit()


# ---------- 校准与判定（纯数学） ----------


def test_calibrate_separable_data():
    vis = [[1.0, 0.1], [0.95, 0.08], [1.05, 0.12], [0.9, 0.05]]
    sem = [[0.1, 1.0], [0.08, 0.95], [0.12, 1.05], [0.05, 0.9]]
    g = gate.calibrate(vis, sem)
    assert g.decide_vec([1.0, 0.1]).is_visual
    assert not g.decide_vec([0.1, 1.0]).is_visual
    # 阈值应落在两类 margin 之间
    dm = g.decide_vec([1.0, 0.1]).margin
    sm = g.decide_vec([0.1, 1.0]).margin
    assert sm < g.threshold <= dm


def test_build_gate_with_toy_embed_and_loo_threshold():
    vis_set, sem_set = set(gate.VISUAL_SEEDS), set(gate.SEMANTIC_SEEDS)

    def embed_fn(texts):
        return [[1.0, 0.0] if t in vis_set else [0.0, 1.0] for t in texts]

    g = gate.build_gate(embed_fn)
    assert g is not None
    d_vis = g.decide_vec([1.0, 0.0])
    d_sem = g.decide_vec([0.0, 1.0])
    assert d_vis.is_visual and not d_sem.is_visual
    assert d_vis.method == "vector"
    # 完全可分时留一法校准的阈值应严格在两类之间
    assert d_sem.margin < g.threshold <= d_vis.margin


def test_gate_decision_carries_diagnostics():
    g = gate.build_gate(lambda ts: [[1.0, 0.0] if t in set(gate.VISUAL_SEEDS) else [0.0, 1.0] for t in ts])
    d = g.decide_vec([0.6, 0.8])
    assert d.sim_visual is not None and d.sim_semantic is not None
    assert d.margin == pytest.approx(d.sim_visual - d.sim_semantic)


# ---------- 降级链：向量不可用 → v1 关键词规则 ----------


def test_decide_falls_back_to_keyword_without_vector():
    # query_vec=None 直接走关键词，不触发任何嵌入调用
    d = gate.decide("深蓝色夜空下的城市剪影", None)
    assert d.method == "keyword" and d.is_visual
    d2 = gate.decide("数据库索引的论文", None)
    assert d2.method == "keyword" and not d2.is_visual


def test_decide_falls_back_when_embedding_unavailable(monkeypatch):
    # 无 API Key 时 llm_client.embed_texts 返回 None → 门控构建失败 → 关键词兜底
    monkeypatch.setattr(gate.llm_client, "embed_texts", lambda texts: None)
    d = gate.decide("深蓝色夜空", [[1.0, 0.0]])
    assert d.method == "keyword" and d.is_visual


def test_keyword_rule_known_blind_spots():
    # v1 的已知盲区（v2 要解决的正是这些）：新词与英文
    assert not gate.keyword_is_visual("霓虹灯牌在雨夜的街头闪烁")
    assert not gate.keyword_is_visual("a snowy mountain peak at sunrise")
    # 词表内的说法仍然有效
    assert gate.keyword_is_visual("深蓝色夜空下的高楼剪影")


# ---------- 检索接线 ----------


def test_gate_strategy_uses_vector_decision(monkeypatch):
    _seed_asset("城市夜景.png")
    from app.core.database import SessionLocal
    from app.retrieval import search as search_service

    seen = {}

    def fake_decide(query, vec):
        seen["call"] = (query, vec)
        return GateDecision(is_visual=False, method="vector", margin=0.2)

    monkeypatch.setattr(search_service, "gate_decide", fake_decide)
    with SessionLocal() as db:
        hits = search_service.search(db, "夜景", strategy="gate")
    assert seen["call"][0] == "夜景"  # 查询文本传入门控
    assert hits  # 门控说非视觉，文本检索照常返回


def test_gate_kw_strategy_skips_vector_gate(monkeypatch):
    _seed_asset("城市夜景.png")
    from app.core.database import SessionLocal
    from app.retrieval import search as search_service

    def boom(*args, **kwargs):
        raise AssertionError("gate_kw 是 v1 关键词规则，不应调用向量门控")

    monkeypatch.setattr(search_service, "gate_decide", boom)
    with SessionLocal() as db:
        hits = search_service.search(db, "夜景", strategy="gate_kw")
    assert hits and hits[0][0].name == "城市夜景.png"
