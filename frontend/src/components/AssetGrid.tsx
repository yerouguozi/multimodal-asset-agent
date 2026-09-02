import type { Asset } from "../types";

interface Props {
  assets: Asset[];
  total: number;
  onOpen: (a: Asset) => void;
  onDelete: (id: number) => void;
}

export default function AssetGrid({ assets, total, onOpen, onDelete }: Props) {
  if (!assets.length) {
    return <div className="empty">还没有素材，拖拽上传一些吧</div>;
  }
  return (
    <section className="panel grid-panel">
      <div className="grid-head">
        共 {total} 个素材
      </div>
      <div className="grid">
        {assets.map((a) => (
          <article key={a.id} className="card asset-card" onClick={() => onOpen(a)}>
            {a.thumbnail_url ? (
              <img src={a.thumbnail_url} alt={a.name} loading="lazy" />
            ) : (
              <div className="thumb-placeholder">{a.modality}</div>
            )}
            <div className="asset-body">
              <div className="asset-name">
                <span className={`badge ${a.modality}`}>{a.modality}</span>
                <span className="name-text">{a.name}</span>
              </div>
              <div className="asset-desc">{a.description || "（暂无描述）"}</div>
              <div className="tags">
                {a.tags.slice(0, 6).map((t) => (
                  <span key={t.id} className="tag">
                    {t.name}
                  </span>
                ))}
              </div>
              <div className="asset-meta">
                <span className={`status ${a.status}`}>{a.status}</span>
                <button
                  className="link-btn danger"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(a.id);
                  }}
                >
                  删除
                </button>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
