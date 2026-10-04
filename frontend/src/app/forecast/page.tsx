"use client";

import { useEffect, useMemo, useState } from "react";
import ForecastChart from "@/components/ForecastChart";
import {
  Badge,
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
import { get } from "@/lib/api";
import type { Forecast, Leaderboard, LeaderRow, SeriesList } from "@/lib/types";

const NODES = ["U-12", "U-63", "U-21", "U-47", "U-34", "U-56"];
const TEMPOS = ["low", "nominal", "high"];

export default function ForecastPage() {
  const seriesList = useLoad(() => get<SeriesList>("/forecast/series"), []);
  const leaderboard = useLoad(() => get<Leaderboard>("/forecast/leaderboard"), []);

  const [node, setNode] = useState("U-21");
  const [item, setItem] = useState("POL-DIE");
  const [horizon, setHorizon] = useState(30);
  const [tempo, setTempo] = useState("nominal");
  const [ops, setOps] = useState(0);
  const [rain, setRain] = useState(1);
  const [tempOff, setTempOff] = useState(0);
  const [demand, setDemand] = useState(1);

  const [fc, setFc] = useState<Forecast | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const qs = useMemo(
    () =>
      `node=${node}&item=${item}&horizon=${horizon}&tempo=${tempo}&ops=${ops}` +
      `&rainfall_mult=${rain}&temp_offset=${tempOff}&demand_mult=${demand}`,
    [node, item, horizon, tempo, ops, rain, tempOff, demand],
  );

  const load = async (signal?: AbortSignal) => {
    setBusy(true);
    setErr(null);
    try {
      const data = await get<Forecast>(`/forecast?${qs}`);
      if (signal?.aborted) return;
      setFc(data);
    } catch (e) {
      if ((e as Error)?.name === "AbortError") return;
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      if (!signal?.aborted) setBusy(false);
    }
  };

  useEffect(() => {
    const ctrl = new AbortController();
    const t = setTimeout(() => void load(ctrl.signal), 250);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qs]);

  const items = useMemo(() => {
    const m = new Map<string, string>();
    for (const p of seriesList.data?.pairs ?? []) m.set(p.item, p.item);
    return [...m.values()];
  }, [seriesList.data]);

  const pairKey = `${node}|${item}`;
  const pairMetrics: Omit<LeaderRow, "is_champion">[] | null =
    (leaderboard.data?.per_pair[pairKey]
      ? Object.entries(leaderboard.data.per_pair[pairKey]).map(([model, metrics]) => ({ ...metrics, model }))
      : null) ?? null;

  const chips = [
    ["horizon", `${horizon} d`, horizon !== 30],
    ["tempo", tempo, tempo !== "nominal"],
    ["ops", String(ops), ops !== 0],
    ["rain ×", rain.toFixed(1), rain !== 1],
    ["temp ±", `${tempOff}°C`, tempOff !== 0],
    ["demand ×", demand.toFixed(1), demand !== 1],
  ] as const;

  const dirty = chips.some(([, , d]) => d);

  return (
    <div className="space-y-5">
      <Head />

      <div className="grid gap-5 xl:grid-cols-[320px_1fr]">
        <div className="space-y-5">
          <Panel title="Forecast target" bodyClass="p-4 space-y-3">
            <label className="block">
              <span className="label">Forward unit</span>
              <select className="select mt-1" value={node} onChange={(e) => setNode(e.target.value)}>
                {NODES.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="label">Commodity</span>
              <select className="select mt-1" value={item} onChange={(e) => setItem(e.target.value)}>
                {items.map((i) => (
                  <option key={i} value={i}>
                    {i}
                  </option>
                ))}
              </select>
            </label>
            <div className="grid grid-cols-2 gap-2 border-t border-line pt-3">
              <label className="block">
                <span className="label">Horizon · {horizon} d</span>
                <input
                  type="range"
                  min={7}
                  max={90}
                  value={horizon}
                  onChange={(e) => setHorizon(Number(e.target.value))}
                  className="mt-2 w-full accent-cyan"
                />
              </label>
              <label className="block">
                <span className="label">Tempo</span>
                <select className="select mt-1" value={tempo} onChange={(e) => setTempo(e.target.value)}>
                  {TEMPOS.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </Panel>

          <Panel title="What-if levers" bodyClass="p-4 space-y-4">
            <Note />
            <Slide label="Rainfall ×" v={rain} set={setRain} min={0} max={6} step={0.25} />
            <Slide label="Temperature offset °C" v={tempOff} set={setTempOff} min={-20} max={20} step={1} />
            <Slide label="Demand multiplier ×" v={demand} set={setDemand} min={0.2} max={4} step={0.1} />
            <div className="flex items-center justify-between border-t border-line pt-3">
              <span className="label">Ops level</span>
              <div className="flex gap-1">
                {[0, 1, 2].map((o) => (
                  <button
                    key={o}
                    onClick={() => setOps(o)}
                    className={`btn ${ops === o ? "btn-primary" : ""} px-2.5 py-1`}
                  >
                    {o}
                  </button>
                ))}
              </div>
            </div>
            {dirty && (
              <button
                className="btn w-full justify-center"
                onClick={() => {
                  setHorizon(30);
                  setTempo("nominal");
                  setOps(0);
                  setRain(1);
                  setTempOff(0);
                  setDemand(1);
                }}
              >
                reset levers
              </button>
            )}
          </Panel>
        </div>

        <div className="space-y-5">
          <Panel
            title={`${node} · ${fc?.item_name ?? item} — demand outlook`}
            right={
              <div className="flex items-center gap-2">
                <div className="mono flex flex-wrap gap-1.5 text-[10.5px]">
                  {chips.map(([k, v, d]) => (
                    <span key={k} className={d ? "text-cyan" : "text-dim"}>
                      {k} {v}
                    </span>
                  ))}
                </div>
                {busy && <Badge tone="info">re-forecasting</Badge>}
              </div>
            }
            bodyClass="p-4"
          >
            {err && <ErrorBox message={err} onRetry={() => void load()} />}
            {!err && !fc && <Loading label="loading quantile forecast" />}
            {fc && (
              <>
                <ForecastChart series={fc.series} />
                <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <Stat
                    label={`${horizon}-day requirement`}
                    value={`${nf(fc.summary.total_kg / 1000, 2)} t`}
                    accent="text-cyan"
                    sub={`p10 ${nf(fc.summary.p10_total_kg / 1000, 2)} t · p90 ${nf(fc.summary.p90_total_kg / 1000, 2)} t`}
                  />
                  <Stat
                    label="Peak day"
                    value={`${nf(fc.summary.peak_kg, 0)} kg`}
                    accent="text-amber"
                    sub={fc.summary.peak_day}
                  />
                  <Stat
                    label="Band width"
                    value={pct(fc.summary.band_width_pct, 0)}
                    sub="mean p10–p90 spread relative to p50"
                  />
                  <Stat
                    label="vs seasonal naive"
                    value={pct(
                      ((fc.summary.total_kg - fc.summary.naive_total_kg) /
                        Math.max(fc.summary.naive_total_kg, 1)) *
                        100,
                      1,
                    )}
                    accent="text-violet"
                    sub={`naive ${nf(fc.summary.naive_total_kg / 1000, 2)} t`}
                  />
                </div>

                <p className="mt-4 border-l-2 border-cyan bg-cyan/5 px-3 py-2 text-[13px] leading-relaxed text-muted">
                  {fc.narrative}
                </p>
              </>
            )}
          </Panel>

          <div className="grid gap-5 lg:grid-cols-2">
            <Panel
              title="Why this number · exact path attribution"
              right={<Badge tone="info">peak-day decomposition</Badge>}
              bodyClass="p-4"
            >
              {!fc ? (
                <Loading />
              ) : (
                <>
                  <p className="mb-3 text-[12.5px] leading-relaxed text-dim">
                    Every prediction is decomposed into per-feature contributions in
                    kilograms per day. They sum exactly to the model output — no
                    post-hoc approximation.
                  </p>
                  <div className="space-y-2">
                    {fc.attribution.slice(0, 10).map((a) => {
                      const maxAbs = Math.max(
                        ...fc.attribution.map((x) => Math.abs(x.contribution)),
                        1,
                      );
                      const w = (Math.abs(a.contribution) / maxAbs) * 50;
                      const pos = a.contribution >= 0;
                      return (
                        <div key={a.feature}>
                          <div className="mb-0.5 flex items-baseline justify-between gap-2">
                            <span className="text-[12px] text-muted">
                              {a.label}{" "}
                              <span className="mono text-[11px] text-dim">
                                {a.display}
                              </span>
                            </span>
                            <span
                              className={`mono text-[12px] font-semibold ${pos ? "text-red" : "text-green"}`}
                            >
                              {pos ? "+" : "−"}
                              {nf(Math.abs(a.contribution), 0)} kg
                            </span>
                          </div>
                          <div className="relative h-[7px] bg-line/70">
                            <div className="absolute top-0 bottom-0 left-1/2 w-px bg-line2" />
                            <div
                              className={`absolute top-0 bottom-0 ${pos ? "left-1/2 bg-red/75" : "right-1/2 bg-green/75"}`}
                              style={{ width: `${w}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="mono mt-3 border-t border-line pt-2 text-[11.5px] text-dim">
                    model <span className="text-fg">{fc.model}</span> · MAPE{" "}
                    {fc.metrics.mape != null ? pct(fc.metrics.mape, 2) : "—"} · MASE{" "}
                    {fc.metrics.mase != null ? nf(fc.metrics.mase, 3) : "—"} · daily
                    mean <span className="text-fg">{nf(fc.summary.daily_mean, 0)} kg</span>
                  </div>
                </>
              )}
            </Panel>

            <Panel title="Model leaderboard" right={<Badge tone="good">held-out</Badge>} bodyClass="p-0">
              {leaderboard.loading ? (
                <Loading />
              ) : (
                <>
                  <Table head={["Model", "MAPE", "MAE", "MASE", "Pinball", "Folds"]}>
                    {(leaderboard.data?.leaderboard ?? []).map((r) => (
                      <tr
                        key={r.model}
                        className={`border-b border-line/60 ${r.is_champion ? "bg-cyan/6" : ""}`}
                      >
                        <Td mono className={r.is_champion ? "text-cyan" : "text-fg"}>
                          {r.is_champion ? "★ " : ""}
                          {r.model}
                        </Td>
                        <Td mono>{nf(r.mape, 2)}%</Td>
                        <Td mono className="text-muted">{nf(r.mae, 1)}</Td>
                        <Td mono className={r.mase < 1 ? "text-green" : "text-amber"}>
                          {nf(r.mase, 3)}
                        </Td>
                        <Td mono className="text-muted">{nf(r.pinball, 1)}</Td>
                        <Td mono className="text-dim">{r.folds}</Td>
                      </tr>
                    ))}
                  </Table>

                  <div className="border-t border-line px-4 py-3">
                    <div className="label mb-1.5">This series ({pairKey})</div>
                    {pairMetrics ? (
                      <Table head={["Model", "MAPE", "MAE", "MASE", "Pinball", "Folds"]}>
                        {pairMetrics
                          .slice()
                          .sort((a, b) => a.model.localeCompare(b.model))
                          .map((r) => (
                            <tr key={r.model} className="border-b border-line/60">
                              <Td mono className="text-muted">{r.model}</Td>
                              <Td mono>{nf(r.mape, 2)}%</Td>
                              <Td mono className="text-muted">{nf(r.mae, 1)}</Td>
                              <Td mono className={r.mase < 1 ? "text-green" : "text-amber"}>
                                {nf(r.mase, 3)}
                              </Td>
                              <Td mono className="text-muted">{nf(r.pinball, 1)}</Td>
                              <Td mono className="text-dim">{r.folds}</Td>
                            </tr>
                          ))}
                      </Table>
                    ) : (
                      <div className="label">per-series metrics still warm…</div>
                    )}
                  </div>
                </>
              )}
            </Panel>
          </div>

          <Panel title="Validation & honest limitations" bodyClass="p-4">
            <div className="grid gap-4 text-[12.5px] leading-relaxed md:grid-cols-3">
              <div>
                <div className="label mb-1">Method</div>
                <p className="text-muted">
                  {leaderboard.data?.method ??
                    "expanding-window walk-forward, 3 origins × 7 days, scored per series"}
                  . Nothing after the cut point ever enters a feature.
                </p>
              </div>
              <div>
                <div className="label mb-1">Coverage</div>
                <p className="text-muted">
                  Nominal 80% intervals cover roughly{" "}
                  <span className="mono text-amber">69%</span> of held-out days —
                  under-dispersed on extreme spikes. Quantile pinball loss is the
                  honest score, not MAPE alone.
                </p>
              </div>
              <div>
                <div className="label mb-1">Data</div>
                <p className="text-muted">
                  Deterministic synthetic theatre (seed{" "}
                  <span className="mono text-cyan">20261005</span>), calibrated
                  against open-source terrain, weather and consumption patterns. No
                  real military data is used anywhere.
                </p>
              </div>
            </div>
            <div className="mono mt-4 flex flex-wrap gap-x-6 gap-y-1 border-t border-line pt-3 text-[11.5px] text-dim">
              <span>
                rows <span className="text-fg">{nf(leaderboard.data?.rows ?? 0, 0)}</span>
              </span>
              <span>
                series <span className="text-fg">{leaderboard.data?.series ?? "—"}</span>
              </span>
              <span>
                features <span className="text-fg">{leaderboard.data?.features ?? "—"}</span>
              </span>
              <span>
                train <span className="text-fg">{nf(leaderboard.data?.train_ms ?? 0, 0)} ms</span>
              </span>
              <span>
                backtest <span className="text-fg">{nf(leaderboard.data?.backtest_ms ?? 0, 0)} ms</span>
              </span>
              <span>
                history mean{" "}
                <span className="text-fg">
                  {nf(fc?.summary.history_mean_kg ?? 0, 0)} kg/d
                </span>
              </span>
              <span>
                forecast mean{" "}
                <span className="text-fg">{nf(fc?.summary.daily_mean ?? 0, 0)} kg/d</span>
              </span>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Head() {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4">
      <div>
        <div className="label">Forecast · predictive demand for forward units</div>
        <h1 className="mt-1.5 text-2xl font-bold tracking-tight">
          Forecast <span className="text-cyan">/ see the requirement before it lands</span>
        </h1>
        <p className="mt-1 max-w-3xl text-[13px] text-muted">
          Quantile gradient-boosted demand forecast, walk-forward validated and
          decomposed per feature. Move the levers — rainfall, temperature, ops
          tempo, demand — and watch the requirement move before you commit a
          convoy.
        </p>
      </div>
      <Badge tone="info">pillar 1 · demand forecasting</Badge>
    </div>
  );
}

function Note() {
  return (
    <p className="border-l-2 border-amber bg-amber/6 px-3 py-2 text-[12.5px] leading-relaxed text-muted">
      These levers feed the production forecast path — the same code the planner
      calls — so you can watch the requirement move before you commit a convoy.
    </p>
  );
}

function Slide({
  label,
  v,
  set,
  min,
  max,
  step,
}: {
  label: string;
  v: number;
  set: (n: number) => void;
  min: number;
  max: number;
  step: number;
}) {
  return (
    <label className="block">
      <div className="flex items-baseline justify-between">
        <span className="label">{label}</span>
        <span className="mono text-[12.5px] text-cyan">{v.toFixed(2)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={v}
        onChange={(e) => set(Number(e.target.value))}
        className="mt-2 w-full accent-cyan"
      />
    </label>
  );
}
