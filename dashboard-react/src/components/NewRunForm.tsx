import { useEffect, useState } from "react";
import { ApiError, getCurrentRun, startRun } from "../api/client";
import { useRunDispatch, useRunState } from "../state/RunContext";

export function NewRunForm() {
  const { isRunActive: isRunning } = useRunState();
  const dispatch = useRunDispatch();

  const [url, setUrl] = useState("");
  const [focusHint, setFocusHint] = useState("");
  const [prdPath, setPrdPath] = useState("");
  const [showCredentials, setShowCredentials] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const [message, setMessage] = useState<{ kind: "info" | "error"; text: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    getCurrentRun()
      .then((current) => dispatch({ kind: "set_run_active", active: current?.status === "running" }))
      .catch(() => {
        /* server not reachable yet; submit will surface the real error */
      });
  }, [dispatch]);

  function isValidUrl(value: string): boolean {
    try {
      const parsed = new URL(value);
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch {
      return false;
    }
  }

  const urlValid = url.length === 0 || isValidUrl(url);
  const credentialsValid = !username || password.length > 0;
  const canSubmit = url.length > 0 && isValidUrl(url) && credentialsValid && !isRunning && !submitting;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setMessage(null);
    try {
      await startRun({
        url,
        prd_path: prdPath || null,
        focus_hint: focusHint || null,
        credentials: username ? { username, password } : null,
      });
      dispatch({ kind: "set_run_active", active: true });
      setMessage({ kind: "info", text: "Run started — watch the feed below." });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setMessage({ kind: "error", text: "A run is already in progress — wait for it to finish." });
        dispatch({ kind: "set_run_active", active: true });
      } else {
        setMessage({ kind: "error", text: err instanceof Error ? err.message : "Failed to start run." });
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mb-3.5 rounded-lg border border-slate-200 bg-white p-3.25 px-3.75">
      <h2 className="m-0 mb-2 text-[10.5px] font-bold tracking-wide text-slate-400 uppercase">New Run</h2>

      <label className="mb-1 block text-[11.5px] font-medium text-slate-600" htmlFor="run-url">
        Target URL
      </label>
      <input
        id="run-url"
        type="url"
        required
        placeholder="https://example.com"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        className={`mb-2 w-full rounded-md border px-2.5 py-1.5 text-[12.5px] outline-none focus:border-purple ${
          urlValid ? "border-slate-200" : "border-red"
        }`}
      />

      <label className="mb-1 block text-[11.5px] font-medium text-slate-600" htmlFor="run-focus">
        Focus hint <span className="font-normal text-slate-400">(optional)</span>
      </label>
      <textarea
        id="run-focus"
        rows={2}
        placeholder="e.g. prioritize the checkout flow"
        value={focusHint}
        onChange={(e) => setFocusHint(e.target.value)}
        className="mb-2 w-full resize-none rounded-md border border-slate-200 px-2.5 py-1.5 text-[12.5px] outline-none focus:border-purple"
      />

      <label className="mb-1 block text-[11.5px] font-medium text-slate-600" htmlFor="run-prd">
        PRD path <span className="font-normal text-slate-400">(optional, server-side path)</span>
      </label>
      <input
        id="run-prd"
        type="text"
        placeholder="prd.md"
        value={prdPath}
        onChange={(e) => setPrdPath(e.target.value)}
        className="mb-2 w-full rounded-md border border-slate-200 px-2.5 py-1.5 font-mono text-[12px] outline-none focus:border-purple"
      />

      <button
        type="button"
        onClick={() => setShowCredentials((v) => !v)}
        className="mb-2 text-[11.5px] font-medium text-purple"
      >
        {showCredentials ? "− Hide credentials" : "+ Add credentials (optional)"}
      </button>

      {showCredentials ? (
        <div className="mb-2 space-y-2 rounded-md bg-slate-50 p-2.5">
          <input
            type="text"
            placeholder="username / email"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[12.5px] outline-none focus:border-purple"
          />
          <input
            type="password"
            placeholder="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[12.5px] outline-none focus:border-purple"
          />
          {!credentialsValid ? <div className="text-[11px] text-red">Password required if username is set.</div> : null}
        </div>
      ) : null}

      <button
        type="submit"
        disabled={!canSubmit}
        className="w-full rounded-md bg-purple py-2 text-[12.5px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
      >
        {isRunning ? "Run in progress…" : submitting ? "Starting…" : "Start Run"}
      </button>

      {message ? (
        <div className={`mt-2 text-[11.5px] ${message.kind === "error" ? "text-red" : "text-green"}`}>
          {message.text}
        </div>
      ) : null}
    </form>
  );
}
