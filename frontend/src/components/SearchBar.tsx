import { useRef } from "react";
import type { ComponentType } from "react";
import {
  Film,
  FileText,
  Image as ImageIcon,
  LayoutGrid,
  Mic,
  RotateCcw,
  ScanSearch,
  Search,
  Tag,
  X,
} from "lucide-react";

interface Props {
  query: string;
  setQuery: (s: string) => void;
  modality: string;
  onModalityChange: (m: string) => void;
  tag: string;
  setTag: (s: string) => void;
  onSearch: () => void;
  onReset: () => void;
  onImageSearch: (f: File) => void;
}

const MODALITIES: {
  value: string;
  label: string;
  icon: ComponentType<{ size?: number | string; className?: string }>;
}[] = [
  { value: "", label: "全部", icon: LayoutGrid },
  { value: "image", label: "图片", icon: ImageIcon },
  { value: "video", label: "视频", icon: Film },
  { value: "audio", label: "音频", icon: Mic },
  { value: "document", label: "文档", icon: FileText },
];

export default function SearchBar({
  query,
  setQuery,
  modality,
  onModalityChange,
  tag,
  setTag,
  onSearch,
  onReset,
  onImageSearch,
}: Props) {
  const imgRef = useRef<HTMLInputElement>(null);

  return (
    <section className="panel search-panel" aria-label="素材搜索">
      <div className="search-main">
        <div className="search-field">
          <Search size={16} className="field-icon" aria-hidden="true" />
          <input
            className="search-input"
            type="search"
            placeholder="自然语言检索：夜景 / 复古游戏 / 营销方案"
            aria-label="输入自然语言查询"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onSearch();
            }}
          />
          {query && (
            <button
              type="button"
              className="field-clear"
              aria-label="清空输入"
              onClick={() => setQuery("")}
            >
              <X size={14} />
            </button>
          )}
          <kbd className="search-kbd">↵ 搜索</kbd>
        </div>

        <div className="search-actions">
          <button type="button" className="btn primary" onClick={onSearch}>
            <Search size={15} />
            搜索
          </button>
          <button
            type="button"
            className="btn ghost"
            onClick={() => imgRef.current?.click()}
            title="用一张参考图片查找相似素材"
          >
            <ScanSearch size={15} />
            以图搜图
          </button>
          <button
            type="button"
            className="btn icon ghost"
            onClick={onReset}
            aria-label="清除筛选，显示全部素材"
            title="显示全部素材"
          >
            <RotateCcw size={15} />
          </button>
        </div>
      </div>

      <div className="search-filters">
        <div className="seg" role="group" aria-label="按素材类型筛选">
          {MODALITIES.map((m) => {
            const Icon = m.icon;
            const active = modality === m.value;
            return (
              <button
                key={m.value || "all"}
                type="button"
                className={`seg-btn${active ? " active" : ""}`}
                aria-pressed={active}
                onClick={() => onModalityChange(active ? "" : m.value)}
              >
                <Icon size={14} />
                {m.label}
              </button>
            );
          })}
        </div>

        <div className="tag-filter">
          <Tag size={14} aria-hidden="true" />
          <input
            className="tag-input"
            type="text"
            placeholder="按标签筛选"
            aria-label="按标签筛选"
            value={tag}
            onChange={(e) => setTag(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onSearch();
            }}
          />
          {tag && (
            <button
              type="button"
              className="field-clear"
              aria-label="清空标签筛选"
              onClick={() => {
                setTag("");
                onSearch();
              }}
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      <input
        ref={imgRef}
        type="file"
        accept="image/*"
        hidden
        aria-label="选择参考图片"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onImageSearch(f);
          e.target.value = "";
        }}
      />
    </section>
  );
}
