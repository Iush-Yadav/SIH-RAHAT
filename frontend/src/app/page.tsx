"use client";

import Link from "next/link";
import LogisticsScene from "@/components/LogisticsScene";
import TacticalMap from "@/components/TacticalMap";
import {
  Badge,
  Bar,
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
import { useTelemetry } from "@/components/Shell";
import { get } from "@/lib/api";
import type { Alert, Convoy, Health, Kpis, Theatre } from "@/lib/types";

const SEV_TONE = {
  critical: "bad",
  warning: "warn",
  info: "info",
} as const;

export default function WarRoom() {
  const tel = useTelemetry();

  const { data, error, loading, reload } = useLoad(async () => {
    const [kpis, alerts, theatre, convoys, health] = await Promise.all([
      get<Kpis>("/kpis"),
      get<{ items: Alert[] }>("/alerts"),
      get<Theatre>("/theatre"),
      get<{ items: Convoy[] }>("/convoys"),
      get<Health>("/health"),
    ]);
    return { kpis, alerts: alerts.items, theatre, convoys: convoys.items, health };
  }, []);

  // Live KPI refresh pushed over the telemetry socket.
  const liveKpis =
    tel.last && typeof tel.last.kpis === "object" && tel.last.kpis
      ? (tel.last.kpis as Kpis)
      : null;

  if (loading) return <Loading label="compiling operational picture" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return null;

  const { alerts, theatre, convoys, health } = data;
  const k = liveKpis ?? data.kpis;
  const crit = alerts.filter((a) => !a.acknowledged && a.severity === "critical");
  const riskCodes = k.unit_risk_list ?? [];

  return (
    <div className="space-y-5">
      <PageHead />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
        <Stat
          label="Units at risk"
          value={`${k.units_at_risk} / ${k.units_total}`}
          accent={k.units_at_risk ? "text-red" : "text-green"}
          sub={riskCodes.length ? riskCodes.join(" · ") : "all formations supplied"}
        />
        <Stat
          label="Fill rate (14 d)"
          value={pct(k.fill_rate_pct)}
          accent={k.fill_rate_pct >= 95 ? "text-green" : k.fill_rate_pct >= 88 ? "text-amber" : "text-red"}
          sub="requirement met across 6 units"
        />
        <Stat
          label="Network efficiency"
          value={nf(k.network_efficiency_index, 1)}
          accent="text-cyan"
          sub={`${inr(k.cost_per_tonne_km)}/t·km · corridor health`}
        />
        <Stat
          label="Convoys in motion"
          value={`${k.convoys_active} / ${k.convoys_total}`}
          sub={`${nf(k.tonnes_in_transit, 1)} t inbound`}
        />
        <Stat
          label="Sensor estate online"
          value={pct(k.sensor_online_pct, 0)}
          accent={k.sensor_online_pct >= 95 ? "text-green" : "text-amber"}
          sub="IoT gateways · last 60 s"
        />
        <Stat
          label="Open alerts"
          value={`${k.alerts_open}`}
          accent={k.alerts_critical ? "text-red" : "text-amber"}
          sub={`${k.alerts_critical} critical · unacknowledged`}
        />
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.55fr_1fr]">
        <Panel
          title="Tactical picture · forward corridor network"
          right={
            <div className="flex items-center gap-3">
              <Badge tone="info">{theatre.corridors.length} corridors</Badge>
              <Badge>{theatre.nodes.length} nodes</Badge>
            </div>
          }
          bodyClass="p-0"
        >
          <TacticalMap theatre={theatre} height={500} />
        </Panel>

        <div className="space-y-5">
          <Panel
            title="Alert board"
            right={<Badge tone={crit.length ? "bad" : "neutral"}>{crit.length} critical</Badge>}
            bodyClass="p-0"
          >
            <div className="max-h-[300px] divide-y divide-line overflow-y-auto">
              {alerts.map((a) => (
                <div key={a.id} className="flex items-start gap-3 px-4 py-2.5">
                  <span
                    className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                      a.severity === "critical"
                        ? "bg-red"
                        : a.severity === "warning"
                          ? "bg-amber"
                          : "bg-cyan"
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="mono text-[11px] text-fg">{a.node}</span>
                      <Badge tone={SEV_TONE[a.severity] ?? "neutral"}>{a.severity}</Badge>
                      <span className="mono ml-auto text-[10.5px] text-dim">
                        {a.ts.slice(11, 16)}
                      </span>
                    </div>
                    <div className="mt-0.5 text-[12.5px] leading-snug text-muted">
                      {a.message}
                    </div>
                    <div className="mt-0.5 text-[11.5px] leading-snug text-dim italic">
                      → {a.action}
                    </div>
                  </div>
                </div>
              ))}
              {!alerts.length && <div className="label p-4">no open alerts</div>}
            </div>
          </Panel>

          <Panel
            title="Days of supply · tightest lines"
            bodyClass="p-0"
            right={<Link href="/inventory" className="mono text-[11px] text-cyan hover:underline">full stock →</Link>}
          >
            <div className="px-4 py-3">
              {k.dos.slice(0, 7).map((d) => {
                const ratio = d.min_level > 0 ? (d.on_hand / d.min_level) * 100 : 100;
                return (
                  <div key={`${d.node}-${d.item}`} className="mb-3 last:mb-0">
                    <div className="mb-1 flex items-baseline justify-between gap-2">
                      <span className="mono text-[12px] text-fg">
                        {d.node}
                        <span className="ml-2 text-dim">{d.name}</span>
                      </span>
                      <span
                        className={`mono text-[12px] ${
                          ratio < 62 ? "text-red" : ratio < 85 ? "text-amber" : "text-green"
                        }`}
                      >
                        {nf(d.dos, 1)} d
                      </span>
                    </div>
                    <Bar
                      value={Math.min(ratio, 100)}
                      color={ratio < 62 ? "bg-red" : ratio < 85 ? "bg-amber" : "bg-green"}
                      height={5}
                    />
                  </div>
                );
              })}
            </div>
          </Panel>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.35fr_1fr]">
        <Panel title="Formation readiness · minimum-supply cover" bodyClass="p-0">
          <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(k.unit_days_of_supply).map(([node, days]) => {
              const toneCls = days < 7 ? "text-red" : days < 12 ? "text-amber" : "text-green";
              const bar = days < 7 ? "bg-red" : days < 12 ? "bg-amber" : "bg-green";
              return (
                <div key={node} className="border border-line bg-ink2/60 p-3">
                  <div className="flex items-baseline justify-between">
                    <span className="mono text-[13px] font-semibold text-fg">{node}</span>
                    <span className={`mono text-[15px] font-semibold ${toneCls}`}>
                      {nf(days, 1)}d
                    </span>
                  </div>
                  <div className="mt-2">
                    <Bar value={Math.min(100, (days / 30) * 100)} color={bar} height={5} />
                  </div>
                  <div className="label mt-1.5">worst-case line</div>
                </div>
              );
            })}
          </div>
        </Panel>

        <Panel
          title="Convoy board"
          right={<Badge tone="info">{convoys.filter((c) => c.status === "in_transit" || c.status === "loading").length} moving</Badge>}
          bodyClass="p-0"
        >
          <Table head={["Convoy", "Leg", "Load", "Distance", "Status", "Risk"]}>
            {convoys.slice(0, 8).map((c) => (
              <tr key={c.code} className="border-b border-line/60 hover:bg-panel2/60">
                <Td mono className="text-cyan">{c.code}</Td>
                <Td mono>
                  {c.origin} <span className="text-dim">→</span> {c.dest}
                </Td>
                <Td mono>
                  {nf(c.load_t, 1)} t
                  <span className="text-dim"> / {nf(c.capacity_t, 0)} t</span>
                </Td>
                <Td mono className="text-muted">{nf(c.distance_km, 1)} km</Td>
                <Td>
                  <Badge
                    tone={
                      c.status === "in_transit"
                        ? "good"
                        : c.status === "held"
                          ? "bad"
                          : c.status === "loading"
                            ? "info"
                            : "neutral"
                    }
                  >
                    {c.status.replace("_", " ")}
                  </Badge>
                </Td>
                <Td mono className={c.risk_score > 0.6 ? "text-red" : c.risk_score > 0.35 ? "text-amber" : "text-green"}>
                  {(c.risk_score * 100).toFixed(0)}%
                </Td>
              </tr>
            ))}
          </Table>
        </Panel>
      </div>

      <div className="mono flex flex-wrap items-center justify-between gap-3 border border-line bg-panel px-4 py-2.5 text-[11px] text-dim">
        <span>
          model <span className="text-cyan">{health.model.status}</span> ·{" "}
          {nf(health.model.rows, 0)} training rows · {health.model.series} series ·{" "}
          {health.model.features} features · trained in {nf(health.model.train_ms, 0)} ms
        </span>
        <span>
          champion{" "}
          <span className="text-cyan">
            {health.model.leaderboard?.find((l) => l.is_champion)?.model}
          </span>{" "}
          · MAPE {health.model.leaderboard?.find((l) => l.is_champion)?.mape}% ·{" "}
          <Link href="/forecast" className="text-cyan hover:underline">
            explainability →
          </Link>
        </span>
      </div>
    </div>
  );
}

function PageHead() {
  return <section className="editorial-hero">
    <div className="hero-copy">
      <div className="label">01 / Overview · Synthetic demonstration</div>
      <h1>The whole picture.<br /><span style={{color:"#b64129",fontFamily:"Georgia, serif",fontStyle:"italic",fontWeight:400}}>Every connection.</span></h1>
      <p className="mt-4 text-muted">Your inventory, network and sensor estate, brought together in one considered workspace.</p>
      <div className="hero-actions"><Link href="/inventory" className="btn btn-primary">Explore inventory ↗</Link><Link href="/reports" className="btn">View evidence →</Link></div>
    </div>
    <div className="hero-art"><LogisticsScene /><span className="art-caption">RAHAT / THE CONNECTED SUPPLY CHAIN</span></div>
  </section>;
}
