import { useEffect, useRef, useState } from "react";
import { Bot, Send, Sparkles } from "lucide-react";
import { chatStream } from "../api";

interface Msg {
  role: "user" | "assistant" | "step";
  text: string;
}

interface Props {
  onComplete?: () => void;
}

const SUGGESTIONS = ["帮我搜「夜景」素材", "我的素材库是什么领域？", "看看 #1 素材"];

export default function ChatPanel({ onComplete }: Props) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs, busy]);

  const send = async (raw?: string) => {
    const text = (raw ?? input).trim();
    if (!text || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", text }]);
    setBusy(true);
    try {
      await chatStream(text, "web", (ev) => {
        if (ev.stage) {
          const content = ev.content ?? "";
          setMsgs((m) => [...m, { role: "step", text: content }]);
        } else if (ev.text) {
          setMsgs((m) => [...m, { role: "assistant", text: ev.text ?? "" }]);
        }
      });
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", text: e instanceof Error ? e.message : String(e) }]);
    } finally {
      setBusy(false);
      onComplete?.();
    }
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
            <span className="chat-sub">能搜会做 · 逐步可见</span>
          </span>
        </span>
        <span className="hint live-badge">
          <i />
          SSE
        </span>
      </div>

      <div className="chatbox" ref={boxRef} role="log" aria-live="polite" aria-label="对话记录">
        {msgs.length === 0 && !busy && (
          <div className="chat-welcome">
            <span className="agent-avatar lg" aria-hidden="true">
              <Bot size={20} />
            </span>
            <p>我是素材助理，能检索素材、生成素材、处理素材，也能总结你的素材库。</p>
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
