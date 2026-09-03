import { useEffect, useState } from "react";
import type { ComponentType } from "react";
import {
  Eye,
  Download,
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
import { downloadAssetsZip, mediaHref } from "../api";

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
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [selectMode, setSelectMode] = useState(false);
  const [zipping, setZipping] = useState(false);

  useEffect(() => {
    setSelected(new Set());
  }, [assets]);

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const download = async () => {
    if (!selected.size || zipping) return;
    setZipping(true);
    try {
      await downloadAssetsZip(Array.from(selected));
      setSelected(new Set());
      setSelectMode(false);
    } catch {
      window.alert("打包下载失败，请稍后重试");
    } finally {
      setZipping(false);
    }
  };

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
        <span className="head-actions">
          <button
            type="button"
            className={`link-btn${selectMode ? " on" : ""}`}
            onClick={() => {
              setSelectMode((v) => !v);
              setSelected(new Set());
            }}
          >
            {selectMode ? "完成" : "选择"}
          </button>
          {selectMode && (
            <button
              type="button"
              className="link-btn"
              disabled={assets.length === 0 || selected.size === assets.length}
              onClick={() => setSelected(new Set(assets.map((a) => a.id)))}
            >
              全选本页
            </button>
          )}
          <span className="head-hint">点击卡片查看详情</span>
        </span>
      </div>
      {selectMode && selected.size > 0 && (
        <div className="bulk-bar">
          <span>
            已选 <b>{selected.size}</b> 个素材
          </span>
          <span className="bulk-actions">
            <button type="button" className="btn primary" onClick={() => void download()} disabled={zipping}>
              {zipping ? "打包中…" : "打包下载"}
            </button>
            <button
              type="button"
              className="btn soft"
              onClick={() => setSelected(new Set())}
              disabled={zipping}
            >
              清除选择
            </button>
          </span>
        </div>
      )}
      <div className="grid">
        {assets.map((a) => (
          <article
            key={a.id}
            className="card asset-card"
            onClick={() => onOpen(a)}
          >
            <div className="asset-thumb">
              {selectMode && (
                <button
                  type="button"
                  className={`card-select${selected.has(a.id) ? " on" : ""}`}
                  aria-label={selected.has(a.id) ? `取消选择素材 #${a.id}` : `选择素材 #${a.id}`}
                  aria-pressed={selected.has(a.id)}
                  onClick={(e) => {
                    e.stopPropagation();
                    toggle(a.id);
                  }}
                >
                  <i />
                </button>
              )}
              {a.thumbnail_url ? (
                <img src={mediaHref(a.thumbnail_url)} alt={a.name} loading="lazy" />
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
                <span className="asset-actions">
                  {a.media_url && (
                    <a
                      className="asset-action"
                      href={a.media_url}
                      download={a.original_filename || a.name}
                      aria-label={`下载素材 #${a.id} ${a.name}`}
                      title="下载原文件"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Download size={13} />
                    </a>
                  )}
                  <button
                    className="asset-action danger"
                    aria-label={`删除素材 #${a.id} ${a.name}`}
                    title="删除素材"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(a.id);
                    }}
                  >
                    <Trash2 size={13} />
                  </button>
                </span>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
