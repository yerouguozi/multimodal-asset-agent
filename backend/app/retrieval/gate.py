"""查询意图门控：判断查询是"视觉描述"还是"任务意图"，决定是否启用图片级 VL 向量。

演进（评测驱动）：
- v1 关键词规则：命中颜色/光影词表即视为视觉查询。零成本、可解释，
  但词表硬编码——新词（"霓虹雨夜街头"）和跨语言（英文查询）直接失效；
- v2 向量质心门控（当前默认）：视觉描述、任务意图各取一组种子短语，
  用 bge-m3 嵌入成两个质心，查询向量离哪个质心近就判为哪类；
  阈值用种子留一法（LOO）自动校准，不手工拍定。
  bge-m3 多语言同空间，英文/新词天然可分；种子是"意图描述"而非
  "关键词枚举"，换说法不影响判定。
- 成本：查询向量复用文本向量召回已算好的结果，门控零额外调用；
  种子嵌入每进程只算一次（失败 5 分钟后允许重试）。
- 降级链：向量不可用（无 Key/超时/语料为空）→ 自动回退 v1 关键词规则。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

from ..llm.client import client as llm_client

logger = logging.getLogger(__name__)

# 种子=意图的"描述性示例"（与评测查询集刻意不相交，避免用测试集校准）。
# 维护方式：线上门控误判日志里挖新说法，补进对应组即可，无需改代码逻辑。
VISUAL_SEEDS: tuple[str, ...] = (
    # 中文视觉描述（颜色/光影/构图/质感）
    "蔚蓝的海水拍打礁石",
    "金色的麦田在阳光下起伏",
    "紫色的晚霞染红天边",
    "昏暗房间里的一束暖光",
    "翠绿森林中的晨雾",
    "黑白相间的斑马条纹",
    "红色的气球飘在空中",
    "雨后路面反射的霓虹光斑",
    "夕阳下拉长的影子",
    "清澈溪水里的鹅卵石",
    "五彩缤纷的热气球",
    "银白色的月光洒在雪地",
    "燃烧的篝火特写",
    "波光粼粼的湖面",
    "卡通风格的粉色独角兽",
    "混凝土墙面的粗糙纹理",
    # 英文视觉描述（多语言同空间，跨语言门控）
    "a red sports car on a mountain road",
    "golden autumn leaves in the park",
    "blue sky with white clouds over the sea",
    "neon lights in a rainy street at night",
)

SEMANTIC_SEEDS: tuple[str, ...] = (
    # 中文任务/主题意图（找的是"内容"，不是"画面"）
    "适合睡前听的放松内容",
    "介绍数据库优化的资料",
    "团队周会的工作汇报",
    "学做西餐的入门教程",
    "找工作需要注意什么",
    "健身减脂的训练安排",
    "关于机器学习的论文",
    "云南自由行的行程规划",
    "适合做手机广告的视频",
    "讲人工智能的播客节目",
    "小孩子学英语的音频",
    "产品发布会的演讲视频",
    "帮助入眠的白噪音",
    "适合跑步时听的音乐",
    "营销活动的推广方案",
    "游戏主播的实况录像",
    # 英文任务/主题意图
    "recommend some music for studying",
    "how to plan a trip to japan",
    "latest research on deep learning",
    "weekly team meeting recording",
)

# 种子嵌入失败后的重试间隔（秒）：避免 API 故障时每个请求都白打一次种子嵌入
_RETRY_INTERVAL_SECONDS = 300.0


@dataclass
class GateDecision:
    is_visual: bool
    method: str  # "vector" | "keyword"
    margin: float | None = None  # sim_visual - sim_semantic（keyword 判定时为 None）
    sim_visual: float | None = None
    sim_semantic: float | None = None
    threshold: float | None = None


@dataclass
class VectorGate:
    """质心 + 阈值；判定纯数学，无任何网络调用。"""

    visual_centroid: np.ndarray
    semantic_centroid: np.ndarray
    threshold: float  # margin >= threshold 判为视觉

    def decide_vec(self, query_vec: list[float] | np.ndarray) -> GateDecision:
        q = np.asarray(query_vec, dtype=np.float32)
        sim_v = _cos(q, self.visual_centroid)
        sim_s = _cos(q, self.semantic_centroid)
        margin = float(sim_v - sim_s)
        return GateDecision(
            is_visual=margin >= self.threshold,
            method="vector",
            margin=margin,
            sim_visual=float(sim_v),
            sim_semantic=float(sim_s),
            threshold=self.threshold,
        )


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9))


def _centroid(vecs: list[np.ndarray]) -> np.ndarray:
    m = np.stack(vecs).mean(axis=0)
    return m / (np.linalg.norm(m) + 1e-9)


def calibrate(visual_vecs: list[np.ndarray], semantic_vecs: list[np.ndarray]) -> VectorGate:
    """种子留一法（LOO）校准阈值：对每个种子，用它"不在场"的质心算 margin，
    在 LOO margin 上取平衡准确率最高的阈值（并列时取并列区间中点，最稳健）。
    校准只用种子，不碰任何评测查询。"""
    vis_margins = [
        _cos(v, _centroid([x for j, x in enumerate(visual_vecs) if j != i]))
        - _cos(v, _centroid(semantic_vecs))
        for i, v in enumerate(visual_vecs)
    ]
    sem_margins = [
        _cos(v, _centroid(visual_vecs))
        - _cos(v, _centroid([x for j, x in enumerate(semantic_vecs) if j != i]))
        for i, v in enumerate(semantic_vecs)
    ]
    margins = sorted(vis_margins + sem_margins)
    # 候选阈值：相邻 margin 的中点（margin 本身作为阈值会把该种子判错/判对的边界重合）
    candidates = [margins[0] - 0.01] + [
        (a + b) / 2 for a, b in zip(margins, margins[1:])
    ] + [margins[-1] + 0.01]
    n_vis, n_sem = len(vis_margins), len(sem_margins)

    def balanced_acc(t: float) -> float:
        tpr = sum(1 for m in vis_margins if m >= t) / n_vis
        tnr = sum(1 for m in sem_margins if m < t) / n_sem
        return (tpr + tnr) / 2

    best = max(balanced_acc(t) for t in candidates)
    band = [t for t in candidates if balanced_acc(t) == best]
    threshold = (band[0] + band[-1]) / 2
    return VectorGate(
        visual_centroid=_centroid(visual_vecs),
        semantic_centroid=_centroid(semantic_vecs),
        threshold=threshold,
    )


def build_gate(embed_fn) -> VectorGate | None:
    """嵌入全部种子并校准；嵌入不可用返回 None（调用方走关键词兜底）。"""
    seeds = list(VISUAL_SEEDS) + list(SEMANTIC_SEEDS)
    try:
        vecs = embed_fn(seeds)
    except Exception as e:
        logger.warning("门控种子嵌入失败（回退关键词规则）: %s", e)
        return None
    if not vecs or len(vecs) != len(seeds):
        return None
    arr = [np.asarray(v, dtype=np.float32) for v in vecs]
    return calibrate(arr[: len(VISUAL_SEEDS)], arr[len(VISUAL_SEEDS):])


# ---------- 进程级缓存 ----------

_GATE: VectorGate | None = None
_GATE_RETRY_AT = 0.0


def set_gate(g: VectorGate | None) -> None:
    """注入已构建的门控（评测脚本/测试用，跳过种子嵌入）。"""
    global _GATE
    _GATE = g


def get_gate() -> VectorGate | None:
    global _GATE, _GATE_RETRY_AT
    if _GATE is not None:
        return _GATE
    if time.monotonic() < _GATE_RETRY_AT:
        return None
    g = build_gate(llm_client.embed_texts)
    if g is None:
        _GATE_RETRY_AT = time.monotonic() + _RETRY_INTERVAL_SECONDS
        return None
    _GATE = g
    logger.info("向量门控已构建（种子 %d+%d，阈值 %.4f）", len(VISUAL_SEEDS), len(SEMANTIC_SEEDS), g.threshold)
    return g


# ---------- v1 关键词规则（降级为兜底，gate_kw 策略供消融评测） ----------

_VISUAL_KEYWORDS = (
    "色", "蓝", "红", "绿", "黄", "紫", "橙", "夜空", "天空", "雪", "灯光", "玻璃",
    "镜面", "方块", "剪影", "夜景", "晚霞", "像素", "阳光", "海面", "山", "楼", "光",
    "画面", "图", "条纹", "彩色",
)


def keyword_is_visual(query: str) -> bool:
    """v1：命中视觉关键词表即判为视觉查询。新词/英文覆盖不到。"""
    return any(k in query for k in _VISUAL_KEYWORDS)


def decide(query: str, query_vec: list[float] | None) -> GateDecision:
    """对外入口：向量门控优先，向量不可用自动回退关键词规则。"""
    g = get_gate() if query_vec is not None else None
    if g is None:
        return GateDecision(is_visual=keyword_is_visual(query), method="keyword")
    return g.decide_vec(query_vec)
