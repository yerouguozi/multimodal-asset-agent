import type { Asset } from "../types";

interface Props {
  asset: Asset;
  onClose: () => void;
  onDelete: (id: number) => void;
}

function fmtSize(n: number): string {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}

export default function AssetDetailModal({ asset, onClose, onDelete }: Props) {
  const rows: [string, string | null][] = [
    ["类型", asset.modality],
    ["原始文件名", asset.original_filename],
    ["大小", fmtSize(asset.size_bytes)],
    ["状态", asset.status],
    ["描述", asset.description],
    ["OCR", asset.ocr_text],
    ["转写", asset.transcript],
    ["正文", asset.text_content],
    ["尺寸", asset.width && asset.height ? `${asset.width} × ${asset.height}` : null],
    ["时长", asset.duration != null ? `${asset.duration.toFixed(1)} 秒` : null],
    ["上传时间", asset.created_at],
    ["错误信息", asset.error_message],
  ];

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <b>
            #{asset.id} {asset.name}
          </b>
          <button className="link-btn" onClick={onClose}>
            关闭
          </button>
        </div>
        <div className="modal-body">
          {asset.thumbnail_url && <img className="modal-img" src={asset.thumbnail_url} alt="" />}
          <div className="tags">
            {asset.tags.map((t) => (
              <span key={t.id} className="tag">
                {t.name}（{t.source}）
              </span>
            ))}
          </div>
          <table className="detail-table">
            <tbody>
              {rows.map(
                ([k, v]) =>
                  v != null && v !== "" && (
                    <tr key={k}>
                      <td className="k">{k}</td>
                      <td className="v">{v}</td>
                    </tr>
                  )
              )}
            </tbody>
          </table>
        </div>
        <div className="modal-foot">
          <button className="btn danger" onClick={() => onDelete(asset.id)}>
            删除素材
          </button>
        </div>
      </div>
    </div>
  );
}
