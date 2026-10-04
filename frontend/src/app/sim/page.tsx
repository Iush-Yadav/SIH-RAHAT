"use client";

import { useMemo, useState } from "react";
import TacticalMap from "@/components/TacticalMap";
import {
  Badge,
  Bar,
  Delta,
  Empty,
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
import { API_BASE, get, getToken, post } from "@/lib/api";
import type {
  PlanMetrics,
  PlanResponse,
  ScenarioStub,
  Sim,
  SimSummary,
  Theatre,
} from "@/lib/types";

const ARMS: { key: keyof Sim["plans"]; label: string; blurb: string }[] = [
  {
    key: "pre_disruption",
    label: "① Pre-disruption order",
    blurb: "Standing order written before the event — healthy network.",
  },
  {
    key: "no_reaction",
    label: "② No reaction",
    blurb: "Same order replayed on the damaged network. Nothing re-planned.",
  },
  {
    key: "rahat",
    label: "③ RAHAT re-solved",
    blurb: "Re-forecast, re-routed and pre-staged for the damaged network.",
  },
];

const METRIC_ROWS: {
  label: string;
  get: (m: PlanMetrics) => number | null;
  fmt: (v: number) => string;
}[] = [
  { label: "Freight delivered", get: (m) => m.tonnage_t, fmt: (v) => `${nf(v, 1)} t` },
  { label: "Crew hours", get: (m) => m.hours, fmt: (v) => `${nf(v, 0)} h` },
  { label: "Distance", get: (m) => m.distance_km, fmt: (v) => `${nf(v, 0)} km` },
  { label: "Fuel", get: (m) => m.fuel_l, fmt: (v) => `${nf(v, 0)} L` },
  { label: "Cost", get: (m) => m.cost_inr, fmt: (v) => inr(v) },
  { label: "Cost per tonne", get: (m) => m.cost_per_tonne_inr, fmt: (v) => inr(v) },
  { label: "Lift utilisation", get: (m) => m.utilisation_pct, fmt: (v) => `${nf(v, 1)}%` },
  { label: "Worst leg risk", get: (m) => m.worst_risk, fmt: (v) => nf(v, 2) },
];

export default function SimPage() {
  const [scenario, setScenario] = useState("bridge_washout");
  const [horizon, setHorizon] = useState(14);
  const [overrides, setOverrides] = useState<Record<string, unknown>>({});
  const [sim, setSim] = useState<Sim | null>(null);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const theatre = useLoad(() => getTheatre(), []);
  const scenarios = useLoad(() => listScenarios(), []);
  const history = useLoad(() => listSims(), []);

  const scenarioMeta = useMemo(
    () => scenarios.data?.items.find((s) => s.key === scenario),
    [scenarios.data, scenario],
  );

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const close = (overrides.close as string[] | undefined) ?? scenarioMeta?.params.close ?? [];
      const adverse =
        typeof overrides.adverse === "boolean"
          ? overrides.adverse
          : scenarioMeta?.params.adverse ?? false;
      const capacityMult =
        typeof overrides.capacity_mult === "number"
          ? overrides.capacity_mult
          : scenarioMeta?.params.capacity_mult ?? 1;

      const [result, planRes] = await Promise.all([
        post<Sim>("/simulate", {
          scenario,
          horizon,
          overrides: Object.keys(overrides).length ? overrides : {},
        }),
        post<PlanResponse>("/plan/routes", {
          horizon,
          close,
          adverse,
          capacity_mult: capacityMult,
        }),
      ]);
      setSim(result);
      setPlan(planRes);
      history.reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const blocked = useMemo(() => {
    const s = new Set<string>(sim?.params.close ?? []);
    for (const b of sim?.plans.no_reaction.blocked_routes ?? []) s.add(b.blocked_at);
    for (const b of sim?.plans.rahat.blocked_routes ?? []) s.add(b.blocked_at);
    return [...s];
  }, [sim]);

  const downloadBriefing = async () => {
    if (!sim?.id) return;
    const r = await fetch(`${API_BASE}/simulations/${sim.id}/briefing`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    const text = await r.text();
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `RAHAT-BRIEFING-${sim.scenario}-${sim.id}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-5">
      <Head />

      <div className="grid gap-5 xl:grid-cols-[1fr_360px]">
        {/* ── scenario picker ── */}
        <Panel title="Counterfactual scenarios" bodyClass="p-4">
          <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {(scenarios.data?.items ?? []).map((s) => (
              <ScenarioCard
                key={s.key}
                s={s}
                active={scenario === s.key}
                onClick={() => {
                  setScenario(s.key);
                  setOverrides({});
                }}
              />
            ))}
          </div>
          <button
            className={`mt-3 w-full border px-4 py-3 text-left transition-colors ${
              scenario === "custom"
                ? "border-cyan bg-cyan/10"
                : "border-line hover:border-line2 hover:bg-panel2"
            }`}
            onClick={() => {
              setScenario("custom");
              setOverrides((o) => ({
                close: o.close ?? [],
                adverse: o.adverse ?? false,
                ...o,
              }));
            }}
          >
            <div className="mono text-[12px] font-semibold text-cyan">
              ⚙ CUSTOM SCENARIO
            </div>
            <div className="mt-0.5 text-[11.5px] text-dim">
              Build your own disruption — close any corridor, flip weather, cut the
              fleet, surge demand.
            </div>
          </button>

          {scenarioMeta && (
            <div className="mt-4 border-t border-line pt-3">
              <div className="label mb-1.5">Preset parameters</div>
              <div className="mono flex flex-wrap gap-1.5 text-[11px]">
                <Badge tone="neutral">close: {(scenarioMeta.params.close ?? []).join(", ") || "none"}</Badge>
                <Badge tone={scenarioMeta.params.adverse ? "warn" : "neutral"}>
                  adverse: {String(scenarioMeta.params.adverse)}
                </Badge>
                <Badge tone="neutral">risk +{scenarioMeta.params.risk_boost}</Badge>
                <Badge tone="neutral">rain ×{scenarioMeta.params.rainfall_mult}</Badge>
                {scenarioMeta.params.demand_mult !== undefined && (
                  <Badge tone="neutral">demand ×{scenarioMeta.params.demand_mult}</Badge>
                )}
                {scenarioMeta.params.capacity_mult !== undefined && (
                  <Badge tone="neutral">fleet ×{scenarioMeta.params.capacity_mult}</Badge>
                )}
              </div>
              <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
                {scenarioMeta.description}
              </p>
              <p className="mt-1.5 text-[12.5px] leading-relaxed text-cyan italic">
                “{scenarioMeta.talking_point}”
              </p>
            </div>
          )}
        </Panel>

        {/* ── controls ── */}
        <Panel title="Run configuration" bodyClass="p-4 space-y-4">
          <label className="block">
            <div className="flex items-baseline justify-between">
              <span className="label">Forecast horizon</span>
              <span className="mono text-[13px] text-cyan">{horizon} days</span>
            </div>
            <input
              type="range"
              min={3}
              max={45}
              step={1}
              value={horizon}
              onChange={(e) => setHorizon(Number(e.target.value))}
              className="mt-2 w-full accent-cyan"
            />
          </label>

          <Slider
            label="Demand surge ×"
            keyName="demand_mult"
            def={1}
            min={0.5}
            max={3}
            step={0.1}
            overrides={overrides}
            setOverrides={setOverrides}
          />
          <Slider
            label="Fleet available ×"
            keyName="capacity_mult"
            def={1}
            min={0.3}
            max={1}
            step={0.05}
            overrides={overrides}
            setOverrides={setOverrides}
          />
          <Slider
            label="Corridor risk boost"
            keyName="risk_boost"
            def={0}
            min={0}
            max={0.4}
            step={0.02}
            overrides={overrides}
            setOverrides={setOverrides}
          />

          <div className="flex items-center justify-between border-t border-line pt-3">
            <span className="label">Adverse weather</span>
            <button
              className={`btn ${overrides.adverse ? "btn-danger" : ""}`}
              onClick={() =>
                setOverrides((o) => ({ ...o, adverse: !(o.adverse ?? false) }))
              }
            >
              {String(overrides.adverse ?? scenarioMeta?.params.adverse ?? false)}
            </button>
          </div>

          <CorridorPicker
            overrides={overrides}
            setOverrides={setOverrides}
            theatre={theatre.data}
          />

          <button
            className={`btn btn-primary w-full justify-center py-3 ${busy ? "opacity-70" : ""}`}
            onClick={run}
            disabled={busy}
          >
            {busy ? "solving…" : "▶ run mission sim"}
          </button>

          {Object.keys(overrides).length > 0 && (
            <button className="btn w-full justify-center" onClick={() => setOverrides({})}>
              reset overrides
            </button>
          )}

          {err && (
            <div className="mono border border-red/40 bg-red/10 px-3 py-2 text-[12px] text-red">
              {err}
            </div>
          )}
        </Panel>
      </div>

      {busy && (
        <Panel bodyClass="p-4">
          <Loading label="re-forecasting 36 series · solving VRP · replaying counterfactuals" />
        </Panel>
      )}

      {sim && (
        <Results
          sim={sim}
          plan={plan}
          theatre={theatre.data}
          blocked={blocked}
          onDownload={downloadBriefing}
        />
      )}

      <Panel title="Simulation history" right={<Badge>{history.data?.items.length ?? 0}</Badge>} bodyClass="p-0">
        {history.loading ? (
          <Loading />
        ) : (history.data?.items.length ?? 0) === 0 ? (
          <Empty message="no simulations recorded yet — run one above" />
        ) : (
          <Table head={["ID", "Scenario", "Horizon", "Fill Δ", "Solved", "By", "When"]}>
            {history.data?.items.slice(0, 12).map((r: SimSummary) => (
              <tr key={r.id} className="border-b border-line/60 hover:bg-panel2/60">
                <Td mono className="text-dim">#{r.id}</Td>
                <Td mono className="text-cyan">{r.label}</Td>
                <Td mono>{r.result?.horizon ?? "—"} d</Td>
                <Td mono>
                  <span className={((r.result?.delta?.fill_rate_pct ?? 0) >= 0 ? "text-green" : "text-red")}>
                    {(r.result?.delta?.fill_rate_pct ?? 0) >= 0 ? "+" : ""}
                    {r.result?.delta?.fill_rate_pct ?? 0} pts
                  </span>
                </Td>
                <Td mono className="text-muted">{r.solve_ms} ms</Td>
                <Td mono className="text-muted">{r.username}</Td>
                <Td mono className="text-dim">{r.created_at.slice(5, 16).replace("T", " ")}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Panel>
    </div>
  );
}

/* ── pieces ────────────────────────────────────────────────────────── */

function Head() {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4">
      <div>
        <div className="label">Mission sim · counterfactual digital twin</div>
        <h1 className="mt-1.5 text-2xl font-bold tracking-tight">
          Mission Sim <span className="text-cyan">/ rehearse the disruption</span>
        </h1>
        <p className="mt-1 max-w-3xl text-[13px] text-muted">
          Three arms, one disruption: the order you already wrote, what happens if
          you do nothing, and what RAHAT re-solves. Same demand forecast, same
          vehicles, same terrain — only the plan differs.
        </p>
      </div>
      <Badge tone="info">pillar 4 · integrated system</Badge>
    </div>
  );
}

function ScenarioCard({
  s,
  active,
  onClick,
}: {
  s: ScenarioStub;
  active: boolean;
  onClick: () => void;
}) {
  const sev =
    s.severity === "high" || s.severity === "critical"
      ? "text-red"
      : s.severity === "medium"
        ? "text-amber"
        : "text-green";
  return (
    <button
      onClick={onClick}
      className={`border p-3 text-left transition-colors ${
        active ? "border-cyan bg-cyan/10" : "border-line hover:border-line2 hover:bg-panel2"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="mono text-[12px] font-semibold text-fg uppercase">
          {s.icon} {s.label}
        </span>
        <span className={`mono text-[10px] uppercase ${sev}`}>{s.severity}</span>
      </div>
      <div className="mt-1 text-[11.5px] leading-snug text-dim">{s.description}</div>
      <div className="mono mt-1.5 text-[10.5px] text-cyan">
        close: {(s.params.close ?? []).join(", ") || "—"}
      </div>
    </button>
  );
}

function Slider({
  label,
  keyName,
  def = 1,
  min,
  max,
  step,
  overrides,
  setOverrides,
}: {
  label: string;
  keyName: string;
  def?: number;
  min: number;
  max: number;
  step: number;
  overrides: Record<string, unknown>;
  setOverrides: (fn: (o: Record<string, unknown>) => Record<string, unknown>) => void;
}) {
  const v = typeof overrides[keyName] === "number" ? (overrides[keyName] as number) : def;
  const touched = keyName in overrides;
  return (
    <label className="block">
      <div className="flex items-baseline justify-between">
        <span className="label">{label}</span>
        <span className={`mono text-[12.5px] ${touched ? "text-cyan" : "text-dim"}`}>
          {v.toFixed(2)}
          {touched ? " *" : ""}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={v}
        onChange={(e) =>
          setOverrides((o) => ({ ...o, [keyName]: Number(e.target.value) }))
        }
        className="mt-2 w-full accent-cyan"
      />
    </label>
  );
}

function CorridorPicker({
  overrides,
  setOverrides,
  theatre,
}: {
  overrides: Record<string, unknown>;
  setOverrides: (fn: (o: Record<string, unknown>) => Record<string, unknown>) => void;
  theatre: Theatre | null;
}) {
  const sel = (overrides.close as string[] | undefined) ?? [];
  const toggle = (code: string) =>
    setOverrides((o) => {
      const cur = (o.close as string[] | undefined) ?? [];
      const next = cur.includes(code) ? cur.filter((c) => c !== code) : [...cur, code];
      return { ...o, close: next };
    });

  if (!theatre) return null;
  return (
    <div className="border-t border-line pt-3">
      <div className="flex items-baseline justify-between">
        <span className="label">Close corridors</span>
        <span className="mono text-[11px] text-cyan">{sel.length} selected</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {theatre.corridors.map((c) => {
          const on = sel.includes(c.code);
          return (
            <button
              key={c.code}
              onClick={() => toggle(c.code)}
              className={`mono rounded-sm border px-1.5 py-1 text-[10.5px] transition-colors ${
                on
                  ? "border-red bg-red/15 text-red"
                  : "border-line text-dim hover:border-line2 hover:text-fg"
              }`}
              title={`${c.name} (${c.road_class})`}
            >
              {c.code}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ── results ───────────────────────────────────────────────────────── */

function Results({
  sim,
  plan,
  theatre,
  blocked,
  onDownload,
}: {
  sim: Sim;
  plan: PlanResponse | null;
  theatre: Theatre | null;
  blocked: string[];
  onDownload: () => void;
}) {
  const d = sim.delta;
  const before = sim.before;
  const after = sim.after;

  return (
    <div className="space-y-5">
      <Panel
        title={`Assessment · ${sim.label}`}
        right={
          <div className="flex items-center gap-2">
            <Badge tone={sim.severity === "high" ? "bad" : "warn"}>{sim.severity}</Badge>
            <Badge tone="neutral">sim #{sim.id}</Badge>
            <button className="btn" onClick={onDownload}>
              ↓ briefing
            </button>
          </div>
        }
        bodyClass="p-4"
      >
        <p className="text-[13px] leading-relaxed text-muted">{sim.description}</p>
        <div className="mono mt-2 text-[11.5px] text-dim">
          solved in {sim.solve_ms} ms · {sim.horizon}-day horizon · closed{" "}
          <span className="text-red">{(sim.params.close ?? []).join(", ") || "none"}</span> ·
          adverse weather <span className={sim.params.adverse ? "text-amber" : "text-green"}>{String(sim.params.adverse)}</span> ·
          generated {sim.generated_at.slice(11, 19)}Z
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
          <Stat
            label="Fill rate"
            value={`${pct(before.fill_rate_pct)} → ${pct(after.fill_rate_pct)}`}
            accent={after.fill_rate_pct >= before.fill_rate_pct ? "text-green" : "text-red"}
            sub={<Delta v={d.fill_rate_pct} unit=" pts" />}
          />
          <Stat
            label="Units at risk"
            value={`${d.units_at_risk_before} → ${d.units_at_risk_after}`}
            accent={d.units_at_risk_after < d.units_at_risk_before ? "text-green" : "text-amber"}
            sub={
              after.units_at_risk.length ? after.units_at_risk.join(" · ") : "none exposed"
            }
          />
          <Stat
            label="Critical stockouts"
            value={`${d.stockouts_before} → ${d.stockouts_after}`}
            accent={d.stockouts_after < d.stockouts_before ? "text-green" : "text-amber"}
            sub="item-unit lines over the horizon"
          />
          <Stat
            label="Freight delivered"
            value={`${nf(sim.plans.no_reaction.tonnage_t, 1)} → ${nf(sim.plans.rahat.tonnage_t, 1)} t`}
            accent="text-cyan"
            sub={<Delta v={d.delivered_t} unit=" t" />}
          />
          <Stat
            label="Cost"
            value={`${inr(sim.plans.no_reaction.cost_inr)} → ${inr(sim.plans.rahat.cost_inr)}`}
            accent={d.cost_inr <= 0 ? "text-green" : "text-amber"}
            sub={<Delta v={pctDelta(sim.plans.no_reaction.cost_inr, sim.plans.rahat.cost_inr)} />}
          />
          <Stat
            label="Distance"
            value={`${nf(sim.plans.no_reaction.distance_km, 0)} → ${nf(sim.plans.rahat.distance_km, 0)} km`}
            accent={d.distance_km <= 0 ? "text-green" : "text-amber"}
            sub={<Delta v={pctDelta(sim.plans.no_reaction.distance_km, sim.plans.rahat.distance_km)} />}
          />
        </div>
      </Panel>

      {/* three-arm comparison */}
      <Panel title="Three-arm comparison" bodyClass="p-0">
        <div className="grid divide-y divide-line lg:grid-cols-3 lg:divide-x lg:divide-y-0">
          {ARMS.map((arm) => {
            const m = sim.plans[arm.key];
            const hero = arm.key === "rahat";
            return (
              <div key={arm.key} className={`p-4 ${hero ? "bg-cyan/5" : ""}`}>
                <div className="flex items-center justify-between">
                  <span className={`mono text-[12.5px] font-semibold ${hero ? "text-cyan" : "text-fg"}`}>
                    {arm.label}
                  </span>
                  <Badge tone={m.blocked_routes.length ? "bad" : "good"}>
                    {m.blocked_routes.length ? `${m.blocked_routes.length} blocked` : "runs"}
                  </Badge>
                </div>
                <div className="mt-1 text-[11.5px] text-dim">{arm.blurb}</div>
                <div className="mono mt-2 text-[10.5px] text-dim">
                  {m.solver} · {m.solve_ms} ms
                </div>

                <div className="mt-3 space-y-1.5">
                  {METRIC_ROWS.filter((r) => r.label !== "Routes run / blocked").map((r) => {
                    const v = r.get(m);
                    return (
                      <div key={r.label} className="flex items-baseline justify-between gap-2">
                        <span className="text-[12px] text-muted">{r.label}</span>
                        <span className="mono text-[12.5px] text-fg">
                          {v === null ? "—" : r.fmt(v)}
                        </span>
                      </div>
                    );
                  })}
                </div>

                <div className="mt-3 border-t border-line pt-2">
                  <div className="label mb-1">Blocked standing routes</div>
                  {m.blocked_routes.length ? (
                    <div className="space-y-1">
                      {m.blocked_routes.map((b, i) => (
                        <div key={i} className="mono text-[11px] text-red">
                          {b.blocked_at} <span className="text-dim">({b.blocked_leg})</span> —{" "}
                          <span className="text-muted">{b.reason}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="mono text-[11px] text-green">none — every leg runs</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Panel>

      <div className="grid gap-5 xl:grid-cols-[1.5fr_1fr]">
        <Panel title="Damaged network · re-solved plan" bodyClass="p-0">
          {theatre ? (
            <TacticalMap
              theatre={theatre}
              routes={plan?.optimised.routes ?? []}
              blocked={blocked}
              adverse={sim.params.adverse}
              height={470}
            />
          ) : (
            <Loading label="loading theatre" />
          )}
        </Panel>

        <Panel title="Commander's briefing note" right={<Badge tone="info">auto-generated</Badge>} bodyClass="p-0">
          <pre className="mono max-h-[470px] overflow-auto px-4 py-3 text-[11.5px] leading-relaxed whitespace-pre-wrap text-muted">
            {sim.briefing_note}
          </pre>
        </Panel>
      </div>

      {/* pre-stage */}
      <div className="grid gap-5 xl:grid-cols-2">
        <Panel
          title="Recommended pre-closure movement"
          right={<Badge tone="warn">{nf(sim.prestage_t, 1)} t</Badge>}
          bodyClass="p-0"
        >
          {sim.prestage.length === 0 ? (
            <Empty message="network stays connected — no pre-stage required" />
          ) : (
            <Table head={["Axis", "Item", "Qty", "Via", "Km", "ETA", "Cost"]}>
              {sim.prestage.map((m, i) => (
                <tr key={i} className="border-b border-line/60 hover:bg-panel2/60">
                  <Td mono className="text-cyan">
                    {m.from} <span className="text-dim">→</span> {m.to}
                  </Td>
                  <Td mono>{m.item}</Td>
                  <Td mono className="text-fg">{nf(m.qty_t, 1)} t</Td>
                  <Td mono className="text-muted">{m.via.join(" · ")}</Td>
                  <Td mono className="text-muted">{nf(m.distance_km, 1)}</Td>
                  <Td mono className="text-muted">{nf(m.eta_hours, 1)} h</Td>
                  <Td mono className="text-muted">{inr(m.cost_inr)}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Panel>

        <Panel
          title="Isolated formations"
          right={<Badge tone={sim.stranded.length ? "bad" : "good"}>{sim.stranded.length}</Badge>}
          bodyClass="p-0"
        >
          {sim.stranded.length === 0 ? (
            <Empty message="every formation keeps at least one supply axis" />
          ) : (
            <div className="divide-y divide-line">
              {sim.stranded.map((s) => (
                <div key={s.node} className="px-4 py-3">
                  <div className="flex items-baseline justify-between">
                    <span className="mono text-[13px] font-semibold text-red">
                      {s.node} <span className="text-muted">{s.name}</span>
                    </span>
                    <span className="mono text-[12px] text-amber">{nf(s.days_left, 1)} d stock</span>
                  </div>
                  <div className="mono mt-1 grid grid-cols-4 gap-2 text-[11.5px] text-dim">
                    <span>held <span className="text-fg">{nf(s.on_hand_t, 1)} t</span></span>
                    <span>need <span className="text-fg">{nf(s.horizon_demand_t, 1)} t</span></span>
                    <span>gap <span className="text-red">{nf(s.gap_t, 1)} t</span></span>
                    <span>pre-stage <span className="text-green">{nf(s.prestaged_t, 1)} t</span></span>
                  </div>
                  <div className="mt-1.5 text-[11.5px] text-dim italic">→ {s.action}</div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      {/* stockouts + packing */}
      <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
        <Panel
          title="Projected critical stockouts"
          right={
            <Badge tone={sim.after.stockouts.length ? "bad" : "good"}>
              {sim.before.stockouts.length} before · {sim.after.stockouts.length} after
            </Badge>
          }
          bodyClass="p-0"
        >
          {sim.after.stockouts.length === 0 && sim.before.stockouts.length === 0 ? (
            <Empty message="no critical line falls below service level" />
          ) : (
            <Table head={["Node", "Item", "Stockout day", "Requirement", "Covered", "Fill"]}>
              {sim.before.stockouts.slice(0, 10).map((so, i) => {
                const fixed = sim.after.stockouts.find(
                  (a) => a.node === so.node && a.item === so.item,
                );
                const row = fixed ?? so;
                return (
                  <tr key={`${so.node}-${so.item}-${i}`} className="border-b border-line/60">
                    <Td mono className="text-cyan">{so.node}</Td>
                    <Td mono>{so.item_name}</Td>
                    <Td mono className={fixed ? "text-green" : "text-red"}>
                      day {nf(row.day, 1)}
                      {fixed && (
                        <span className="ml-1.5 text-dim"> (was {nf(so.day, 1)})</span>
                      )}
                    </Td>
                    <Td mono className="text-muted">{nf(row.req_kg, 0)} kg</Td>
                    <Td mono className="text-muted">{nf(row.supply_kg, 0)} kg</Td>
                    <Td mono className={row.fill_pct >= 95 ? "text-green" : "text-amber"}>
                      {pct(row.fill_pct)}
                    </Td>
                  </tr>
                );
              })}
            </Table>
          )}
        </Panel>

        <Panel
          title="Load consolidation"
          right={
            <Badge tone={sim.packing ? "info" : "neutral"}>
              {sim.packing ? `${sim.packing.vehicles_used}/${sim.packing.vehicles_available} vehicles` : "n/a"}
            </Badge>
          }
          bodyClass="p-4"
        >
          {!sim.packing || sim.packing.buckets.length === 0 ? (
            <Empty message="nothing to pack in this scenario" />
          ) : (
            <>
              <div className="mono mb-3 grid grid-cols-3 gap-2 text-[11.5px]">
                <div>
                  <div className="label">mean util</div>
                  <div className="text-[16px] text-cyan">{pct(sim.packing.mean_util_pct)}</div>
                </div>
                <div>
                  <div className="label">tonnes</div>
                  <div className="text-[16px] text-fg">{nf(sim.packing.total_t, 1)}</div>
                </div>
                <div>
                  <div className="label">overflow</div>
                  <div className={`text-[16px] ${sim.packing.overflow.length ? "text-red" : "text-green"}`}>
                    {sim.packing.overflow.length}
                  </div>
                </div>
              </div>
              <div className="max-h-[220px] space-y-2.5 overflow-y-auto pr-1">
                {sim.packing.buckets.map((b) => (
                  <div key={b.vehicle}>
                    <div className="mb-1 flex items-baseline justify-between">
                      <span className="mono text-[11.5px] text-fg">
                        {b.vehicle} <span className="text-dim">{b.vehicle_type}</span>
                      </span>
                      <span className="mono text-[11.5px] text-muted">
                        {nf(b.load_t, 1)} / {nf(b.capacity_t, 0)} t · {pct(b.util_pct, 0)}
                      </span>
                    </div>
                    <Bar
                      value={b.util_pct}
                      color={b.util_pct > 90 ? "bg-green" : b.util_pct > 60 ? "bg-cyan" : "bg-amber"}
                      height={5}
                    />
                  </div>
                ))}
              </div>
            </>
          )}
        </Panel>
      </div>

      {sim.alerts.length > 0 && (
        <Panel title="Scenario alerts" bodyClass="p-0">
          <div className="divide-y divide-line">
            {sim.alerts.map((a, i) => (
              <div key={i} className="flex items-start gap-3 px-4 py-2.5">
                <Badge tone={a.severity === "critical" ? "bad" : "warn"}>{a.severity}</Badge>
                <span className="mono w-16 shrink-0 text-[11.5px] text-cyan">{a.node}</span>
                <span className="text-[12.5px] text-muted">{a.message}</span>
                <span className="mono ml-auto shrink-0 text-[11px] text-dim">{a.action}</span>
              </div>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

function pctDelta(from: number, to: number) {
  if (!from) return 0;
  return ((to - from) / from) * 100;
}

const getTheatre = () => get<Theatre>("/theatre");
const listScenarios = () => get<{ items: ScenarioStub[] }>("/scenarios");
const listSims = () => get<{ items: SimSummary[] }>("/simulations");
