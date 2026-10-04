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
  inr,
  nf,
  pct,
  useLoad,
} from "@/components/ui";
import { API_BASE, get, getToken } from "@/lib/api";
import type {
  AuditEntry,
  Kpis,
  Leaderboard,
  Meta,
  SimSummary,
} from "@/lib/types";

export default function ReportsPage() {
  const kpis = useLoad(() => get<Kpis>("/kpis"), []);
  const meta = useLoad(() => get<Meta>("/meta"), []);
  const history = useLoad(() => get<{ items: SimSummary[] }>("/simulations"), []);
  const board = useLoad(() => get<Leaderboard>("/forecast/leaderboard"), []);
  const audit = useLoad(() => get<{ items: AuditEntry[] }>("/admin/audit?limit=20"), []);

  const [active, setActive] = useState<number | null>(null);
  const [briefing, setBriefing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const open = async (id: number) => {
    setBusy(true);
    setErr(null);
    setActive(id);
    try {
      const r = await fetch(`${API_BASE}/simulations/${id}/briefing`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!r.ok) throw new Error(`briefing fetch failed (${r.status})`);
      setBriefing(await r.text());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBriefing(null);
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!briefing) return;
    try {
      await navigator.clipboard.writeText(briefing);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setErr("clipboard blocked by the browser");
    }
  };

  const download = () => {
    if (!briefing || active == null) return;
    const url = URL.createObjectURL(new Blob([briefing], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `RAHAT-BRIEFING-${active}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const champion = board.data?.leaderboard?.find((l) => l.is_champion);

  return (
    <div className="space-y-5">
      <Head onPrint={() => window.print()} />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
        <Stat label="Units at risk" value={`${kpis.data?.units_at_risk ?? 0} / ${kpis.data?.units_total ?? 6}`} accent={(kpis.data?.units_at_risk ?? 0) ? "text-red" : "text-green"} />
        <Stat label="Fill rate" value={pct(kpis.data?.fill_rate_pct ?? 0)} accent="text-cyan" />
        <Stat label="Network efficiency" value={nf(kpis.data?.network_efficiency_index ?? 0, 1)} accent="text-cyan" />
        <Stat label="Open alerts" value={nf(kpis.data?.alerts_open ?? 0, 0)} accent="text-amber" />
        <Stat label="Convoys moving" value={`${kpis.data?.convoys_active ?? 0}/${kpis.data?.convoys_total ?? 0}`} accent="text-green" />
        <Stat label="Simulations run" value={nf(history.data?.items.length ?? 0, 0)} accent="text-violet" />
      </div>

      <div className="grid gap-5 xl:grid-cols-[1fr_1.15fr]">
        <Panel
          title="Simulation archive"
          right={<Badge tone="neutral">briefings are auditable</Badge>}
          bodyClass="p-0"
        >
          {history.loading ? (
            <Loading />
          ) : (history.data?.items.length ?? 0) === 0 ? (
            <Empty message="no simulations yet — run one in Mission Sim" />
          ) : (
            <Table head={["ID", "Scenario", "Fill Δ", "Cost Δ", "Run by", "Briefing"]}>
              {history.data?.items.map((r) => {
                const d = r.result?.delta;
                return (
                  <tr
                    key={r.id}
                    className={`border-b border-line/60 hover:bg-panel2/60 ${
                      active === r.id ? "bg-cyan/8" : ""
                    }`}
                  >
                    <Td mono className="text-dim">#{r.id}</Td>
                    <Td mono className="text-cyan">{r.label}</Td>
                    <Td mono className={(d?.fill_rate_pct ?? 0) >= 0 ? "text-green" : "text-red"}>
                      {(d?.fill_rate_pct ?? 0) >= 0 ? "+" : ""}
                      {d?.fill_rate_pct ?? 0} pts
                    </Td>
                    <Td mono className={(d?.cost_inr ?? 0) <= 0 ? "text-green" : "text-amber"}>
                      {d ? inr(d.cost_inr) : "—"}
                    </Td>
                    <Td mono className="text-muted">{r.username}</Td>
                    <Td>
                      <button className="btn py-0.5" onClick={() => void open(r.id)}>
                        {active === r.id && busy ? "…" : "open"}
                      </button>
                    </Td>
                  </tr>
                );
              })}
            </Table>
          )}
        </Panel>

        <Panel
          title={active ? `Briefing note · simulation #${active}` : "Briefing note"}
          right={
            <div className="flex gap-2">
              <button className="btn py-0.5" onClick={copy} disabled={!briefing}>
                {copied ? "✓ copied" : "copy"}
              </button>
              <button className="btn py-0.5" onClick={download} disabled={!briefing}>
                ↓ save
              </button>
            </div>
          }
          bodyClass="p-0"
        >
          {err && <div className="p-4"><ErrorBox message={err} /></div>}
          {busy && <div className="p-4"><Loading label="rendering briefing" /></div>}
          {!busy && !briefing && (
            <Empty message="select a simulation to render its commander's briefing note" />
          )}
          {briefing && (
            <pre className="mono max-h-[520px] overflow-auto px-4 py-3 text-[11.5px] leading-relaxed whitespace-pre-wrap text-muted">
              {briefing}
            </pre>
          )}
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <Panel title="Model card" right={<Badge tone="good">{champion?.model ?? "—"}</Badge>} bodyClass="p-4">
          {board.loading ? (
            <Loading />
          ) : (
            <div className="space-y-2 text-[12.5px] leading-relaxed">
              <Row k="Champion" v={champion?.model ?? "—"} />
              <Row k="MAPE" v={pct(champion?.mape ?? 0, 2)} />
              <Row k="MASE" v={nf(champion?.mase ?? 0, 3)} />
              <Row k="Pinball loss" v={nf(champion?.pinball ?? 0, 1)} />
              <Row k="Folds" v={nf(champion?.folds ?? 0, 0)} />
              <Row k="Backtest" v={board.data?.method ?? "—"} />
              <Row k="Intervals" v="nominal 80% · ~69% realised coverage" />
              <Row k="Data" v={`synthetic theatre, seed ${meta.data?.theatre_seed ?? 20261005}`} />
            </div>
          )}
        </Panel>

        <Panel title="Problem statement coverage" bodyClass="p-4">
          <div className="space-y-2.5 text-[12.5px] leading-relaxed">
            <Cover
              title="AI/ML demand forecasting"
              where="Forecast · /api/v1/forecast"
              done="Quantile gradient boosting, walk-forward backtest, exact path attribution."
            />
            <Cover
              title="GIS-enabled logistics planning"
              where="Planner · /api/v1/plan/*"
              done="Corridor graph, multi-depot Clarke-Wright VRP, load packing, reallocation."
            />
            <Cover
              title="IoT-based inventory tracking"
              where="Stock & IoT · /api/v1/sensors"
              done="Simulated pallet, temperature and humidity frames with MQTT-format topics; no physical sensor integration."
            />
            <Cover
              title="Integrated predictive logistics system"
              where="Mission Sim · /api/v1/simulate"
              done="Three-arm counterfactual replay tying forecast, stock, routes and risk together."
            />
          </div>
        </Panel>

        <Panel title="Audit trail" right={<Badge>{audit.data?.items.length ?? 0}</Badge>} bodyClass="p-0">
          {audit.loading ? (
            <Loading />
          ) : (
            <div className="max-h-[330px] divide-y divide-line overflow-y-auto">
              {audit.data?.items.map((a) => (
                <div key={a.id} className="px-4 py-2">
                  <div className="flex items-baseline gap-2">
                    <span className="mono text-[11.5px] text-cyan">{a.username}</span>
                    <span className="mono text-[11px] text-fg">{a.action}</span>
                    <span className="mono ml-auto text-[10.5px] text-dim">
                      {a.ts.slice(5, 16).replace("T", " ")}
                    </span>
                  </div>
                  <div className="mono mt-0.5 text-[11px] text-dim">
                    {a.role}
                    {a.entity ? ` · ${a.entity}` : ""}
                    {a.detail && Object.keys(a.detail).length
                      ? ` · ${JSON.stringify(a.detail).slice(0, 70)}`
                      : ""}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line/60 pb-1.5">
      <span className="label shrink-0">{k}</span>
      <span className="mono text-right text-[12px] text-fg">{v}</span>
    </div>
  );
}

function Cover({ title, where, done }: { title: string; where: string; done: string }) {
  return (
    <div className="border-l-2 border-cyan pl-3">
      <div className="text-[12.5px] font-semibold text-fg">{title}</div>
      <div className="mono text-[11px] text-cyan">{where}</div>
      <div className="mt-0.5 text-dim">{done}</div>
    </div>
  );
}

function Head({ onPrint }: { onPrint: () => void }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4">
      <div>
        <div className="label">Briefing · the pack you actually hand up</div>
        <h1 className="mt-1.5 text-2xl font-bold tracking-tight">
          Briefing <span className="text-cyan">/ evidence, narrative, export</span>
        </h1>
        <p className="mt-1 max-w-3xl text-[13px] text-muted">
          Every simulation leaves an auditable briefing note. This page turns the
          run archive, the model card and the problem-statement coverage into one
          printable pack.
        </p>
      </div>
      <div className="flex gap-2">
        <button className="btn" onClick={onPrint}>
          ⎙ print / pdf
        </button>
      </div>
    </div>
  );
}
