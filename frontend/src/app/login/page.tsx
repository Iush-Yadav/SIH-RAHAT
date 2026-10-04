"use client";

import LogisticsScene from "@/components/LogisticsScene";
import { useEffect, useState } from "react";
import { listRoles, login } from "@/lib/api";
import type { Roles } from "@/lib/types";
import { useSession } from "@/components/Shell";

const PRESETS: { user: string; blurb: string }[] = [
  { user: "commander", blurb: "Overview, simulation and briefing access." },
  { user: "logistics", blurb: "Forecast, planning, stock. No administration." },
  { user: "quartermaster", blurb: "Stock levels and IoT sensor estate." },
  { user: "admin", blurb: "User accounts, roles and the audit trail." },
];

export default function LoginPage() {
  const { login: signIn } = useSession();
  const [roles, setRoles] = useState<Roles>({});
  const [username, setUsername] = useState("commander");
  const [password, setPassword] = useState("commander");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listRoles()
      .then(setRoles)
      .catch(() => setRoles({}));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = await login(username.trim(), password);
      signIn(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const pick = (u: string) => {
    setUsername(u);
    setPassword(u);
    setError(null);
  };

  return (
    <div className="login-page">
      <header className="masthead"><div className="brand"><span className="brand-mark">r<span>↗</span></span><span>RAHAT<small>THE SUPPLY INTELLIGENCE PROJECT</small></span></div><div className="masthead-meta"><span>SMART INDIA HACKATHON 2026</span><span className="demo-stamp">PS / 26251</span></div></header>
      <div className="login-grid">
        <section className="login-intro">
          <div className="label">01 / The connected supply chain</div>
          <h1>Every supply.<br />A clearer <em>picture.</em></h1>
          <p>A shared workspace for inventory, forecasts and evidence. See the connections. Understand the numbers. Keep people in control.</p>
          <div className="login-scene"><LogisticsScene /><span className="art-caption">RAHAT FIELD NOTES / ORIGINAL ILLUSTRATION</span></div>
          <div className="login-note"><div><b>01—04</b>Connected modules</div><div><b>Local first</b>No external map tiles</div><div><b>Demo data</b>Clearly labelled evidence</div></div>
        </section>

        {/* Right: sign in */}
        <form onSubmit={submit} className="panel login-form">
          <div className="label">02 / Enter the workspace</div>
          <h2 className="mt-2 text-xl font-semibold">Welcome to RAHAT.</h2>
          <p className="mt-1.5 text-[12.5px] text-dim">
            Role-based access control. Demo passwords equal the username — e.g.{" "}
            <span className="mono text-cyan">commander / commander</span>.
          </p>

          <div className="mt-5 grid grid-cols-2 gap-2">
            {PRESETS.map((p) => (
              <button
                key={p.user}
                type="button"
                onClick={() => pick(p.user)}
                aria-pressed={username === p.user}
                className={`role-picker border px-3 py-2.5 text-left transition-colors ${
                  username === p.user
                    ? "border-cyan bg-cyan/10"
                    : "border-line hover:border-line2 hover:bg-panel2"
                }`}
              >
                <div className="mono text-[12px] font-semibold text-fg">
                  {p.user}
                </div>
                <div className="mt-0.5 text-[11px] leading-tight text-dim">
                  {p.blurb}
                </div>
              </button>
            ))}
          </div>

          <div className="mt-5 space-y-3">
            <label className="block">
              <span className="label">Username</span>
              <input
                required
                className="input mt-1"
                value={username}
                autoComplete="username"
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="label">Password</span>
              <input
                required
                className="input mt-1"
                type="password"
                value={password}
                autoComplete="current-password"
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
          </div>

          {error && (
            <div role="alert"
            className="mono mt-4 border border-red/40 bg-red/10 px-3 py-2 text-[12px] text-red">
              {error}
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary mt-5 w-full justify-center py-2.5"
            disabled={busy}
          >
            {busy ? "authenticating…" : "Open workspace →"}
          </button>

          {Object.keys(roles).length > 0 && (
            <div className="mt-5 border-t border-line pt-4">
              <div className="label mb-2">Roles &amp; permissions</div>
              <div className="space-y-1.5">
                {Object.entries(roles).map(([slug, r]) => (
                  <div key={slug} className="flex flex-wrap items-baseline gap-2">
                    <span className="mono w-[150px] shrink-0 text-[11.5px] text-cyan">
                      {r.label}
                    </span>
                    <span className="text-[11.5px] leading-snug text-dim">
                      {r.can.join(" · ")}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </form>
      </div>
    </div>
  );
}
