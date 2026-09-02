import { useEffect, useRef, useState } from "react";
import { chatStream } from "../api";

interface Msg {
  role: "user" | "assistant" | "step";
  text: string;
}

interface Props {
  onComplete?: () => void;
}

export default function ChatPanel({ onComplete }: Props) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    boxRef.current?.scrollTo(0, boxRef.current.scrollHeight);
  }, [msgs]);

  const send = async () => {
    const text = input.trim();
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
          const text = ev.text;
          setMsgs((m) => [...m, { role: "assistant", text }]);
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
    <section className="panel chat-panel">
      <div className="panel-head">
        <b>素材助理 Agent</b>
        <span className="hint">SSE 逐步推送</span>
      </div>
      <div className="chatbox" ref={boxRef}>
        {msgs.length === 0 && <div className="empty">问我：帮我搜夜景 / 我的素材库是什么领域 / 看看 #1</div>}
        {msgs.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            {m.role === "user" ? "你：" : m.role === "assistant" ? "AI：" : "→ "}
            {m.text}
          </div>
        ))}
        {busy && <div className="chat-msg step">→ 思考中…</div>}
      </div>
      <div className="row">
        <input
          className="text-input grow"
          placeholder="和素材助理对话…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void send();
          }}
        />
        <button className="btn primary" onClick={() => void send()} disabled={busy}>
          发送
        </button>
      </div>
    </section>
  );
}
