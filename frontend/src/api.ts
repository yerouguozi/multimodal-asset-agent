import type {
  Asset,
  AssetList,
  AssetSegments,
  ChatMessageRecord,
  ChatSessionSummary,
  ChatEvent,
  DomainProfile,
  SearchHit,
  SearchMetrics,
  SearchResponse,
  UploadItem,
  UsageSummary,
} from "./types";

const TOKEN_KEY = "mma_token";
const USER_KEY = "mma_user";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser(): string | null {
  return localStorage.getItem(USER_KEY);
}

export function setAuth(token: string, username: string): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, username);
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(input, { ...init, headers });
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return r.json() as Promise<T>;
}

export function fetchAssets(opts: { modality?: string; tag?: string; pageSize?: number } = {}): Promise<AssetList> {
  const p = new URLSearchParams();
  if (opts.modality) p.set("modality", opts.modality);
  if (opts.tag) p.set("tag", opts.tag);
  p.set("page_size", String(opts.pageSize ?? 50));
  return apiFetch(`/api/assets?${p}`).then((r) => j<AssetList>(r));
}

export function searchAssets(q: string, modality?: string, tag?: string): Promise<SearchResponse> {
  const p = new URLSearchParams({ q });
  if (modality) p.set("modality", modality);
  if (tag) p.set("tag", tag);
  return apiFetch(`/api/search?${p}`).then((r) => j<SearchResponse>(r));
}

export async function uploadFiles(files: File[]): Promise<UploadItem[]> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  const r = await apiFetch("/api/upload", { method: "POST", body: fd });
  const data = await j<{ items: UploadItem[] }>(r);
  return data.items;
}

export function deleteAsset(id: number): Promise<void> {
  return apiFetch(`/api/assets/${id}`, { method: "DELETE" }).then(() => undefined);
}

export function fetchAsset(id: number): Promise<Asset> {
  return apiFetch(`/api/assets/${id}`).then((r) => j<Asset>(r));
}

export function fetchAssetSegments(id: number): Promise<AssetSegments> {
  return apiFetch(`/api/assets/${id}/segments`).then((r) => j<AssetSegments>(r));
}

export function fetchDomainProfile(): Promise<DomainProfile> {
  return apiFetch("/api/domain/profile").then((r) => j<DomainProfile>(r));
}

export async function searchByImage(file: File): Promise<SearchHit[]> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await apiFetch("/api/search/image", { method: "POST", body: fd });
  const data = await j<{ hits: SearchHit[] }>(r);
  return data.hits;
}

export function fetchUsageSummary(): Promise<UsageSummary> {
  return apiFetch("/api/usage/summary").then((r) => j<UsageSummary>(r));
}

export function fetchSearchMetrics(): Promise<SearchMetrics> {
  return apiFetch("/api/metrics/search").then((r) => j<SearchMetrics>(r));
}

export function fetchChatSessions(): Promise<ChatSessionSummary[]> {
  return apiFetch("/api/chat/sessions")
    .then((r) => j<{ sessions: ChatSessionSummary[] }>(r))
    .then((d) => d.sessions);
}

export function fetchChatMessages(sessionId: string): Promise<ChatMessageRecord[]> {
  return apiFetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`)
    .then((r) => j<{ messages: ChatMessageRecord[] }>(r))
    .then((d) => d.messages);
}

export async function authLogin(username: string, password: string): Promise<void> {
  const r = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await j<{ access_token: string }>(r);
  setAuth(data.access_token, username);
}

export async function authRegister(username: string, password: string): Promise<void> {
  const r = await fetch("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await j<{ access_token: string }>(r);
  setAuth(data.access_token, username);
}

export async function chatStream(
  message: string,
  sessionId: string,
  onEvent: (e: ChatEvent) => void
): Promise<void> {
  const resp = await apiFetch("/api/chat", {
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
