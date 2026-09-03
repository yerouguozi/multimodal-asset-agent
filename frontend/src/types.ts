export interface Tag {
  id: number;
  name: string;
  source: string;
}

export interface Asset {
  id: number;
  name: string;
  original_filename: string;
  modality: string;
  mime_type: string;
  size_bytes: number;
  status: string;
  description: string | null;
  ocr_text: string | null;
  transcript: string | null;
  text_content: string | null;
  width: number | null;
  height: number | null;
  duration: number | null;
  thumbnail_url: string | null;
  error_message: string | null;
  created_at: string;
  tags: Tag[];
}

export interface AssetList {
  items: Asset[];
  total: number;
  page: number;
  page_size: number;
}

export interface SearchHit {
  asset: Asset;
  score: number;
}

export interface SearchResponse {
  query: string;
  hits: SearchHit[];
}

export interface UploadItem {
  asset?: Asset | null;
  duplicate_of?: number | null;
  error?: string | null;
}

export interface DomainProfile {
  total: number;
  by_modality: Record<string, number>;
  modality_shares: Record<string, number>;
  top_tags: { name: string; count: number }[];
  adaptive_weights: Record<string, number>;
  labels: string[];
  summary: string;
}

export interface UsageSummary {
  total_calls: number;
  total_cost: number;
  by_model: Record<string, number>;
  recent: { asset_id: number | null; model: string; operation: string; cost: number; created_at: string }[];
}
export interface PlanStep {
  tool: string;
  args?: Record<string, unknown>;
}

export interface TraceAsset {
  id: number;
  name: string;
  modality?: string;
  description?: string | null;
  tags?: string[];
}

export interface TraceMoment {
  asset_id: number;
  name: string;
  start: number;
  end?: number | null;
  snippet: string;
}

export interface ChatEvent {
  stage?: string;
  content?: string;
  text?: string;
  session_id?: string;
  intent?: string;
  steps?: PlanStep[];
  tool?: string;
  ok?: boolean;
  summary?: string;
  assets?: TraceAsset[];
  moments?: TraceMoment[];
  labels?: string[];
  by_modality?: Record<string, number>;
  elapsed_ms?: number;
}

export interface ChatSessionSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message?: string | null;
}

export interface ChatMessageRecord {
  id: number;
  role: string;
  content: string;
  created_at: string;
}
