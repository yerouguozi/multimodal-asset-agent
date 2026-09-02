import type { DomainProfile } from "../types";

interface Props {
  profile: DomainProfile | null;
  onRefresh: () => void;
}

export default function DomainProfileCard({ profile, onRefresh }: Props) {
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
        </>
      ) : (
        <div className="empty">加载中…</div>
      )}
    </section>
  );
}
