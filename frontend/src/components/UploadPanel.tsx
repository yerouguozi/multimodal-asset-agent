import { useRef, useState } from "react";
import { FileUp, Loader2, Sparkles } from "lucide-react";

interface Props {
  onUpload: (files: File[]) => void;
  busy: boolean;
}

const SUPPORTED = ["图片", "视频", "音频", "PDF", "Word", "Excel", "TXT"];

export default function UploadPanel({ onUpload, busy }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);

  return (
    <section
      className={`panel upload-panel${drag ? " dragging" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        onUpload(Array.from(e.dataTransfer.files));
      }}
    >
      <input
        ref={inputRef}
        id="asset-upload-input"
        type="file"
        multiple
        hidden
        onChange={(e) => {
          onUpload(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
      <button
        type="button"
        className="upload-inner"
        onClick={() => inputRef.current?.click()}
        aria-haspopup="dialog"
      >
        <span className="upload-visual" aria-hidden="true">
          {busy ? <Loader2 className="spin" size={24} /> : <FileUp size={24} />}
        </span>
        <span className="upload-title">
          {busy ? "正在理解并入库…" : "拖拽素材到这里，或点击选择文件"}
        </span>
        <span className="upload-hint">
          {busy ? "解析 / 打标 / 摘要 / 向量化会在后台自动完成" : "入库后自动完成理解与索引，随时可用自然语言找到它们"}
        </span>
        <span className="upload-formats">
          {SUPPORTED.map((f) => (
            <i key={f}>{f}</i>
          ))}
          <span className="upload-auto">
            <Sparkles size={11} />
            自动打标
          </span>
        </span>
      </button>
    </section>
  );
}
