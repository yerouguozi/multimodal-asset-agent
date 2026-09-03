import type { ComponentType } from "react";
import {
  Eye,
  FileText,
  Film,
  Image as ImageIcon,
  Inbox,
  Mic,
  SearchX,
  Trash2,
} from "lucide-react";
import type { Asset } from "../types";
import { timeAgoZh } from "../time";

interface Props {
  assets: Asset[];
  total: number;
  loading: boolean;
  hasFilter: boolean;
  onOpen: (a: Asset) => void;
  onDelete: (id: number) => void;
  onReset: () => void;
}

const MODALITY_ICON: Record<string, ComponentType<{ size?: number | string; className?: string }>> = {
  image: ImageIcon,
  video: Film,
  audio: Mic,
  document: FileText,
};

const STATUS_TEXT: Record<string, string> = {
  ready: "就绪",
  pending: "排队中",
  processing: "处理中",
  failed: "失败",
};

function ModalityIcon({ modality, size = 15 }: { modality: string; size?: number }) {
  const Icon = MODALITY_ICON[modality] ?? FileText;
  return <Icon size={size} aria-hidden="true" />;
}

function SkeletonGrid() {
  return (
    <div className="grid" aria-hidden="true">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="asset-card skeleton-card">
          <div className="skeleton-block thumb" />
          <div className="asset-body">
            <div className="skeleton-block line w60" />
            <div className="skeleton-block line w90" />
            <div className="skeleton-block line w70" />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function AssetGrid({
  assets,
  total,
  loading,
  hasFilter,
  onOpen,
  onDelete,
  onReset,
}: Props) {
  if (loading && !assets.length) {
    return (
      <section className="panel grid-panel" aria-busy="true" aria-label="素材加载中">
        <div className="grid-head">
          <span className="head-dot pulse" />
          正在加载素材库…
        </div>
        <SkeletonGrid />
      </section>
    );
  }

  if (!assets.length) {
    return (
      <section className="panel grid-panel">
        <div className="empty-state">
          {hasFilter ? <SearchX size={30} aria-hidden="true" /> : <Inbox size={30} aria-hidden="true" />}
          <h3>{hasFilter ? "没有找到匹配的素材" : "素材库还是空的"}</h3>
          <p>
            {hasFilter
              ? "换一个说法试试，或清空筛选后浏览全部素材。"
              : "把图片、视频、音频或文档拖进上方上传区，它会自动理解、打标并入库。"}
          </p>
          {hasFilter && (
            <button type="button" className="btn soft" onClick={onReset}>
              清空筛选，显示全部
            </button>
          )}
        </div>
      </section>
    );
  }

  return (
    <section className="panel grid-panel">
      <div className="grid-head">
        <span>
          素材库 <b>{total}</b>
          {hasFilter && <span className="head-filter">已筛选</span>}
        </span>
        <span className="head-hint">点击卡片查看详情</span>
      </div>
      <div className="grid">
        {assets.map((a) => (
          <article
            key={a.id}
            className="card asset-card"
            onClick={() => onOpen(a)}
          >
            <div className="asset-thumb">
              {a.thumbnail_url ? (
                <img src={a.thumbnail_url} alt={a.name} loading="lazy" />
              ) : (
                <div className="thumb-placeholder">
                  <ModalityIcon modality={a.modality} size={22} />
                  <span>{a.modality}</span>
                </div>
              )}
              <span className={`status-pill ${a.status}`}>
                <i />
                {STATUS_TEXT[a.status] ?? a.status}
              </span>
              <span className={`type-pill ${a.modality}`}>
                <ModalityIcon modality={a.modality} size={11} />
                {a.modality}
              </span>
              <span className="thumb-hover">
                <Eye size={14} />
                查看详情
              </span>
            </div>
            <div className="asset-body">
              <button type="button" className="asset-name-btn" onClick={() => onOpen(a)}>
                {a.name}
              </button>
              <p className="asset-desc">{a.description || "已入库，暂无自动描述"}</p>
              {a.tags.length > 0 && (
                <div className="tags">
                  {a.tags.slice(0, 3).map((t) => (
                    <span key={t.id} className="tag">
                      {t.name}
                    </span>
                  ))}
                  {a.tags.length > 3 && <span className="tag more">+{a.tags.length - 3}</span>}
                </div>
              )}
              <div className="asset-meta">
                <span className="asset-time">{timeAgoZh(a.created_at) && `上传于 ${timeAgoZh(a.created_at)}`}</span>
                <button
                  className="asset-delete"
                  aria-label={`删除素材 #${a.id} ${a.name}`}
                  title="删除素材"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(a.id);
                  }}
                >
                  <Trash2 size={13} />
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
