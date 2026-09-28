import { useState, type FormEvent } from "react";
import { Field } from "../../components/Field";
import { Navigate, useLocation, useNavigate, type Location } from "react-router-dom";
import { ApiError } from "../../api/http";
import { useAuth } from "./auth-context";

export function LoginPage() {
  const { token, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const from = (location.state as { from?: Location } | null)?.from;
  const target = from ? `${from.pathname}${from.search}` : "/";

  if (token) return <Navigate to={target} replace />;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      navigate(target, { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Wrong email or password."
          : err instanceof Error
            ? err.message
            : "Login failed.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login">
      <form className="login-card" onSubmit={handleSubmit} noValidate>
        <h1>Task Manager</h1>
        <p className="muted">Sign in to see and manage your tasks.</p>
        <Field label="Email">
          {(id) => (
            <input
              id={id}
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          )}
        </Field>
        <Field label="Password">
          {(id) => (
            <input
              id={id}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          )}
        </Field>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button
          className="button primary"
          type="submit"
          disabled={submitting || !email.trim() || !password}
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
        <p className="hint">
          Demo users: <code>ana@example.com</code>, <code>bruno@example.com</code>,{" "}
          <code>carla@example.com</code> — password <code>demo-password-2026</code>
        </p>
      </form>
    </main>
  );
}
