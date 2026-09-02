import { useRef, useState } from "react";

interface Props {
  onUpload: (files: File[]) => void;
  busy: boolean;
}

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
        type="file"
        multiple
        hidden
        onChange={(e) => {
          onUpload(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
      <div className="upload-inner" onClick={() => inputRef.current?.click()}>
        <div className="upload-title">{busy ? "处理中…" : "拖拽素材到这里，或点击选择文件"}</div>
        <div className="upload-hint">图片 / 视频 / 音频 / PDF / Word / Excel / TXT · 自动打标、摘要、转录、入库</div>
      </div>
    </section>
  );
}
