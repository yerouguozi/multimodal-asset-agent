import type {
  Asset,
  AssetList,
  ChatEvent,
  DomainProfile,
  SearchHit,
  SearchResponse,
  UploadItem,
  UsageSummary,
} from "./types";

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return r.json() as Promise<T>;
}

export function fetchAssets(opts: { modality?: string; tag?: string; pageSize?: number } = {}): Promise<AssetList> {
  const p = new URLSearchParams();
  if (opts.modality) p.set("modality", opts.modality);
  if (opts.tag) p.set("tag", opts.tag);
  p.set("page_size", String(opts.pageSize ?? 50));
  return fetch(`/api/assets?${p}`).then((r) => j<AssetList>(r));
}

export function searchAssets(q: string, modality?: string, tag?: string): Promise<SearchResponse> {
  const p = new URLSearchParams({ q });
  if (modality) p.set("modality", modality);
  if (tag) p.set("tag", tag);
  return fetch(`/api/search?${p}`).then((r) => j<SearchResponse>(r));
}

export async function uploadFiles(files: File[]): Promise<UploadItem[]> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  const r = await fetch("/api/upload", { method: "POST", body: fd });
  const data = await j<{ items: UploadItem[] }>(r);
  return data.items;
}

export function deleteAsset(id: number): Promise<void> {
  return fetch(`/api/assets/${id}`, { method: "DELETE" }).then(() => undefined);
}

export function fetchAsset(id: number): Promise<Asset> {
  return fetch(`/api/assets/${id}`).then((r) => j<Asset>(r));
}

export function fetchDomainProfile(): Promise<DomainProfile> {
  return fetch("/api/domain/profile").then((r) => j<DomainProfile>(r));
}

export async function searchByImage(file: File): Promise<SearchHit[]> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/api/search/image", { method: "POST", body: fd });
  const data = await j<{ hits: SearchHit[] }>(r);
  return data.hits;
}

export function fetchUsageSummary(): Promise<UsageSummary> {
  return fetch("/api/usage/summary").then((r) => j<UsageSummary>(r));
}

export async function chatStream(
  message: string,
  sessionId: string,
  onEvent: (e: ChatEvent) => void
): Promise<void> {
  const resp = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() ?? "";
    for (const part of parts) {
      for (const line of part.split("\n")) {
        if (line.startsWith("data: ")) {
          onEvent(JSON.parse(line.slice(6)) as ChatEvent);
        }
      }
    }
  }
}
