import { useState } from "react";
import { api } from "../api";

// Sign-in screen (auth.mode "password"). The backend checks the credentials and sets an
// HttpOnly session cookie; nothing about the account is kept in the browser.
export function Login({ onSuccess }: { onSuccess: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) { setError("Enter your username and password."); return; }
    setBusy(true);
    try {
      const r = await api.login(email.trim(), password);
      if (r.ok) { setError(null); onSuccess(); return; }
      setError(r.detail || "Incorrect username or password. Please try again.");
    } catch {
      setError("The sign-in service is unreachable — please retry in a moment.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-shell">
      <form className="login-card" onSubmit={submit}>
        <img src="/sympany-logo.svg" alt="Sympany. All the insurance you need." className="login-logo" />
        <h1 className="login-title">Social media listening</h1>
        <p className="login-sub">Sign in with your Sympany console account.</p>

        <label className="login-label" htmlFor="login-email">Username</label>
        <input
          id="login-email"
          className="login-input"
          type="text"
          value={email}
          onChange={(e) => { setEmail(e.target.value); setError(null); }}
          placeholder="Your username"
          autoComplete="username"
          autoFocus
        />

        <label className="login-label" htmlFor="login-password">Password</label>
        <div className="login-pw">
          <input
            id="login-password"
            className="login-input"
            type={show ? "text" : "password"}
            value={password}
            onChange={(e) => { setPassword(e.target.value); setError(null); }}
            placeholder="Enter your password"
            autoComplete="current-password"
          />
          <button type="button" className="login-eye" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"}>
            {show ? "Hide" : "Show"}
          </button>
        </div>

        {error && <div className="login-error">{error}</div>}

        <button className="btn login-btn" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>

        <div className="login-foot">For authorised Sympany staff only</div>
      </form>
    </div>
  );
}
