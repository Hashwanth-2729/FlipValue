import { useState, type ReactNode } from "react";

import { account, ApiError } from "../api";
import { useAsync } from "../hooks";
import type { Account } from "../types";
import { ErrorState, Loading, Notice } from "./ui";

/** Loads the signed-in account; shows sign-in / create-account when there is none. */
export function AccountGate({ purpose, children }: {
  purpose: string;
  children: (me: Account, signOut: () => void) => ReactNode;
}) {
  const me = useAsync(() => account.me(), []);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  if (me.loading) return <Loading label="Checking your session" lines={2} />;
  if (me.data) {
    return <>{children(me.data, () => void account.logout().finally(me.reload))}</>;
  }
  if (me.error && me.error.status !== 401) return <ErrorState error={me.error} onRetry={me.reload} what="your account" />;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (mode === "login" ? account.login(email, password) : account.register(email, password));
      setPassword("");
      me.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, "unexpected", String(err)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card narrow auth" onSubmit={submit} aria-labelledby="auth-h">
      <h2 id="auth-h">{mode === "login" ? "Sign in" : "Create an account"}</h2>
      <p className="muted">{purpose}</p>
      {error && <Notice tone="danger" title={error.message} />}
      <div className="field">
        <label htmlFor="auth-email">Email</label>
        <input id="auth-email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="auth-password">Password</label>
        <input id="auth-password" type="password" required minLength={mode === "register" ? 10 : 1}
          autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} />
        {mode === "register" && <span className="hint">At least 10 characters.</span>}
      </div>
      <div className="row">
        <button type="submit" className="btn primary" disabled={busy}>{mode === "login" ? "Sign in" : "Create account"}</button>
        <button type="button" className="btn link" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}>
          {mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
        </button>
      </div>
      <p className="small muted">
        Valuing a phone never needs an account. FlipValue stores your email and a scrypt hash of your password; email
        verification is not available yet.
      </p>
    </form>
  );
}
