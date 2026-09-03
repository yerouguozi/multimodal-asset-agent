/** 后端时间按 UTC 存储且不带时区标记；显示前统一按 UTC 解析再转本地。 */
export function parseUtc(iso?: string | null): Date | null {
  if (!iso) return null;
  const hasOffset = /(Z|[+-]\d{2}:\d{2})$/.test(iso);
  const d = new Date(hasOffset ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function timeAgoZh(iso?: string | null): string {
  const t = parseUtc(iso);
  if (!t) return "";
  const diff = Date.now() - t.getTime();
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} 小时前`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d} 天前`;
  return t.toLocaleDateString("zh-CN");
}

export function fmtDateTime(iso?: string | null, withSeconds = true): string {
  const t = parseUtc(iso);
  if (!t) return iso ?? "";
  return t.toLocaleString("zh-CN", { hour12: false, second: withSeconds ? "2-digit" : undefined });
}
