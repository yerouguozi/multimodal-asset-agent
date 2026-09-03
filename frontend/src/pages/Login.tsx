import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, KeyRound, Loader2, LogIn, UserPlus } from "lucide-react";
import { authLogin, authRegister } from "../api";

export default function Login() {
  const nav = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || password.length < 4) {
      setError("用户名不能为空，密码至少 4 位");
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (mode === "register") await authRegister(username.trim(), password);
      else await authLogin(username.trim(), password);
      nav("/app", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message.replace(/^HTTP \d+: /, "") : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <Link to="/" className="login-back">
        <ArrowLeft size={15} />
        返回介绍页
      </Link>
      <div className="login-card">
        <span className="login-logo">
          <KeyRound size={22} />
        </span>
        <h1>{mode === "login" ? "登录工作台" : "创建账号"}</h1>
        <p className="login-sub">
          {mode === "login"
            ? "登录后，素材库、检索与 Agent 会话都归你的账号所有。"
            : "注册后立刻获得独立的素材空间，数据按用户隔离。"}
        </p>
        <form onSubmit={(e) => void submit(e)}>
          <label>
            用户名
            <input
              className="text-input"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="例如 yerouguozi"
            />
          </label>
          <label>
            密码
            <input
              className="text-input"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="至少 4 位"
            />
          </label>
          {error && <p className="login-error">{error}</p>}
          <button type="submit" className="btn primary login-submit" disabled={busy}>
            {busy ? <Loader2 className="spin" size={16} /> : mode === "login" ? <LogIn size={16} /> : <UserPlus size={16} />}
            {mode === "login" ? "登录并进入素材库" : "注册并进入素材库"}
          </button>
        </form>
        <button
          type="button"
          className="login-switch"
          onClick={() => {
            setMode((m) => (m === "login" ? "register" : "login"));
            setError("");
          }}
        >
          {mode === "login" ? "还没有账号？注册一个" : "已有账号？去登录"}
        </button>
      </div>
    </div>
  );
}
