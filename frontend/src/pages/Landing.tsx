import { useEffect, useState } from "react";
import type { ComponentType } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  Database,
  FileText,
  Film,
  FolderGit,
  Gauge,
  Image as ImageIcon,
  Layers,
  Mic,
  Radar,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { DomainProfile, UsageSummary } from "../types";

interface LiveStats {
  ok: boolean;
  assets?: number;
  calls?: number;
  cost?: number;
}

const FEATURES: {
  icon: ComponentType<{ size?: number | string; className?: string }>;
  title: string;
  desc: string;
}[] = [
  {
    icon: Layers,
    title: "统一入库流水线",
    desc: "图片 / 视频 / 音频 / 文档一条管线：SHA-256 + pHash 去重、缩略图与封面、OCR / 转写 / 摘要 / 自动打标，失败自动重试。",
  },
  {
    icon: Search,
    title: "跨模态语义检索",
    desc: "自实现 BM25 与 bge-m3 向量做 RRF 融合，再由 bge-reranker 精排。用自然语言描述，就能跨图片、视频、音频找素材。",
  },
  {
    icon: ImageIcon,
    title: "以图搜图",
    desc: "图片走 VL 图片向量。给一张参考图，找出视觉上相似的素材；纯视觉查询按查询类型自动启用门控。",
  },
  {
    icon: Bot,
    title: "素材助理 Agent",
    desc: "LangGraph 任务规划 → 多步工具循环 → 组织回答，SSE 逐步推送。支持搜素材、生成素材、转码处理与素材库总结。",
  },
  {
    icon: Radar,
    title: "领域自适应画像",
    desc: "分类体系不写死：从标签聚合与 LLM 洞察自动生成“我的素材库是什么领域”，并反哺检索字段权重。",
  },
  {
    icon: ShieldCheck,
    title: "成本与质控闭环",
    desc: "每次模型调用落账、简单任务走轻量模型路由；自带检索评测集，并兼容质控平台的评测会话协议。",
  },
];

const PIPELINE: { title: string; desc: string }[] = [
  { title: "上传入库", desc: "去重、缩略图、元数据" },
  { title: "模态解析", desc: "OCR / 转写 / 文档摘要" },
  { title: "统一向量化", desc: "bge-m3 + VL 图片向量" },
  { title: "混合检索", desc: "BM25 + 向量 RRF 融合" },
  { title: "语义精排", desc: "bge-reranker 兜底重排" },
  { title: "Agent 作答", desc: "多步规划 + SSE 推送" },
];

const STACK = [
  "FastAPI",
  "SQLAlchemy",
  "LangGraph",
  "Qwen3-VL",
  "SenseVoice",
  "bge-m3 / reranker",
  "React 18",
  "TypeScript",
  "Milvus（可切换）",
];

export default function Landing() {
  const [live, setLive] = useState<LiveStats>({ ok: false });

  useEffect(() => {
    let alive = true;
    const run = async () => {
      try {
        const h = await fetch("/api/health");
        const profP = fetch("/api/domain/profile").then((r) =>
          r.ok ? (r.json() as Promise<DomainProfile>) : null
        );
        const useP = fetch("/api/usage/summary").then((r) =>
          r.ok ? (r.json() as Promise<UsageSummary>) : null
        );
        const [prof, usage] = await Promise.all([profP, useP]);
        if (!alive) return;
        setLive({
          ok: h.ok,
          assets: prof?.total,
          calls: usage?.total_calls,
          cost: usage?.total_cost,
        });
      } catch {
        if (alive) setLive({ ok: false });
      }
    };
    void run();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="landing" id="top">
      <header className="land-nav">
        <div className="nav-inner">
          <a className="brand" href="#top">
            <span className="brand-mark">M</span>
            <span className="brand-text">
              Multimodal <i>Asset Agent</i>
            </span>
          </a>
          <nav className="nav-links">
            <a href="#capabilities">能力</a>
            <a href="#pipeline">流水线</a>
            <a href="#eval">评测</a>
            <a href="#stack">技术栈</a>
          </nav>
          <Link className="btn primary nav-cta" to="/app">
            快速使用
            <ArrowRight size={15} />
          </Link>
        </div>
      </header>

      <section className="hero">
        <div className="hero-inner">
          <div className="hero-badge">
            <span className="pulse-dot" />
            自研全栈 · 多模态检索 + Agent
          </div>
          <h1 className="hero-title">
            上传什么素材，
            <br />
            就长成什么
            <span className="text-grad"> 素材中枢</span>
          </h1>
          <p className="hero-sub">
            图片、视频、音频、文档统一入库：自动理解、打标、转写、向量化。
            再用自然语言、参考图或 Agent 对话，管理真正属于你的素材库。
          </p>
          <div className="cta-row">
            <Link className="btn primary btn-cta" to="/app">
              快速使用
              <ArrowRight size={17} />
            </Link>
            <a className="btn soft btn-cta" href="#eval">
              查看检索评测
            </a>
          </div>

          <div className="live-strip">
            <span className={`live-item ${live.ok ? "ok" : ""}`}>
              <span className="live-dot" />
              {live.ok ? "服务运行中" : "后端离线 · UI 预览模式"}
            </span>
            <span className="live-divider" />
            <span className="live-item">
              素材 <b>{live.assets ?? "—"}</b> 件
            </span>
            <span className="live-item">
              模型调用 <b>{live.calls ?? "—"}</b> 次
            </span>
            <span className="live-item">
              估算成本 <b>{live.cost != null ? `$${live.cost.toFixed(4)}` : "—"}</b>
            </span>
          </div>
        </div>

        <div className="hero-stage">
          <div className="mock-window">
            <div className="mock-bar">
              <span className="dot d-red" />
              <span className="dot d-amber" />
              <span className="dot d-green" />
              <span className="mock-url">
                <Sparkles size={12} />
                workspace · multimodal asset agent
              </span>
            </div>
            <div className="mock-body">
              <div className="mock-search">
                <Search size={14} />
                <span>夜景 · 复古游戏 · 营销方案…</span>
                <span className="mock-kbd">↵</span>
              </div>
              <div className="mock-cols">
                <div className="mock-grid">
                  <div className="mock-tile tile-1">
                    <ImageIcon size={18} />
                    <i>night_city.png</i>
                  </div>
                  <div className="mock-tile tile-2">
                    <Film size={18} />
                    <i>demo_reel.mp4</i>
                  </div>
                  <div className="mock-tile tile-3">
                    <ImageIcon size={18} />
                    <i>retro_ui.png</i>
                  </div>
                  <div className="mock-tile tile-4">
                    <Mic size={18} />
                    <i>podcast_09.mp3</i>
                  </div>
                  <div className="mock-tile tile-5">
                    <ImageIcon size={18} />
                    <i>brand_kit.png</i>
                  </div>
                  <div className="mock-tile tile-6">
                    <FileText size={18} />
                    <i>campaign.pdf</i>
                  </div>
                </div>
                <aside className="mock-chat">
                  <div className="mock-chat-head">
                    <Bot size={15} />
                    素材助理
                  </div>
                  <div className="mock-msg user">帮我找“夜色城市”素材，做成一期合集</div>
                  <div className="mock-msg step">→ 规划：检索素材 → 生成封面 → 汇总</div>
                  <div className="mock-msg agent">
                    找到 6 个相关素材：图像 ×4、视频 ×2。已按相关度排序，其中 2 个来自音频转写片段。
                  </div>
                </aside>
              </div>
            </div>
          </div>

          <div className="float-chip fc-1">
            <span className="chip-icon">
              <ImageIcon size={14} />
            </span>
            以图搜图 · VL 向量命中
          </div>
          <div className="float-chip fc-2">
            <span className="chip-icon">
              <Radar size={14} />
            </span>
            领域画像已更新
          </div>
          <div className="float-chip fc-3">
            <span className="chip-icon">
              <CheckCircle2 size={14} />
            </span>
            入库完成 · 自动打标 12 个
          </div>
        </div>
      </section>

      <section className="section" id="capabilities">
        <div className="section-head">
          <span className="eyebrow">CORE CAPABILITIES</span>
          <h2>
            不是“上传文件夹”，
            <br className="only-mobile" />
            是会<em>自动生长</em>的素材中枢
          </h2>
          <p>从入库到回答，每一步都真实可观测：能看到标签、向量、检索分数与模型成本。</p>
        </div>
        <div className="feature-grid">
          {FEATURES.map((f) => (
            <article key={f.title} className="feature-card">
              <span className="icon-tile">
                <f.icon size={20} />
              </span>
              <h3>{f.title}</h3>
              <p>{f.desc}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section pipe-section" id="pipeline">
        <div className="section-head">
          <span className="eyebrow">ONE PIPELINE</span>
          <h2>
            素材从进库到回答，
            <em>一条可解释的流水线</em>
          </h2>
        </div>
        <div className="pipe">
          {PIPELINE.map((p, i) => (
            <div key={p.title} className="pipe-step">
              <span className="pipe-num">{String(i + 1).padStart(2, "0")}</span>
              <h3>{p.title}</h3>
              <p>{p.desc}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="section eval-section" id="eval">
        <div className="section-head">
          <span className="eyebrow">MEASURED, NOT CLAIMED</span>
          <h2>
            检索效果不是感觉，
            <em>是 45 组真实查询测出来的</em>
          </h2>
          <p>5 种检索策略对比评测（含语义改写与纯视觉查询），关键指标如下。</p>
        </div>
        <div className="eval-grid">
          <div className="eval-card">
            <div className="eval-num">0.789</div>
            <div className="eval-cap">Recall@1 · 精排后</div>
            <div className="bar">
              <i style={{ width: "78.9%" }} />
            </div>
            <p>纯 BM25 基线 0.611 → 重排兜底后 0.789</p>
          </div>
          <div className="eval-card">
            <div className="eval-num">0.956</div>
            <div className="eval-cap">Recall@5 · 门控三路融合</div>
            <div className="bar">
              <i style={{ width: "95.6%" }} />
            </div>
            <p>朴素多模态融合是负结果，门控启用后全场最高</p>
          </div>
          <div className="eval-card">
            <div className="eval-num">0.893</div>
            <div className="eval-cap">MRR · 精排后</div>
            <div className="bar">
              <i style={{ width: "89.3%" }} />
            </div>
            <p>第一结果排得准，才叫“找到”，不只是“召回”</p>
          </div>
          <div className="eval-card">
            <div className="eval-num">100%</div>
            <div className="eval-cap">后端向量一致性</div>
            <div className="bar">
              <i style={{ width: "100%" }} />
            </div>
            <p>Milvus 与本地向量库在 45×5 评测上结果完全一致</p>
          </div>
        </div>
        <div className="eval-notes">
          <span>
            <CheckCircle2 size={15} />
            后端 pytest 全量自动化测试通过（模型全 mock，离线可跑）
          </span>
          <span>
            <CheckCircle2 size={15} />
            不填模型 Key 也能运行：自动降级为关键词检索 + 无打标入库
          </span>
        </div>
      </section>

      <section className="section stack-section" id="stack">
        <div className="stack-card">
          <div className="stack-left">
            <span className="eyebrow">TECH STACK</span>
            <h2>
              每层都用<em>“为什么是它”</em>做过取舍
            </h2>
            <p>
              检索是自己实现的 BM25 与向量库，不全是调包；Agent 是 LangGraph
              状态图，不是一句 prompt 就完事。
            </p>
            <Link className="btn primary btn-cta" to="/app">
              快速使用
              <ArrowRight size={17} />
            </Link>
          </div>
          <div className="stack-right">
            {STACK.map((s) => (
              <span key={s} className="stack-chip">
                <Database size={13} />
                {s}
              </span>
            ))}
          </div>
        </div>
      </section>

      <section className="final-cta">
        <div className="cta-glow" />
        <h2>现在就开始，搭建你的素材中枢</h2>
        <p>Docker 一条命令启动；不需要先填 Key，空跑也能体验完整流程。</p>
        <div className="cta-row">
          <Link className="btn primary btn-cta" to="/app">
            快速使用
            <ArrowRight size={17} />
          </Link>
          <a
            className="btn soft btn-cta"
            href="https://github.com/yerouguozi/multimodal-asset-agent"
            target="_blank"
            rel="noreferrer"
          >
            <FolderGit size={16} />
            GitHub 源码
          </a>
        </div>
      </section>

      <footer className="land-footer">
        <a className="brand" href="#top">
          <span className="brand-mark">M</span>
          <span>Multimodal Asset Agent</span>
        </a>
        <span className="footer-note">
          <Gauge size={13} />
          自研多模态素材管理 Agent · FastAPI + LangGraph + React
        </span>
        <a className="footer-gh" href="https://github.com/yerouguozi/multimodal-asset-agent" target="_blank" rel="noreferrer">
          <FolderGit size={15} />
          yerouguozi
        </a>
      </footer>
    </div>
  );
}
