import type { DomainProfile, UsageSummary } from "../types";

interface Props {
  profile: DomainProfile | null;
  usage: UsageSummary | null;
  onRefresh: () => void;
}

export default function DomainProfileCard({ profile, usage, onRefresh }: Props) {
  return (
    <section className="panel profile-panel">
      <div className="panel-head">
        <b>素材库画像</b>
        <button className="link-btn" onClick={onRefresh}>
          刷新
        </button>
      </div>
      {profile ? (
        <>
          <p className="profile-summary">{profile.summary}</p>
          {profile.labels.length > 0 && (
            <div className="tags">
              {profile.labels.map((l, i) => (
                <span key={i} className="tag label">
                  {l}
                </span>
              ))}
            </div>
          )}
          <div className="bars">
            {Object.entries(profile.by_modality).map(([m, c]) => (
              <div key={m} className="bar-row">
                <span className="bar-label">
                  {m} {c}
                </span>
                <div className="bar">
                  <div className="bar-fill" style={{ width: `${(c / Math.max(1, profile.total)) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
          <div className="weights">自适应检索权重 {JSON.stringify(profile.adaptive_weights)}</div>
          {usage && (
            <div className="weights" style={{ marginTop: 6 }}>
              模型调用 {usage.total_calls} 次 · 估算成本 ${usage.total_cost.toFixed(4)}
              {usage.by_model && `（${Object.keys(usage.by_model).length} 种模型）`}
            </div>
          )}
        </>
      ) : (
        <div className="empty">加载中…</div>
      )}
    </section>
  );
}
