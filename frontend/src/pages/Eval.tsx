import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, BarChart3, CheckCircle2, FlaskConical } from "lucide-react";

interface StrategyRow {
  key: string;
  name: string;
  recall1: number;
  recall3: number;
  recall5: number;
  mrr: number;
  ndcg3: number;
}

interface EvalData {
  meta: { title: string; queries: number; strategies: number; note: string };
  best: { strategy: string; recall1: number; recall5: number; mrr: number; note: string };
  strategies: StrategyRow[];
  conclusions: string[];
  consistency: string;
}

export default function Eval() {
  const [data, setData] = useState<EvalData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/eval.json")
      .then((r) => (r.ok ? (r.json() as Promise<EvalData>) : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="eval-page">
      <header className="eval-nav">
        <Link to="/app" className="ghost-chip">
          <ArrowLeft size={14} />
          工作台
        </Link>
        <Link to="/" className="brand">
          <span className="brand-mark">M</span>
          <span className="brand-text">Retrieval <i>Eval</i></span>
        </Link>
        <a className="ghost-chip" href="https://github.com/yerouguozi/multimodal-asset-agent" target="_blank" rel="noreferrer">
          查看源码
        </a>
      </header>

      {error ? (
        <div className="eval-empty">评测数据加载失败：{error}</div>
      ) : !data ? (
        <div className="eval-empty">加载评测数据…</div>
      ) : (
        <main className="eval-main">
          <div className="eval-hero">
            <span className="eyebrow">
              <FlaskConical size={13} />
              {data.meta.queries} QUERIES × {data.meta.strategies} STRATEGIES
            </span>
            <h1>{data.meta.title}</h1>
            <p>{data.meta.note}</p>
          </div>

          <section className="eval-cards">
            <div className="eval-card">
              <div className="eval-num">{data.best.recall1.toFixed(3)}</div>
              <div className="eval-cap">Recall@1 · {data.best.strategy}</div>
              <div className="bar">
                <i style={{ width: `${data.best.recall1 * 100}%` }} />
              </div>
            </div>
            <div className="eval-card">
              <div className="eval-num">{data.best.recall5.toFixed(3)}</div>
              <div className="eval-cap">Recall@5 · 门控融合</div>
              <div className="bar">
                <i style={{ width: `${data.best.recall5 * 100}%` }} />
              </div>
            </div>
            <div className="eval-card">
              <div className="eval-num">{data.best.mrr.toFixed(3)}</div>
              <div className="eval-cap">MRR · {data.best.strategy}</div>
              <div className="bar">
                <i style={{ width: `${data.best.mrr * 100}%` }} />
              </div>
            </div>
          </section>

          <section className="eval-table-wrap">
            <h2>
              <BarChart3 size={17} />
              五种策略量化对比
            </h2>
            <div className="eval-table">
              <div className="ev-row head">
                <span>策略</span>
                <span>Recall@1</span>
                <span>Recall@3</span>
                <span>Recall@5</span>
                <span>MRR</span>
                <span>NDCG@3</span>
              </div>
              {data.strategies.map((s) => (
                <div key={s.key} className="ev-row">
                  <span className="ev-name">
                    <i>{s.key}</i>
                    {s.name}
                  </span>
                  <span>{s.recall1.toFixed(3)}</span>
                  <span>{s.recall3.toFixed(3)}</span>
                  <span>{s.recall5.toFixed(3)}</span>
                  <span>{s.mrr.toFixed(3)}</span>
                  <span>{s.ndcg3.toFixed(3)}</span>
                </div>
              ))}
            </div>
            <p className="eval-best-note">{data.best.note}</p>
          </section>

          <section className="eval-insights">
            <h2>从评测里得到的结论</h2>
            <ul>
              {data.conclusions.map((c) => (
                <li key={c}>
                  <CheckCircle2 size={15} />
                  {c}
                </li>
              ))}
            </ul>
            <p className="eval-consistency">{data.consistency}</p>
          </section>
        </main>
      )}
    </div>
  );
}
