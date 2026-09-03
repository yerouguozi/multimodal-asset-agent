import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, ArrowLeft, BarChart3, Clock3, Gauge, RefreshCw } from "lucide-react";
import { fetchSearchMetrics } from "../api";
import type { SearchMetrics } from "../types";

const STRATEGY_LABEL: Record<string, string> = {
  full: "full（含重排）",
  rrf: "RRF 融合",
  gate: "门控三路",
  tri: "朴素三路",
  bm25: "仅 BM25",
};

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString("zh-CN", { hour12: false });
}

export default function Metrics() {
  const [data, setData] = useState<SearchMetrics | null>(null);
  const [error, setError] = useState("");

  const load = () => {
    fetchSearchMetrics().then(setData).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  };

  useEffect(load, []);

  return (
    <div className="eval-page metrics-page">
      <header className="eval-nav">
        <Link to="/app" className="ghost-chip">
          <ArrowLeft size={14} />
          工作台
        </Link>
        <span className="brand">
          <span className="brand-mark">M</span>
          <span className="brand-text">Search <i>Metrics</i></span>
        </span>
        <button type="button" className="ghost-chip" onClick={load} aria-label="刷新指标">
          <RefreshCw size={14} />
          刷新
        </button>
      </header>

      <main className="eval-main">
        {error ? (
          <div className="eval-empty">指标加载失败：{error}</div>
        ) : !data ? (
          <div className="eval-empty">加载检索指标…</div>
        ) : (
          <>
            <div className="eval-hero">
              <span className="eyebrow">
                <Activity size={13} />
                RETRIEVAL OBSERVABILITY
              </span>
              <h1>检索实时指标</h1>
              <p>API 与 Agent 工具的每次检索都会落日志，这里展示延迟、命中与来源分布。</p>
            </div>

            <section className="eval-cards">
              <div className="eval-card">
                <div className="eval-num">{data.total_queries}</div>
                <div className="eval-cap">累计查询</div>
              </div>
              <div className="eval-card">
                <div className="eval-num">{data.p95_latency_ms.toFixed(0)}ms</div>
                <div className="eval-cap">P95 延迟</div>
              </div>
              <div className="eval-card">
                <div className="eval-num">{data.avg_latency_ms.toFixed(0)}ms</div>
                <div className="eval-cap">平均延迟</div>
              </div>
              <div className="eval-card">
                <div className="eval-num">{data.avg_hits.toFixed(1)}</div>
                <div className="eval-cap">平均命中</div>
              </div>
            </section>

            {data.total_queries > 0 && (
              <section className="metric-grid">
                <div className="metric-card">
                  <h2>
                    <Gauge size={15} />
                    来源 / 策略分布
                  </h2>
                  {[
                    { title: "按来源", map: data.by_source },
                    { title: "按策略", map: data.by_strategy },
                  ].map(({ title, map }) => {
                    const entries = Object.entries(map);
                    const total = entries.reduce((s, [, c]) => s + c, 0) || 1;
                    return (
                      <div key={title} className="metric-group">
                        <h3>{title}</h3>
                        {entries.length === 0 ? (
                          <p className="metric-empty">暂无数据</p>
                        ) : (
                          entries.map(([k, c]) => (
                            <div key={k} className="metric-row">
                              <span>{STRATEGY_LABEL[k] ?? k}</span>
                              <div className="bar">
                                <i style={{ width: `${(c / total) * 100}%` }} />
                              </div>
                              <b>{c}</b>
                            </div>
                          ))
                        )}
                      </div>
                    );
                  })}
                </div>

                <div className="metric-card">
                  <h2>
                    <BarChart3 size={15} />
                    高频查询
                  </h2>
                  {data.top_queries.length === 0 ? (
                    <p className="metric-empty">暂无数据</p>
                  ) : (
                    <div className="top-query-list">
                      {data.top_queries.map((q) => (
                        <div key={`${q.query}-${q.count}`} className="top-query">
                          <span>{q.query}</span>
                          <i>
                            {q.count} 次 · {q.avg_latency_ms.toFixed(0)}ms
                          </i>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </section>
            )}

            <section className="eval-table-wrap">
              <h2>
                <Clock3 size={16} />
                最近查询
              </h2>
              {data.recent.length === 0 ? (
                <p className="metric-empty">还没有检索记录——回工作台搜一次就有了。</p>
              ) : (
                <div className="eval-table">
                  <div className="ev-row head">
                    <span>时间</span>
                    <span>查询</span>
                    <span>来源</span>
                    <span>策略</span>
                    <span>耗时</span>
                    <span>命中</span>
                  </div>
                  {[...data.recent].reverse().map((r, i) => (
                    <div key={`${r.created_at}-${i}`} className="ev-row">
                      <span>{fmtTime(r.created_at)}</span>
                      <span className="ev-query">{r.query}</span>
                      <span>{r.source === "agent-tool" ? "Agent 工具" : "API"}</span>
                      <span>{STRATEGY_LABEL[r.strategy] ?? r.strategy}</span>
                      <span>{r.latency_ms}ms</span>
                      <span>{r.hits_count}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
