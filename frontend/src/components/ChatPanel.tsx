import { useEffect, useRef, useState } from "react";
import type { ComponentType } from "react";
import {
  Bot,
  FileText,
  History,
  Image as ImageIcon,
  Plus,
  Radar,
  Search,
  Send,
  SlidersHorizontal,
  Sparkles,
  Timer,
  X,
} from "lucide-react";
import {
  chatStream,
  fetchChatMessages,
  fetchChatSessions,
} from "../api";
import type {
  ChatMessageRecord,
  ChatSessionSummary,
  PlanStep,
  TraceAsset,
  TraceMoment,
} from "../types";

interface Msg {
  role: "user" | "assistant" | "step" | "plan" | "trace";
  text?: string;
  intent?: string;
  steps?: PlanStep[];
  tool?: string;
  ok?: boolean;
  summary?: string;
  assets?: TraceAsset[];
  moments?: TraceMoment[];
  labels?: string[];
  elapsed_ms?: number;
}

interface Props {
  onComplete?: () => void;
  onOpenAsset?: (assetId: number) => void;
}

const SUGGESTIONS = ["帮我搜「夜景」素材", "我的素材库是什么领域？", "看看 #1 素材"];

const TOOL_META: Record<
  string,
  { label: string; Icon: ComponentType<{ size?: number | string; className?: string }> }
> = {
  search_assets: { label: "语义检索", Icon: Search },
  get_asset_detail: { label: "素材详情", Icon: FileText },
  domain_profile: { label: "领域画像", Icon: Radar },
  generate_image: { label: "文生图入库", Icon: ImageIcon },
  transform_asset: { label: "素材处理", Icon: SlidersHorizontal },
  find_moment: { label: "片段定位", Icon: Timer },
  find_passage: { label: "片段检索", Icon: FileText },
};

function fmtTs(sec?: number): string {
  const s = Math.max(0, Math.floor(sec ?? 0));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function fmtWhen(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} 小时前`;
  return new Date(iso).toLocaleDateString("zh-CN");
}

function makeSessionId(): string {
  return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export default function ChatPanel({ onComplete, onOpenAsset }: Props) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const refreshSessions = () => {
    fetchChatSessions().then(setSessions).catch(() => undefined);
  };

  useEffect(() => {
    refreshSessions();
  }, []);

  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs, busy]);

  const pickSession = async (sid: string) => {
    if (busy || sid === sessionId) {
      setShowHistory(false);
      return;
    }
    setHistoryLoading(true);
    setShowHistory(false);
    try {
      const rows = await fetchChatMessages(sid);
      setSessionId(sid);
      setMsgs(
        rows.map((r: ChatMessageRecord) => ({
          role: r.role === "user" ? "user" : "assistant",
          text: r.content,
        }))
      );
    } catch {
      setMsgs([]);
    } finally {
      setHistoryLoading(false);
    }
  };

  const newChat = () => {
    if (busy) return;
    setSessionId("");
    setMsgs([]);
    setShowHistory(false);
    setInput("");
    inputRef.current?.focus();
  };

  const send = async (raw?: string) => {
    const text = (raw ?? input).trim();
    if (!text || busy) return;
    const sid = sessionId || makeSessionId();
    if (!sessionId) setSessionId(sid);
    setInput("");
    setMsgs((m) => [...m, { role: "user", text }]);
    setBusy(true);
    try {
      await chatStream(text, sid, (ev) => {
        if (Array.isArray(ev.steps) && ev.intent !== undefined) {
          setMsgs((m) => [
            ...m,
            { role: "plan", intent: ev.intent, steps: ev.steps, elapsed_ms: ev.elapsed_ms },
          ]);
        } else if (ev.tool) {
          setMsgs((m) => [
            ...m,
            {
              role: "trace",
              tool: ev.tool,
              ok: ev.ok,
              summary: ev.summary,
              assets: ev.assets,
              moments: ev.moments,
              labels: ev.labels,
              elapsed_ms: ev.elapsed_ms,
            },
          ]);
        } else if (ev.stage) {
          setMsgs((m) => [...m, { role: "step", text: ev.content ?? "" }]);
        } else if (ev.text && !ev.session_id) {
          setMsgs((m) => [...m, { role: "assistant", text: ev.text }]);
        }
      });
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", text: e instanceof Error ? e.message : String(e) }]);
    } finally {
      setBusy(false);
      refreshSessions();
      onComplete?.();
    }
  };

  const renderPlan = (m: Msg) => (
    <div className="trace-card plan-card">
      <div className="plan-seq">
        <span className="trace-chip intent">
          <Sparkles size={11} />
          意图：{m.intent || "chitchat"}
        </span>
        {(m.steps ?? []).map((s, i) => {
          const meta = TOOL_META[s.tool] ?? { label: s.tool, Icon: Bot };
          const Icon = meta.Icon;
          return (
            <span key={`${s.tool}-${i}`} className="plan-seq-item">
              {i > 0 && <i className="plan-arrow" aria-hidden="true" />}
              <span className="trace-chip tool">
                <Icon size={11} />
                {meta.label}
              </span>
            </span>
          );
        })}
        {m.elapsed_ms != null && <span className="trace-time">{m.elapsed_ms}ms</span>}
      </div>
    </div>
  );

  const renderTrace = (m: Msg) => {
    const meta = TOOL_META[m.tool ?? ""] ?? { label: m.tool ?? "工具", Icon: Bot };
    const Icon = meta.Icon;
    return (
      <div className={`trace-card${m.ok === false ? " failed" : ""}`}>
        <div className="trace-head">
          <span className={`trace-icon${m.ok === false ? " failed" : ""}`}>
            <Icon size={13} aria-hidden="true" />
          </span>
          <b>{meta.label}</b>
          <span className={`trace-status${m.ok === false ? " failed" : ""}`}>
            {m.ok === false ? "未成功" : "完成"}
          </span>
          {m.elapsed_ms != null && <span className="trace-time">{m.elapsed_ms}ms</span>}
        </div>
        {m.summary && <p className="trace-summary">{m.summary}</p>}
        {m.labels && m.labels.length > 0 && (
          <div className="tags trace-tags">
            {m.labels.map((l) => (
              <span key={l} className="tag label">
                {l}
              </span>
            ))}
          </div>
        )}
        {m.assets && m.assets.length > 0 && (
          <div className="trace-assets">
            {m.assets.map((a) => (
              <button
                key={a.id}
                type="button"
                className="asset-ref"
                onClick={() => onOpenAsset?.(a.id)}
                title={a.description ?? undefined}
              >
                #{a.id}
                <span>{a.name}</span>
              </button>
            ))}
          </div>
        )}
        {m.moments && m.moments.length > 0 && (
          <div className="trace-moments">
            {m.moments.map((mo, i) => (
              <button
                key={`${mo.asset_id}-${i}`}
                type="button"
                className="moment-ref"
                onClick={() => onOpenAsset?.(mo.asset_id)}
              >
                <span className="moment-time">
                  {fmtTs(mo.start)}
                  {mo.end != null ? `-${fmtTs(mo.end)}` : ""}
                </span>
                <span className="moment-text">{mo.snippet}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <section className="panel chat-panel" aria-label="素材助理对话">
      <div className="panel-head">
        <span className="chat-head-title">
          <span className="agent-avatar sm" aria-hidden="true">
            <Bot size={15} />
          </span>
          <span>
            <b>素材助理 Agent</b>
            <span className="chat-sub">能搜会做 · 轨迹可见</span>
          </span>
        </span>
        <div className="head-right">
          <span className="hint live-badge">
            <i />
            SSE
          </span>
          <button
            type="button"
            className="icon-btn sm"
            onClick={newChat}
            aria-label="开始新对话"
            title="新对话"
          >
            <Plus size={14} />
          </button>
          <button
            type="button"
            className={`icon-btn sm${showHistory ? " on" : ""}`}
            onClick={() => setShowHistory((v) => !v)}
            aria-label="历史会话"
            aria-expanded={showHistory}
            title="历史会话"
          >
            <History size={14} />
          </button>
        </div>
      </div>

      {showHistory && (
        <div className="history-panel">
          <div className="history-head">
            <b>历史会话</b>
            <button
              type="button"
              className="field-clear"
              onClick={() => setShowHistory(false)}
              aria-label="关闭历史会话"
            >
              <X size={13} />
            </button>
          </div>
          <div className="history-list">
            {sessions.length === 0 ? (
              <p className="history-empty">还没有历史会话，和助理聊一句就会出现在这里。</p>
            ) : (
              sessions.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={`history-item${s.id === sessionId ? " current" : ""}`}
                  onClick={() => void pickSession(s.id)}
                >
                  <span className="history-title">{s.title}</span>
                  <span className="history-meta">
                    {s.message_count} 条 · {fmtWhen(s.updated_at)}
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      )}

      <div
        className="chatbox"
        ref={boxRef}
        role="log"
        aria-live="polite"
        aria-label="对话记录"
      >
        {msgs.length === 0 && !busy && !historyLoading && (
          <div className="chat-welcome">
            <span className="agent-avatar lg" aria-hidden="true">
              <Bot size={20} />
            </span>
            <p>我是素材助理，每一步用了什么工具、命中哪些素材都会实时展示，点素材就能看详情。</p>
            <div className="chat-suggestions">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="chat-chip"
                  onClick={() => {
                    setInput(s);
                    inputRef.current?.focus();
                  }}
                >
                  <Sparkles size={12} />
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {msgs.map((m, i) => {
          if (m.role === "plan") return <div key={i}>{renderPlan(m)}</div>;
          if (m.role === "trace") return <div key={i}>{renderTrace(m)}</div>;
          if (m.role === "step") {
            return (
              <div key={i} className="chat-msg step">
                <span className="step-dot" aria-hidden="true" />
                <span className="step-text">{m.text}</span>
              </div>
            );
          }
          if (m.role === "user") {
            return (
              <div key={i} className="chat-msg user">
                <span className="bubble">{m.text}</span>
              </div>
            );
          }
          return (
            <div key={i} className="chat-msg assistant">
              <span className="agent-avatar sm" aria-hidden="true">
                <Bot size={14} />
              </span>
              <span className="bubble">{m.text}</span>
            </div>
          );
        })}
        {busy && (
          <div className="chat-msg assistant">
            <span className="agent-avatar sm" aria-hidden="true">
              <Bot size={14} />
            </span>
            <span className="bubble typing" aria-label="助理正在思考">
              <i />
              <i />
              <i />
            </span>
          </div>
        )}
        {historyLoading && <div className="empty">正在加载历史消息…</div>}
      </div>

      <div className="chat-composer">
        <input
          ref={inputRef}
          className="composer-input"
          type="text"
          placeholder="和素材助理对话…"
          aria-label="消息内容"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void send();
          }}
        />
        <button
          type="button"
          className="btn primary composer-send"
          onClick={() => void send()}
          disabled={busy || !input.trim()}
          aria-label="发送消息"
        >
          <Send size={15} />
        </button>
      </div>
    </section>
  );
}
