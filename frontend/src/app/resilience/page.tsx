"use client";

import { useMemo, useState } from "react";
import TacticalMap from "@/components/TacticalMap";
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
import { get } from "@/lib/api";
import type { Fragility, StressCurve, Theatre } from "@/lib/types";

const SEV_TONE = {
  critical: "bad",
  high: "warn",
  medium: "info",
  low: "neutral",
} as const;

export default function ResiliencePage() {
  const frag = useLoad(() => get<Fragility>("/resilience/fragility"), []);
  const stress = useLoad(() => get<StressCurve>("/resilience/stress?max_failures=6"), []);
  const theatre = useLoad(() => get<Theatre>("/theatre"), []);
  const [sel, setSel] = useState<string | null>(null);

  const corridors = useMemo(() => frag.data?.corridors ?? [], [frag.data]);
  const top = useMemo(() => corridors.slice(0, 8), [corridors]);
  const points = stress.data?.points ?? [];

  return (
    <div className="space-y-5">
      <Head />

      {frag.error && <ErrorBox message={frag.error} onRetry={frag.reload} />}
      {stress.error && <ErrorBox message={stress.error} onRetry={stress.reload} />}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Base network efficiency"
          value={pct(frag.data?.base_efficiency ?? 0, 1)}
          accent="text-cyan"
          sub="shortest-risk-adjusted depot cover"
        />
        <Stat
          label="Single points of failure"
          value={nf(frag.data?.single_points.length ?? 0, 0)}
          accent={(frag.data?.single_points.length ?? 0) ? "text-red" : "text-green"}
          sub="corridors whose loss isolates a unit"
        />
        <Stat
          label="Vulnerable formations"
          value={nf(frag.data?.nodes.filter((n) => n.vulnerable).length ?? 0, 0)}
          accent="text-amber"
          sub="≤ 1 all-weather axis or a sole axis"
        />
        <Stat
          label="First isolation at"
          value={stress.data?.critical_threshold ? `${stress.data.critical_threshold} loss` : "—"}
          accent="text-red"
          sub="greedy worst-case closure sequence"
        />
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.5fr_1fr]">
        <Panel
          title="Corridor fragility ranking · blast radius"
          right={<Badge tone="neutral">{corridors.length} corridors · {frag.data?.compute_ms ?? 0} ms</Badge>}
          bodyClass="p-0"
        >
          {frag.loading ? (
            <Loading label="closing every corridor in turn" />
          ) : (
            <Table head={["#", "Corridor", "Class", "Lost units", "Detour km", "Eff. drop", "Severity"]}>
              {top.map((c, i) => (
                <tr
                  key={c.code}
                  onClick={() => setSel(sel === c.code ? null : c.code)}
                  className={`cursor-pointer border-b border-line/60 hover:bg-panel2/60 ${
                    sel === c.code ? "bg-cyan/10" : ""
                  }`}
                >
                  <Td mono className="text-dim">{i + 1}</Td>
                  <Td>
                    <span className="mono text-[12.5px] text-cyan">{c.code}</span>
                    <span className="ml-2 text-[11.5px] text-dim">{c.name}</span>
                  </Td>
                  <Td mono className="text-muted">
                    {c.road_class}
                    {c.all_weather ? "" : " · fair"}
                  </Td>
                  <Td mono className={c.blast_radius ? "text-red" : "text-green"}>
                    {c.blast_radius ? c.units_lost.join(", ") : "none"}
                  </Td>
                  <Td mono className="text-muted">{nf(c.detour_km, 1)}</Td>
                  <Td mono className="text-amber">{pct(c.efficiency_drop_pct, 1)}</Td>
                  <Td>
                    <Badge tone={SEV_TONE[c.severity]}>{c.severity}</Badge>
                  </Td>
                </tr>
              ))}
            </Table>
          )}
          <div className="border-t border-line px-4 py-2.5">
            <span className="mono text-[11.5px] text-dim">
              click a row to isolate it on the map — {sel ?? "nothing selected"}
            </span>
          </div>
        </Panel>

        <Panel
          title="Stress test · greedy worst-case sequence"
          right={
            <Badge tone={stress.data?.critical_threshold ? "warn" : "good"}>
              {points.length} points
            </Badge>
          }
          bodyClass="p-4"
        >
          {stress.loading ? (
            <Loading label="growing the failure set" />
          ) : points.length ? (
            <>
              <StressChart points={points} threshold={stress.data?.critical_threshold ?? null} />
              <div className="mt-3 divide-y divide-line border-t border-line">
                {points.map((p) => (
                  <div key={p.failed} className="flex items-center gap-3 py-1.5">
                    <span className="mono w-8 text-[11.5px] text-dim">
                      {p.failed} ✕
                    </span>
                    <span className="mono min-w-0 flex-1 truncate text-[11.5px] text-muted">
                      {p.closed.length ? p.closed.join(" ") : "nominal"}
                    </span>
                    <span
                      className={`mono text-[12px] ${
                        p.unreachable ? "text-red" : "text-green"
                      }`}
                    >
                      {p.efficiency_pct.toFixed(1)}%
                    </span>
                    <span className="mono w-14 text-right text-[11.5px] text-dim">
                      {p.unreachable} lost
                    </span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <Empty message="stress curve unavailable" />
          )}
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.5fr_1fr]">
        <Panel title="Fragility on the map" bodyClass="p-0">
          {theatre.loading ? (
            <Loading />
          ) : theatre.data ? (
            <TacticalMap
              theatre={theatre.data}
              blocked={sel ? [sel] : []}
              selected={sel}
              onSelectCorridor={(code) => setSel(sel === code ? null : code)}
              dimUnhighlighted={false}
              height={470}
            />
          ) : null}
        </Panel>

        <Panel title="Formation redundancy · axes out of each unit" bodyClass="p-0">
          {frag.loading ? (
            <Loading />
          ) : (
            <Table head={["Unit", "Axes", "All-weather", "Sole axis", "Status"]}>
              {(frag.data?.nodes ?? []).map((n) => (
                <tr key={n.node} className="border-b border-line/60">
                  <Td mono className="text-cyan">{n.node}</Td>
                  <Td mono>{n.axes}</Td>
                  <Td
                    mono
                    className={n.all_weather_axes <= 1 ? "text-red" : "text-green"}
                  >
                    {n.all_weather_axes}
                  </Td>
                  <Td mono className="text-amber">{n.sole_axis ?? "—"}</Td>
                  <Td>
                    <Badge tone={n.vulnerable ? "bad" : "good"}>
                      {n.vulnerable ? "vulnerable" : "redundant"}
                    </Badge>
                  </Td>
                </tr>
              ))}
            </Table>
          )}
        </Panel>
      </div>

      <Panel title="What the index means" bodyClass="p-4">
        <div className="grid gap-4 text-[12.5px] leading-relaxed md:grid-cols-3">
          <div>
            <div className="label mb-1">Blast radius</div>
            <p className="text-muted">
              Close one corridor, re-run coverage from every depot, and count what is
              cut off plus what has to detour. That is the fragility ranking — not a
              static risk score.
            </p>
          </div>
          <div>
            <div className="label mb-1">Stress curve</div>
            <p className="text-muted">
              Repeatedly close whichever single corridor hurts most at that step.
              The efficiency line is smooth until it isn&apos;t — that knee is the
              number a commander needs before an operation.
            </p>
          </div>
          <div>
            <div className="label mb-1">Composite index</div>
            <p className="text-muted">
              Edge connectivity, all-weather redundancy and reachability combined
              into one 0–100 figure on the War Room. Higher means the network
              absorbs more failure before supply stops.
            </p>
          </div>
        </div>
      </Panel>
    </div>
  );
}

function StressChart({
  points,
  threshold,
}: {
  points: StressCurve["points"];
  threshold: number | null;
}) {
  const W = 420;
  const H = 180;
  const padL = 40;
  const padB = 26;
  const padT = 12;
  const n = points.length;
  const x = (i: number) => padL + (i / Math.max(1, n - 1)) * (W - padL - 14);
  const y = (v: number) => H - padB - (v / 100) * (H - padT - padB);

  const pts = points.map((p, i) => `${x(i).toFixed(1)},${y(p.efficiency_pct).toFixed(1)}`).join(" ");
  const area = `${padL},${y(0)} ${pts} ${x(n - 1)},${y(0)}`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={180}>
      {[0, 25, 50, 75, 100].map((v) => (
        <g key={v}>
          <line x1={padL} y1={y(v)} x2={W - 14} y2={y(v)} stroke="#1b2940" strokeWidth={1} />
          <text x={padL - 6} y={y(v) + 4} textAnchor="end" className="mono" fontSize={9.5} fill="#5b6d88">
            {v}
          </text>
        </g>
      ))}
      <polygon points={area} fill="#35e0ff" opacity={0.1} />
      <polyline points={pts} fill="none" stroke="#35e0ff" strokeWidth={2} strokeLinejoin="round" />
      {points.map((p, i) => (
        <g key={p.failed}>
          <circle
            cx={x(i)}
            cy={y(p.efficiency_pct)}
            r={p.unreachable ? 4 : 3}
            fill={p.unreachable ? "#ff4d5e" : "#35e0ff"}
          />
          <text x={x(i)} y={H - 8} textAnchor="middle" className="mono" fontSize={9.5} fill="#5b6d88">
            {p.failed}
          </text>
        </g>
      ))}
      {threshold != null && (
        <g>
          <line
            x1={x(threshold)}
            y1={padT}
            x2={x(threshold)}
            y2={H - padB}
            stroke="#ff4d5e"
            strokeWidth={1.2}
            strokeDasharray="3 3"
          />
          <text x={x(threshold) + 4} y={padT + 10} className="mono" fontSize={9.5} fill="#ff4d5e">
            isolation begins
          </text>
        </g>
      )}
      <text x={W - 14} y={H - 8} textAnchor="end" className="mono" fontSize={9.5} fill="#5b6d88">
        corridors closed →
      </text>
    </svg>
  );
}

function Head() {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4">
      <div>
        <div className="label">Resilience · what breaks if the network breaks</div>
        <h1 className="mt-1.5 text-2xl font-bold tracking-tight">
          Resilience <span className="text-cyan">/ fragility &amp; stress testing</span>
        </h1>
        <p className="mt-1 max-w-3xl text-[13px] text-muted">
          Every corridor is closed in turn and the coverage recomputed from scratch.
          What comes back is a ranking, a redundancy view and a knee in the curve —
          the three things that decide whether a forward unit survives a cut.
        </p>
      </div>
      <Badge tone="info">pillar 4 · integrated system</Badge>
    </div>
  );
}
