import { useEffect, useRef, useState } from "react";
import type { ComponentType } from "react";
import {
  Clock,
  FileText,
  Film,
  HardDrive,
  Hash,
  Image as ImageIcon,
  Maximize2,
  Mic,
  ScanText,
  Timer,
  Trash2,
  X,
} from "lucide-react";
import type { Asset } from "../types";
import type { TranscriptSegment } from "../types";
import { fetchAssetSegments } from "../api";

interface Props {
  asset: Asset;
  onClose: () => void;
  onDelete: (id: number) => void;
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

function fmtSize(n: number): string {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString("zh-CN", { hour12: false });
}

function fmtTs(sec?: number): string {
  const s = Math.max(0, Math.floor(sec ?? 0));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export default function AssetDetailModal({ asset, onClose, onDelete }: Props) {
  const modalRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const gap = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = "hidden";
    if (gap > 0) document.body.style.paddingRight = `${gap}px`;
    closeRef.current?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab" || !modalRef.current) return;
      const nodes = Array.from(modalRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (n) => n.offsetParent !== null
      );
      if (!nodes.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      document.body.style.paddingRight = "";
      prev?.focus?.();
    };
  }, [onClose]);

  useEffect(() => {
    if (asset.modality !== "video" && asset.modality !== "audio") return;
    let alive = true;
    fetchAssetSegments(asset.id)
      .then((d) => {
        if (alive) setSegments(d.segments);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [asset.id, asset.modality]);

  const seekTo = (start: number) => {
    const el = videoRef.current ?? audioRef.current;
    if (el) {
      el.currentTime = start;
      void el.play();
    }
  };

  const Icon = MODALITY_ICON[asset.modality] ?? FileText;
  const rows: { k: string; v: string; Icon: ComponentType<{ size?: number | string; className?: string }> }[] = [
    { k: "编号", v: `#${asset.id}`, Icon: Hash },
    { k: "原始文件名", v: asset.original_filename, Icon: FileText },
    { k: "大小", v: fmtSize(asset.size_bytes), Icon: HardDrive },
    { k: "上传时间", v: fmtDate(asset.created_at), Icon: Clock },
    ...(asset.width && asset.height
      ? [{ k: "尺寸", v: `${asset.width} × ${asset.height}px`, Icon: Maximize2 }]
      : []),
    ...(asset.duration != null
      ? [{ k: "时长", v: `${asset.duration.toFixed(1)} 秒`, Icon: Timer }]
      : []),
  ];
  const contentBlocks: { label: string; text: string; Icon: ComponentType<{ size?: number | string; className?: string }> }[] = [
    { label: "自动描述", text: asset.description ?? "", Icon: ScanText },
    { label: "OCR 文字", text: asset.ocr_text ?? "", Icon: ScanText },
    { label: "语音转写", text: asset.transcript ?? "", Icon: Mic },
    { label: "文档正文", text: asset.text_content ?? "", Icon: FileText },
  ].filter((b) => b.text);

  return (
    <div className="modal-mask" onClick={onClose}>
      <div
        ref={modalRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={`素材详情 #${asset.id} ${asset.name}`}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="modal-head">
          <div className="modal-title-wrap">
            <span className={`type-pill ${asset.modality}`}>
              <Icon size={11} aria-hidden="true" />
              {asset.modality}
            </span>
            <h2 id="asset-modal-title">
              #{asset.id} {asset.name}
            </h2>
          </div>
          <div className="modal-head-actions">
            <span className={`status-pill ${asset.status}`}>
              <i />
              {STATUS_TEXT[asset.status] ?? asset.status}
            </span>
            <button
              ref={closeRef}
              type="button"
              className="icon-btn"
              onClick={onClose}
              aria-label="关闭详情"
              title="关闭（Esc）"
            >
              <X size={16} />
            </button>
          </div>
        </header>

        <div className="modal-body">
          {asset.modality === "video" && asset.media_url ? (
            <div className="modal-preview">
              <video
                ref={videoRef}
                className="modal-media"
                src={asset.media_url}
                poster={asset.thumbnail_url ?? undefined}
                controls
                preload="metadata"
              />
            </div>
          ) : asset.modality === "audio" && asset.media_url ? (
            <div className="modal-preview">
              <audio ref={audioRef} className="modal-media audio" src={asset.media_url} controls preload="metadata" />
            </div>
          ) : asset.thumbnail_url ? (
            <div className="modal-preview">
              <img src={asset.thumbnail_url} alt={asset.name} />
            </div>
          ) : null}

          {segments.length > 0 && (
            <section className="modal-section">
              <h3>转写片段 · 点击跳转</h3>
              <div className="modal-segments">
                {segments.map((s, i) => (
                  <button
                    key={`${s.start}-${i}`}
                    type="button"
                    className="moment-ref"
                    onClick={() => seekTo(s.start)}
                  >
                    <span className="moment-time">
                      {fmtTs(s.start)}
                      {s.end != null ? `-${fmtTs(s.end)}` : ""}
                    </span>
                    <span className="moment-text">{s.text}</span>
                  </button>
                ))}
              </div>
            </section>
          )}

          {asset.error_message && (
            <div className="modal-error" role="alert">
              处理失败：{asset.error_message}
            </div>
          )}

          <dl className="detail-grid">
            {rows.map(({ k, v, Icon: RowIcon }) => (
              <div key={k} className="detail-item">
                <dt>
                  <RowIcon size={13} aria-hidden="true" />
                  {k}
                </dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>

          {asset.tags.length > 0 && (
            <section className="modal-section">
              <h3>标签</h3>
              <div className="tags">
                {asset.tags.map((t) => (
                  <span key={t.id} className="tag" title={`来源：${t.source}`}>
                    {t.name}
                    <i>{t.source}</i>
                  </span>
                ))}
              </div>
            </section>
          )}

          <section className="modal-section">
            <h3>内容理解</h3>
            {contentBlocks.length ? (
              contentBlocks.map(({ label, text, Icon: BlockIcon }) => (
                <div key={label} className="content-block">
                  <h4>
                    <BlockIcon size={13} aria-hidden="true" />
                    {label}
                  </h4>
                  <p>{text}</p>
                </div>
              ))
            ) : (
              <p className="modal-muted">
                {asset.status === "ready"
                  ? "这条素材已入库，但没有可展示的理解文本。"
                  : "理解结果生成后会显示在这里。"}
              </p>
            )}
          </section>
        </div>

        <footer className="modal-foot">
          <button type="button" className="btn soft" onClick={onClose}>
            关闭
          </button>
          <button
            type="button"
            className="btn danger"
            onClick={() => onDelete(asset.id)}
          >
            <Trash2 size={14} />
            删除素材
          </button>
        </footer>
      </div>
    </div>
  );
}
