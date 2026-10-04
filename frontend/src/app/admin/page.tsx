"use client";

import { useState } from "react";
import {
  Badge,
  Empty,
  ErrorBox,
  Loading,
  Panel,
  Stat,
  Table,
  Td,
  nf,
  pct,
  useLoad,
} from "@/components/ui";
import { useSession } from "@/components/Shell";
import { get, post } from "@/lib/api";
import type { AdminUser, AuditEntry, Health, Roles } from "@/lib/types";

export default function AdminPage() {
  const { user } = useSession();
  const users = useLoad(() => get<{ items: AdminUser[] }>("/admin/users"), []);
  const roles = useLoad(() => get<Roles>("/auth/roles"), []);
  const audit = useLoad(() => get<{ items: AuditEntry[] }>("/admin/audit?limit=120"), []);
  const health = useLoad(() => get<Health>("/health"), []);

  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const canRetrain = user?.perms.includes("retrain") ?? false;

  const retrain = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const r = await post<{ ok: boolean; elapsed_ms: number }>("/admin/retrain", {});
      setMsg(`Model rebuilt in ${nf(r.elapsed_ms, 0)} ms — leaderboard refreshed.`);
      health.reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const model = health.data?.model;
  const entries = (audit.data?.items ?? []).filter(
    (a) =>
      !filter ||
      a.username.includes(filter) ||
      a.action.includes(filter) ||
      a.entity.includes(filter),
  );

  return (
    <div className="space-y-5">
      <Head />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Registered users" value={nf(users.data?.items.length ?? 0, 0)} sub="PBKDF2-SHA256 · 200k rounds" />
        <Stat label="Roles" value={nf(Object.keys(roles.data ?? {}).length, 0)} accent="text-cyan" sub="permission-checked at the router" />
        <Stat
          label="Model status"
          value={model?.status ?? "…"}
          accent={model?.status === "ready" ? "text-green" : "text-amber"}
          sub={model ? `${nf(model.series, 0)} series · ${nf(model.rows, 0)} rows` : "—"}
        />
        <Stat
          label="Audit entries"
          value={nf(audit.data?.items.length ?? 0, 0)}
          accent="text-violet"
          sub={`${health.data?.telemetry_ticks ?? 0} telemetry ticks`}
        />
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="User accounts" bodyClass="p-0">
          {users.loading ? (
            <Loading />
          ) : (
            <Table head={["Username", "Display name", "Role", "Created", "Override"]}>
              {users.data?.items.map((u) => (
                <tr key={u.username} className="border-b border-line/60 hover:bg-panel2/60">
                  <Td mono className="text-cyan">{u.username}</Td>
                  <Td>{u.display_name}</Td>
                  <Td mono className="text-muted">{u.role}</Td>
                  <Td mono className="text-dim">{u.created_at.slice(0, 10)}</Td>
                  <Td>
                    <Badge tone={u.can_override ? "warn" : "neutral"}>
                      {u.can_override ? "yes" : "no"}
                    </Badge>
                  </Td>
                </tr>
              ))}
            </Table>
          )}
          <div className="mono border-t border-line px-4 py-2.5 text-[11.5px] text-dim">
            demo credentials: password equals username. Production swaps the PBKDF2
            store for the unit&apos;s identity provider; JWT is HS256 with an
            env-provided secret.
          </div>
        </Panel>

        <Panel title="Roles &amp; permissions" bodyClass="p-0">
          {roles.loading ? (
            <Loading />
          ) : (
            <Table head={["Role", "Label", "Permissions"]}>
              {Object.entries(roles.data ?? {}).map(([slug, r]) => (
                <tr key={slug} className="border-b border-line/60">
                  <Td mono className="text-cyan">{slug}</Td>
                  <Td>{r.label}</Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      {r.can.map((p) => (
                        <span
                          key={p}
                          className="mono rounded-sm border border-line2 px-1.5 py-0.5 text-[10.5px] text-muted"
                        >
                          {p}
                        </span>
                      ))}
                    </div>
                  </Td>
                </tr>
              ))}
            </Table>
          )}
          <div className="mono border-t border-line px-4 py-2.5 text-[11.5px] text-dim">
            Signed in as <span className="text-cyan">{user?.username}</span> ·{" "}
            <span className="text-fg">{user?.role_label}</span> ·{" "}
            {user?.perms.join(", ")}
          </div>
        </Panel>
      </div>

      <Panel
        title="Model operations"
        right={
          <button
            className="btn btn-primary"
            onClick={retrain}
            disabled={!canRetrain || busy}
          >
            {busy ? "retraining…" : "↻ retrain all models"}
          </button>
        }
        bodyClass="p-4"
      >
        {msg && (
          <div className="mono mb-3 border border-green/40 bg-green/8 px-3 py-2 text-[12px] text-green">
            {msg}
          </div>
        )}
        {err && <div className="mono mb-3 border border-red/40 bg-red/10 px-3 py-2 text-[12px] text-red">{err}</div>}
        {!canRetrain && (
          <div className="mono mb-3 border border-amber/40 bg-amber/8 px-3 py-2 text-[12px] text-amber">
            Your role cannot retrain — sign in as <span className="text-fg">admin</span>.
          </div>
        )}

        <div className="grid gap-4 text-[12.5px] md:grid-cols-4">
          <div>
            <div className="label mb-1">Training set</div>
            <div className="mono text-fg">
              {nf(model?.rows ?? 0, 0)} rows · {nf(model?.series ?? 0, 0)} series ·{" "}
              {nf(model?.features ?? 0, 0)} features
            </div>
          </div>
          <div>
            <div className="label mb-1">Wall time</div>
            <div className="mono text-fg">
              train {nf(model?.train_ms ?? 0, 0)} ms · backtest {nf(model?.backtest_ms ?? 0, 0)} ms
            </div>
          </div>
          <div>
            <div className="label mb-1">Last trained</div>
            <div className="mono text-fg">
              {model?.trained_at
                ? new Date(model.trained_at * 1000).toISOString().replace("T", " ").slice(0, 19) + "Z"
                : "—"}
            </div>
          </div>
          <div>
            <div className="label mb-1">Champion</div>
            <div className="mono text-cyan">
              {model?.leaderboard?.find((l) => l.is_champion)?.model ?? "—"} · MAPE{" "}
              {pct(model?.leaderboard?.find((l) => l.is_champion)?.mape ?? 0, 2)}
            </div>
          </div>
        </div>

        {model?.error && (
          <div className="mono mt-3 border border-red/40 bg-red/10 px-3 py-2 text-[12px] text-red">
            {model.error}
          </div>
        )}

        <div className="mt-4 overflow-x-auto border-t border-line pt-3">
          <Table head={["Model", "MAPE", "MAE", "MASE", "Pinball", "Folds", "Champion"]}>
            {(model?.leaderboard ?? []).map((l) => (
              <tr key={l.model} className="border-b border-line/60">
                <Td mono className="text-fg">{l.model}</Td>
                <Td mono>{nf(l.mape, 2)}%</Td>
                <Td mono className="text-muted">{nf(l.mae, 1)}</Td>
                <Td mono className={l.mase < 1 ? "text-green" : "text-amber"}>{nf(l.mase, 3)}</Td>
                <Td mono className="text-muted">{nf(l.pinball, 1)}</Td>
                <Td mono className="text-dim">{l.folds}</Td>
                <Td>{l.is_champion ? <Badge tone="good">★</Badge> : null}</Td>
              </tr>
            ))}
          </Table>
        </div>
      </Panel>

      <Panel
        title="Audit trail"
        right={
          <input
            className="input w-56 py-1"
            placeholder="filter user / action / entity"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        }
        bodyClass="p-0"
      >
        {audit.loading ? (
          <Loading />
        ) : entries.length === 0 ? (
          <Empty message="no audit entries match" />
        ) : (
          <Table head={["ID", "Timestamp", "User", "Role", "Action", "Entity", "Detail"]}>
            {entries.slice(0, 60).map((a) => (
              <tr key={a.id} className="border-b border-line/60 hover:bg-panel2/60">
                <Td mono className="text-dim">{a.id}</Td>
                <Td mono className="text-muted">{a.ts.slice(0, 19).replace("T", " ")}</Td>
                <Td mono className="text-cyan">{a.username}</Td>
                <Td mono className="text-muted">{a.role}</Td>
                <Td mono className="text-fg">{a.action}</Td>
                <Td mono className="text-muted">{a.entity}</Td>
                <Td mono className="text-dim">
                  {a.detail && Object.keys(a.detail).length
                    ? JSON.stringify(a.detail)
                    : "—"}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Panel>

      {health.error && <ErrorBox message={health.error} onRetry={health.reload} />}
    </div>
  );
}

function Head() {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4">
      <div>
        <div className="label">Administration · accountability</div>
        <h1 className="mt-1.5 text-2xl font-bold tracking-tight">
          Admin <span className="text-cyan">/ users, models, audit</span>
        </h1>
        <p className="mt-1 max-w-3xl text-[13px] text-muted">
          Role-based access control, model retraining and a tamper-evident trail of
          every login, plan, simulation and acknowledgement.
        </p>
      </div>
      <Badge tone="info">governance</Badge>
    </div>
  );
}
