import React, { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { todayEt } from "./dates";

type Budget = { key_count: number; known_keys: number; remaining: number; spent_today: number; daily_budget: number };

// Deliberately absent from navigation. The backend always requires authentication.
export function OddsAdmin() {
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState("");
  const [feed, setFeed] = useState("moneylines");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [budget, setBudget] = useState<Budget | null>(null);
  const [params] = useSearchParams();
  const date = params.get("date") || todayEt();
  const close = () => { setOpen(false); setToken(""); setMessage(""); setBudget(null); };
  useEffect(() => { if (open) dialog.current?.showModal(); }, [open]);
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.altKey && event.shiftKey && event.code === "KeyO") {
        event.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, []);
  const request = async (refresh: boolean) => {
    setBusy(true); setMessage("");
    try {
      const query = new URLSearchParams({ date, feed });
      const response = await fetch(`/api/admin/odds/${refresh ? `refresh?${query}` : "budget"}`, {
        method: refresh ? "POST" : "GET",
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Odds request failed");
      setBudget(refresh ? body.budget : body);
      if (refresh) {
        const errors = new Set<string>();
        for (const [key, result] of Object.entries(body) as [string, any][]) {
          if (key === "budget") continue;
          if (result.error) errors.add(result.error);
          for (const game of Object.values(result.games || {}) as any[]) {
            if (game.error) errors.add(game.error);
          }
        }
        setMessage(errors.size ? [...errors].join("; ") : "Refresh checked. Recent cache and cooldowns still apply. Reload the page to view updated odds.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Odds request failed");
    } finally { setBusy(false); }
  };
  if (!open) return null;
  return <dialog ref={dialog} className="odds-admin" aria-labelledby="odds-admin-title" onCancel={close}>
    <h2 id="odds-admin-title">Odds refresh</h2>
    <p>{date} · Uses API credits. Repeated refreshes are limited.</p>
    <label>Admin token <input autoFocus type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} /></label>
    <label>Feed <select aria-label="Feed" value={feed} onChange={e => setFeed(e.target.value)}>
      <option value="moneylines">Moneylines + totals</option>
      <option value="props">Player props (slate)</option>
      <option value="first-period">First-period odds</option>
      <option value="all">All three feeds</option>
    </select></label>
    <div className="refresh-actions">
      <button className="refresh-button" disabled={busy || !token} onClick={() => void request(false)}>Check budget</button>
      <button className="refresh-button" disabled={busy || !token} onClick={() => void request(true)}>{busy ? "Working…" : "Refresh odds"}</button>
      <button className="refresh-button" disabled={busy} onClick={close}>Close</button>
    </div>
    {budget && <p>{budget.known_keys}/{budget.key_count} keys checked · {budget.remaining} known credits remaining · {budget.spent_today}/{budget.daily_budget} credits used today (UTC)</p>}
    {message && <p role="status">{message}</p>}
  </dialog>;
}
