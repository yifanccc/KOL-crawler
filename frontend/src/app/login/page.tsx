"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Activity, ArrowRight, LockKeyhole, RadioTower } from "lucide-react";
import { login } from "@/lib/api";

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(username, password);
      const target = searchParams.get("next") || "/";
      router.replace(target.startsWith("/") ? target : "/");
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-frame">
        <div className="auth-brand">
          <span><Activity size={22} aria-hidden="true" /></span>
          <div><strong>KOL Intel</strong><small>Financial signal terminal</small></div>
        </div>
        <div className="auth-status"><RadioTower size={15} aria-hidden="true" /> 私有情报节点</div>
        <div className="auth-copy">
          <p className="terminal-label">Secure Access</p>
          <h1>进入金融 KOL 情报流</h1>
          <p>登录后查看分钟级观点、标的、标签与推送状态。</p>
        </div>
        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            <span>用户名</span>
            <input autoComplete="username" autoFocus required value={username} onChange={(event) => setUsername(event.target.value)} />
          </label>
          <label>
            <span>密码</span>
            <div className="auth-password">
              <LockKeyhole size={16} aria-hidden="true" />
              <input autoComplete="current-password" required type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
            </div>
          </label>
          {error ? <p className="auth-error" role="alert">{error}</p> : null}
          <button type="submit" disabled={submitting}>
            {submitting ? "验证中" : "登录"}<ArrowRight size={17} aria-hidden="true" />
          </button>
        </form>
      </section>
    </main>
  );
}
