"use client";

import { useMemo, useState } from "react";
import TacticalMap from "@/components/TacticalMap";
import {
  Badge,
  Bar,
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
import { get, post } from "@/lib/api";
import type {
  PackingResult,
  PlanResponse,
  PlanRoute,
  ReallocateResponse,
  Theatre,
} from "@/lib/types";

const UNITS = ["U-12", "U-63", "U-21", "U-47", "U-34", "U-56"];

export default function PlannerPage() {
  const theatre = useLoad(() => get<Theatre>("/theatre"), []);

  const [horizon, setHorizon] = useState(14);
  const [close, setClose] = useState<string[]>([]);
  const [adverse, setAdverse] = useState(false);
  const [capMult, setCapMult] = useState(1);

  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [packing, setPacking] = useState<PackingResult | null>(null);
  const [realloc, setRealloc] = useState<ReallocateResponse | null>(null);
  const [target, setTarget] = useState("U-21");
  const [busy, setBusy] = useState<"plan" | "pack" | "realloc" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const solve = async () => {
    setBusy("plan");
    setErr(null);
    try {
      setPlan(await post<PlanResponse>("/plan/routes", { horizon, close, adverse, capacity_mult: capMult }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const pack = async () => {
    setBusy("pack");
    setErr(null);
    try {
      setPacking(await post<PackingResult>("/plan/consolidate", { horizon }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const reallocate = async () => {
    setBusy("realloc");
    setErr(null);
    try {
      setRealloc(
        await post<ReallocateResponse>("/plan/reallocate", {
          to: target,
          horizon,
          max_ship_t: 6,
        }),
      );
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const b = plan?.baseline;
  const o = plan?.optimised;
  const allRoutes = useMemo(() => o?.routes ?? [], [o]);

  return (
    <div className="space-y-5">
      <Head />

      <div className="grid gap-5 xl:grid-cols-[1fr_340px]">
        <Panel
          title="Convoy route plan · multi-depot vehicle routing"
          right={
            plan ? (
              <Badge tone="good">
                improved {pct(plan.improvement.cost_pct, 1)} cost ·{" "}
                {pct(plan.improvement.distance_pct, 1)} km
              </Badge>
            ) : (
              <Badge tone="neutral">not solved</Badge>
            )
          }
          bodyClass="p-0"
        >
          {theatre.loading ? (
            <Loading label="loading corridor graph" />
          ) : theatre.error ? (
            <ErrorBox message={theatre.error} onRetry={theatre.reload} />
          ) : theatre.data ? (
            <TacticalMap
              theatre={theatre.data}
              routes={allRoutes}
              blocked={close}
              adverse={adverse}
              height={540}
            />
          ) : null}
        </Panel>

        <Panel title="Solver configuration" bodyClass="p-4 space-y-4">
          <div className="flex items-baseline justify-between">
            <span className="label">Planning horizon</span>
            <span className="mono text-[13px] text-cyan">{horizon} days</span>
          </div>
          <input
            type="range"
            min={3}
            max={45}
            value={horizon}
            onChange={(e) => setHorizon(Number(e.target.value))}
            className="w-full accent-cyan"
          />

          <div className="flex items-baseline justify-between">
            <span className="label">Fleet available</span>
            <span className="mono text-[13px] text-cyan">×{capMult.toFixed(2)}</span>
          </div>
          <input
            type="range"
            min={0.3}
            max={1}
            step={0.05}
            value={capMult}
            onChange={(e) => setCapMult(Number(e.target.value))}
            className="w-full accent-cyan"
          />

          <div className="flex items-center justify-between border-t border-line pt-3">
            <span className="label">Adverse weather</span>
            <button
              className={`btn ${adverse ? "btn-danger" : ""}`}
              onClick={() => setAdverse((v) => !v)}
            >
              {String(adverse)}
            </button>
          </div>

          <div className="border-t border-line pt-3">
            <div className="flex items-baseline justify-between">
              <span className="label">Closed corridors</span>
              <span className="mono text-[11px] text-cyan">{close.length}</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(theatre.data?.corridors ?? []).map((c) => (
                <button
                  key={c.code}
                  onClick={() =>
                    setClose((cur) =>
                      cur.includes(c.code)
                        ? cur.filter((x) => x !== c.code)
                        : [...cur, c.code],
                    )
                  }
                  className={`mono rounded-sm border px-1.5 py-1 text-[10.5px] transition-colors ${
                    close.includes(c.code)
                      ? "border-red bg-red/15 text-red"
                      : "border-line text-dim hover:border-line2 hover:text-fg"
                  }`}
                  title={c.name}
                >
                  {c.code}
                </button>
              ))}
            </div>
          </div>

          <button
            className="btn btn-primary w-full justify-center py-3"
            onClick={solve}
            disabled={busy === "plan"}
          >
            {busy === "plan" ? "solving…" : "▶ solve vehicle routing"}
          </button>

          {err && (
            <div className="mono border border-red/40 bg-red/10 px-3 py-2 text-[12px] text-red">
              {err}
            </div>
          )}

          {plan && (
            <div className="mono border-t border-line pt-3 text-[11.5px] text-dim">
              <div className="label mb-1">Cost model</div>
              {Object.entries(plan.cost_model).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span>{k.replace(/_/g, " ")}</span>
                  <span className="text-fg">{v}</span>
                </div>
              ))}
              <div className="mt-1.5 flex justify-between">
                <span>solve time</span>
                <span className="text-fg">{plan.total_ms} ms</span>
              </div>
            </div>
          )}
        </Panel>
      </div>

      {plan && b && o && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
          <Stat
            label="Distance saved"
            value={`${nf(b.distance_km, 0)} → ${nf(o.distance_km, 0)} km`}
            accent="text-green"
            sub={`${nf(plan.improvement.distance_km, 1)} km · ${pct(plan.improvement.distance_pct, 1)}`}
          />
          <Stat
            label="Cost saved"
            value={`${inr(b.cost_inr)} → ${inr(o.cost_inr)}`}
            accent="text-green"
            sub={`${inr(plan.improvement.cost_inr)} · ${pct(plan.improvement.cost_pct, 1)}`}
          />
          <Stat
            label="Fuel"
            value={`${nf(b.fuel_l, 0)} → ${nf(o.fuel_l, 0)} L`}
            accent="text-cyan"
            sub={`${nf(plan.improvement.fuel_l, 1)} L saved`}
          />
          <Stat
            label="Crew hours"
            value={`${nf(b.hours, 0)} → ${nf(o.hours, 0)} h`}
            accent="text-cyan"
            sub={`${b.routes.length} vs ${o.routes.length} routes`}
          />
          <Stat
            label="Utilisation"
            value={`${pct(b.utilisation_pct, 1)} → ${pct(o.utilisation_pct, 1)}`}
            accent="text-green"
            sub={`${nf(plan.improvement.utilisation_pct, 1)} pts`}
          />
          <Stat
            label="Worst leg risk"
            value={`${nf(b.worst_risk, 2)} → ${nf(o.worst_risk, 2)}`}
            accent={o.worst_risk <= b.worst_risk ? "text-green" : "text-amber"}
            sub={`${o.unserved.length} unit(s) unserved`}
          />
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Baseline · crow-flies nearest depot" right={<Badge tone="neutral">greedy</Badge>} bodyClass="p-0">
          {!b ? (
            <Empty message="solve a plan to see the baseline" />
          ) : (
            <RouteTable routes={b.routes} />
          )}
        </Panel>
        <Panel
          title="RAHAT · Clarke-Wright savings + Or-opt"
          right={<Badge tone="good">optimised</Badge>}
          bodyClass="p-0"
        >
          {!o ? (
            <Empty message="solve a plan to see the optimised routes" />
          ) : (
            <RouteTable routes={o.routes} />
          )}
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        {/* consolidation */}
        <Panel
          title="Load consolidation · first-fit-decreasing"
          right={
            <button className="btn" onClick={pack} disabled={busy === "pack"}>
              {busy === "pack" ? "packing…" : "pack 14-day requirement"}
            </button>
          }
          bodyClass="p-4"
        >
          {!packing ? (
            <Empty message="packs the modelled requirement into the available fleet" />
          ) : (
            <>
              <div className="mono mb-3 grid grid-cols-4 gap-2 text-[11.5px]">
                <div>
                  <div className="label">vehicles</div>
                  <div className="text-[16px] text-cyan">
                    {packing.vehicles_used}/{packing.vehicles_available}
                  </div>
                </div>
                <div>
                  <div className="label">mean util</div>
                  <div className="text-[16px] text-fg">{pct(packing.mean_util_pct)}</div>
                </div>
                <div>
                  <div className="label">tonnes</div>
                  <div className="text-[16px] text-fg">{nf(packing.total_t, 1)}</div>
                </div>
                <div>
                  <div className="label">overflow</div>
                  <div className={`text-[16px] ${packing.overflow.length ? "text-red" : "text-green"}`}>
                    {packing.overflow.length}
                  </div>
                </div>
              </div>
              <div className="max-h-[260px] space-y-3 overflow-y-auto pr-1">
                {packing.buckets.map((bk) => (
                  <div key={bk.vehicle}>
                    <div className="mb-1 flex items-baseline justify-between">
                      <span className="mono text-[12px] text-fg">
                        {bk.vehicle} <span className="text-dim">{bk.vehicle_type}</span>
                      </span>
                      <span className="mono text-[11.5px] text-muted">
                        {nf(bk.load_t, 1)} t + {nf(bk.vol_l / 1000, 1)} m³ ·{" "}
                        {pct(bk.util_pct, 0)}
                      </span>
                    </div>
                    <Bar
                      value={bk.util_pct}
                      color={bk.util_pct > 90 ? "bg-green" : bk.util_pct > 60 ? "bg-cyan" : "bg-amber"}
                      height={5}
                    />
                    <div className="mono mt-1 text-[10.5px] text-dim">
                      {bk.lines
                        .map((l) => l.code ?? l.item_code ?? "")
                        .filter(Boolean)
                        .join(" · ") || `${bk.lines.length} lines`}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </Panel>

        {/* reallocation */}
        <Panel
          title="Surplus → deficit reallocation"
          right={
            <div className="flex items-center gap-2">
              <select className="select w-28" value={target} onChange={(e) => setTarget(e.target.value)}>
                {UNITS.map((u) => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
              <button className="btn" onClick={reallocate} disabled={busy === "realloc"}>
                {busy === "realloc" ? "solving…" : "find moves"}
              </button>
            </div>
          }
          bodyClass="p-0"
        >
          {!realloc ? (
            <Empty message="moves surplus stock sideways to cover a projected shortfall" />
          ) : realloc.movements.length === 0 ? (
            <Empty message="no donor holds surplus above the floor for this recipient" />
          ) : (
            <>
              <div className="mono flex gap-6 border-b border-line px-4 py-2.5 text-[11.5px]">
                <span>
                  moves <span className="text-fg">{realloc.movements.length}</span>
                </span>
                <span>
                  tonnage <span className="text-cyan">{nf(realloc.total_t, 1)} t</span>
                </span>
                <span>
                  cost <span className="text-fg">{inr(realloc.total_cost_inr)}</span>
                </span>
                <span>
                  donors <span className="text-fg">{realloc.from.join(", ")}</span>
                </span>
              </div>
              <Table head={["Axis", "Item", "Qty", "Via", "Km", "ETA", "Risk"]}>
                {realloc.movements.map((m, i) => (
                  <tr key={i} className="border-b border-line/60 hover:bg-panel2/60">
                    <Td mono className="text-cyan">
                      {m.from} <span className="text-dim">→</span> {m.to}
                    </Td>
                    <Td mono>{m.item}</Td>
                    <Td mono className="text-fg">{nf(m.qty_t, 2)} t</Td>
                    <Td mono className="text-muted">{m.via.join(" · ")}</Td>
                    <Td mono className="text-muted">{nf(m.distance_km, 1)}</Td>
                    <Td mono className="text-muted">{nf(m.eta_hours, 1)} h</Td>
                    <Td mono className={m.risk > 0.5 ? "text-red" : "text-amber"}>
                      {nf(m.risk, 2)}
                    </Td>
                  </tr>
                ))}
              </Table>
            </>
          )}
        </Panel>
      </div>

      <Panel title="How the planner works" bodyClass="p-4">
        <div className="grid gap-4 text-[12.5px] leading-relaxed md:grid-cols-3">
          <div>
            <div className="label mb-1">① Demand</div>
            <p className="text-muted">
              The champion quantile model forecasts every critical commodity at every
              forward unit over the horizon. Those tonnages — not a guess — become the
              demand column of the routing problem.
            </p>
          </div>
          <div>
            <div className="label mb-1">② Network</div>
            <p className="text-muted">
              A weighted graph over {theatre.data?.corridors.length ?? 20} corridors:
              road class, gradient, weather, closure risk and payload class all price a
              leg. Closed corridors are removed outright, never silently repaired.
            </p>
          </div>
          <div>
            <div className="label mb-1">③ Solve</div>
            <p className="text-muted">
              Hand-written Clarke-Wright savings across every depot with Or-opt
              improvement, evaluated at each depot so the depot itself is a decision
              variable. Multi-trip shuttles cover demand beyond one vehicle&apos;s load.
            </p>
          </div>
        </div>
      </Panel>
    </div>
  );
}

function Head() {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4">
      <div>
        <div className="label">Planner · GIS corridor &amp; convoy optimisation</div>
        <h1 className="mt-1.5 text-2xl font-bold tracking-tight">
          Planner <span className="text-cyan">/ move the freight, not the map</span>
        </h1>
        <p className="mt-1 max-w-3xl text-[13px] text-muted">
          Forecasts become tonnage, tonnage becomes routes, routes become rupees. The
          baseline is deliberately simple — crow-flies nearest depot — so the saving
          is the algorithm, not a rigged fleet.
        </p>
      </div>
      <Badge tone="info">pillar 2 · GIS planning</Badge>
    </div>
  );
}

function RouteTable({ routes }: { routes: PlanRoute[] }) {
  if (!routes.length) return <Empty message="no routes returned" />;
  return (
    <Table head={["Vehicle", "Depot", "Stops", "Load", "Km", "Hours", "Cost", "Risk"]}>
      {routes.map((r) => (
        <tr key={r.vehicle} className="border-b border-line/60 hover:bg-panel2/60">
          <Td mono className="text-cyan">{r.vehicle}</Td>
          <Td mono className="text-muted">{r.depot}</Td>
          <Td mono>
            {r.visits.join(" → ")}
            <span className="text-dim"> ({r.legs.length} legs)</span>
          </Td>
          <Td mono>
            {nf(r.load_t, 1)} / {nf(r.capacity_t, 0)} t
          </Td>
          <Td mono className="text-muted">{nf(r.distance_km, 1)}</Td>
          <Td mono className="text-muted">{nf(r.hours, 1)}</Td>
          <Td mono className="text-muted">{inr(r.cost_inr)}</Td>
          <Td mono className={r.risk > 0.5 ? "text-red" : r.risk > 0.3 ? "text-amber" : "text-green"}>
            {nf(r.risk, 2)}
          </Td>
        </tr>
      ))}
    </Table>
  );
}
