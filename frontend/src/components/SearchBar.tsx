import { useRef } from "react";

interface Props {
  query: string;
  setQuery: (s: string) => void;
  modality: string;
  setModality: (s: string) => void;
  tag: string;
  setTag: (s: string) => void;
  onSearch: () => void;
  onReset: () => void;
  onImageSearch: (f: File) => void;
}

export default function SearchBar({
  query, setQuery, modality, setModality, tag, setTag, onSearch, onReset, onImageSearch,
}: Props) {
  const imgRef = useRef<HTMLInputElement>(null);
  return (
    <section className="panel search-panel">
      <div className="row">
        <input
          className="text-input grow"
          placeholder="自然语言检索，如：夜景 / 复古游戏 / 营销方案"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSearch();
          }}
        />
        <button className="btn primary" onClick={onSearch}>
          搜索
        </button>
        <button className="btn ghost" onClick={onReset}>
          全部素材
        </button>
        <button className="btn ghost" onClick={() => imgRef.current?.click()}>
          以图搜图
        </button>
        <input
          ref={imgRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onImageSearch(f);
            e.target.value = "";
          }}
        />
      </div>
      <div className="row">
        <select className="text-input" value={modality} onChange={(e) => setModality(e.target.value)}>
          <option value="">全部类型</option>
          <option value="image">图片</option>
          <option value="video">视频</option>
          <option value="audio">音频</option>
          <option value="document">文档</option>
        </select>
        <input
          className="text-input grow"
          placeholder="按标签筛选（可选）"
          value={tag}
          onChange={(e) => setTag(e.target.value)}
        />
      </div>
    </section>
  );
}
