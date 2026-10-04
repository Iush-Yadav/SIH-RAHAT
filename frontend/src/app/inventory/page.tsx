"use client";

import { useMemo, useState } from "react";
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
  nf,
  pct,
  useLoad,
} from "@/components/ui";
import { useSession, useTelemetry } from "@/components/Shell";
import { get, post } from "@/lib/api";
import type { Alert, InventoryResponse, InventoryRow, SensorsResponse } from "@/lib/types";

export default function InventoryPage() {
  const { user } = useSession();
  const tel = useTelemetry();
  const [node, setNode] = useState("");
  const [cat, setCat] = useState("");
  const [showAll, setShowAll] = useState(false);

  const catalog = useLoad(() => get<InventoryResponse>("/inventory"), []);
  const inv = useLoad(() => {
    const qs = new URLSearchParams();
    if (node) qs.set("node", node);
    if (cat) qs.set("category", cat);
    const q = qs.toString();
    return get<InventoryResponse>(`/inventory${q ? `?${q}` : ""}`);
  }, [node, cat]);
  const sensors = useLoad(() => get<SensorsResponse>("/sensors"), []);
  const alerts = useLoad(() => get<{ items: Alert[]; open: number }>("/alerts"), []);

  const [ackError, setAckError] = useState<string | null>(null);
  const [acked, setAcked] = useState<number[]>([]);
  const canAck = user?.perms.includes("acknowledge") || user?.perms.includes("admin");

  const ack = async (id: number) => {
    setAckError(null);
    try {
      await post(`/alerts/${id}/ack`, {});
      setAcked((a) => [...a, id]);
      alerts.reload();
    } catch (error) {
      setAckError(error instanceof Error ? error.message : "Could not acknowledge alert. Try again.");
    }
  };

  // Live frame pushed over the telemetry socket.
  const liveFrame =
    tel.last && tel.last.type === "frame"
      ? ((tel.last.nodes as SensorsResponse["nodes"]) ?? null)
      : null;

  // Memoised so the derived hooks below have a stable dependency.
  const rows = useMemo(() => inv.data?.items ?? [], [inv.data]);
  const filtered = showAll ? rows : rows.slice(0, 60);

  const counts = useMemo(() => {
    const c: Record<InventoryRow["status"], number> = { critical: 0, low: 0, ok: 0 };
    for (const r of rows) c[r.status] += 1;
    return c;
  }, [rows]);

  const categories = useMemo(
    () => [...new Set((catalog.data?.items ?? []).map((r) => r.category))].sort(),
    [catalog.data],
  );

  const sensorRows = liveFrame ?? sensors.data?.nodes ?? [];

  return (
    <div className="space-y-5">
      <Head />
      {ackError && <ErrorBox message={ackError} />}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
        <Stat label="Stock lines" value={nf(inv.data?.count ?? 0, 0)} sub="node × commodity" />
        <Stat
          label="Critical lines"
          value={nf(counts.critical, 0)}
          accent={counts.critical ? "text-red" : "text-green"}
          sub="< 6 days of supply"
        />
        <Stat
          label="Low lines"
          value={nf(counts.low, 0)}
          accent={counts.low ? "text-amber" : "text-green"}
          sub="6 – 9 days of supply"
        />
        <Stat
          label="Sensors online"
          value={pct(sensors.data?.online_pct ?? 0, 0)}
          accent={(sensors.data?.online_pct ?? 0) >= 95 ? "text-green" : "text-amber"}
          sub="simulated gateways · local bus"
        />
        <Stat
          label="Telemetry ticks"
          value={nf(sensors.data?.ticks ?? 0, 0)}
          accent="text-cyan"
          sub={`${sensors.data?.clients ?? 0} live socket client(s)`}
        />
        <Stat
          label="Open alerts"
          value={nf(alerts.data?.open ?? 0, 0)}
          accent={(alerts.data?.open ?? 0) ? "text-amber" : "text-green"}
          sub="acknowledgement gated by role"
        />
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.45fr_1fr]">
        <Panel
          title="Stock ledger"
          right={
            <div className="flex items-center gap-2">
              <select aria-label="Filter by location" className="select w-28 py-1" value={node} onChange={(e) => setNode(e.target.value)}>
                <option value="">all nodes</option>
                {["RH-01", "DP-A", "AF-01", "DP-CT", "DP-B", "U-12", "U-63", "U-21", "U-47", "U-34", "U-56"].map(
                  (n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ),
                )}
              </select>
              <select aria-label="Filter by category" className="select w-32 py-1" value={cat} onChange={(e) => setCat(e.target.value)}>
                <option value="">all categories</option>
                {categories.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
          }
          bodyClass="p-0"
        >
          {inv.loading ? (
            <Loading />
          ) : inv.error ? (
            <ErrorBox message={inv.error} onRetry={inv.reload} />
          ) : rows.length === 0 ? (
            <Empty message="no stock lines match this filter" />
          ) : (
            <>
              <Table
                head={["Node", "Item", "On hand", "Min", "In transit", "Daily", "DoS", "Cover"]}
              >
                {filtered.map((r) => (
                  <tr key={`${r.node}-${r.item}`} className="border-b border-line/60 hover:bg-panel2/60">
                    <Td mono className="text-cyan">{r.node}</Td>
                    <Td>
                      <span className="mono text-[12px]">{r.item}</span>
                      <span className="ml-2 text-[11.5px] text-dim">{r.name}</span>
                    </Td>
                    <Td mono className="text-fg">{nf(r.on_hand, 0)}</Td>
                    <Td mono className="text-dim">{nf(r.min_level, 0)}</Td>
                    <Td mono className="text-muted">{nf(r.in_transit, 0)}</Td>
                    <Td mono className="text-muted">{nf(r.daily_rate, 0)}</Td>
                    <Td
                      mono
                      className={
                        r.status === "critical"
                          ? "text-red"
                          : r.status === "low"
                            ? "text-amber"
                            : "text-green"
                      }
                    >
                      {r.dos_days >= 999 ? "∞" : nf(r.dos_days, 1)}
                    </Td>
                    <Td className="w-40">
                      <div className="flex items-center gap-2">
                        <Bar
                          value={Math.min(r.fill_pct, 100)}
                          color={
                            r.status === "critical"
                              ? "bg-red"
                              : r.status === "low"
                                ? "bg-amber"
                                : "bg-green"
                          }
                          height={5}
                        />
                        <span className="mono w-12 shrink-0 text-[11px] text-dim">
                          {pct(r.fill_pct, 0)}
                        </span>
                      </div>
                    </Td>
                  </tr>
                ))}
              </Table>
              <div className="flex items-center justify-between border-t border-line px-4 py-2.5">
                <span className="mono text-[11.5px] text-dim">
                  showing {filtered.length} of {rows.length} lines
                  {node || cat ? " (filtered)" : ""}
                </span>
                {rows.length > 60 && (
                  <button className="btn py-1" onClick={() => setShowAll((s) => !s)}>
                    {showAll ? "show fewer" : `show all ${rows.length}`}
                  </button>
                )}
              </div>
            </>
          )}
        </Panel>

        <div className="space-y-5">
          <Panel
            title="IoT sensor estate"
            right={<Badge tone="info">{sensorRows.length} nodes</Badge>}
            bodyClass="p-4"
          >
            {sensors.loading ? (
              <Loading label="polling gateways" />
            ) : sensorRows.length === 0 ? (
              <Empty message="waiting for the first telemetry frame…" />
            ) : (
              <div className="grid gap-2.5 sm:grid-cols-2">
                {sensorRows.map((s) => {
                  const batt = s.battery ?? s.battery_pct ?? 100;
                  return (
                    <div
                      key={s.node_id}
                      className={`border p-2.5 ${
                        s.online ? "border-line bg-ink2/60" : "border-red/45 bg-red/6"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="mono text-[12px] font-semibold text-fg">
                          {s.code}
                        </span>
                        <span
                          className={`mono text-[10px] uppercase ${s.online ? "text-green" : "text-red"}`}
                        >
                          {s.online ? "● online" : "○ offline"}
                        </span>
                      </div>
                      <div className="mono mt-1 text-[11px] text-dim">{s.gateway}</div>

                      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11.5px]">
                        <Kv k="pallet" v={`${nf(s.weight ?? 0, 0)} kg`} />
                        <Kv k="temp" v={`${nf(s.temp ?? 0, 1)} °C`} />
                        <Kv k="RH" v={`${nf(s.humidity ?? 0, 1)} %`} />
                        <Kv
                          k="battery"
                          v={`${nf(batt, 0)} %`}
                          tone={batt < 25 ? "text-red" : batt < 50 ? "text-amber" : "text-green"}
                        />
                      </div>

                      <div className="mono mt-2 flex items-center justify-between text-[10.5px] text-dim">
                        <span>{s.protocol ?? "MQTT"}</span>
                        <span>RSSI {nf(s.signal ?? s.signal_dbm ?? -70, 0)} dBm</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="mt-4 border-t border-line pt-3">
              <div className="label mb-1.5">Simulated MQTT-format stream · rahat/&#123;gateway&#125;/&#123;kind&#125;</div>
              <div className="mono space-y-0.5 text-[11px]">
                {(sensors.data?.mqtt ?? []).slice(-8).map((line, i) => (
                  <div key={i} className="text-dim">
                    <span className="text-cyan">{line.split(" ")[0]}</span>{" "}
                    {line.split(" ")[1]}
                  </div>
                ))}
                {!sensors.data?.mqtt?.length && <div className="text-dim">quiet</div>}
              </div>
              <div className="mono mt-2 text-[11px] text-dim">
                uptime {nf((sensors.data?.uptime_s ?? 0) / 60, 1)} min · payload
                persisted to SQLite every N ticks · external broker adapter not connected
              </div>
            </div>
          </Panel>

          <Panel title="Alert board" right={<Badge tone={alerts.data?.open ? "warn" : "good"}>
            {alerts.data?.open ?? 0} open
          </Badge>} bodyClass="p-0">
            {alerts.loading ? (
              <Loading />
            ) : (alerts.data?.items.length ?? 0) === 0 ? (
              <Empty message="no alerts" />
            ) : (
              <div className="max-h-[330px] divide-y divide-line overflow-y-auto">
                {alerts.data?.items.map((a) => (
                  <div key={a.id} className="px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <Badge
                        tone={
                          a.severity === "critical"
                            ? "bad"
                            : a.severity === "warning"
                              ? "warn"
                              : "info"
                        }
                      >
                        {a.severity}
                      </Badge>
                      <span className="mono text-[11.5px] text-cyan">{a.node ?? "—"}</span>
                      <span className="mono text-[11px] text-dim">{a.type}</span>
                      <span className="mono ml-auto text-[10.5px] text-dim">
                        {a.ts.slice(11, 16)}
                      </span>
                    </div>
                    <div className="mt-1 text-[12.5px] leading-snug text-muted">{a.message}</div>
                    <div className="mt-1 flex items-center justify-between gap-3">
                      <span className="text-[11.5px] text-dim italic">→ {a.action}</span>
                      {a.acknowledged || acked.includes(a.id) ? (
                        <span className="mono text-[10.5px] text-green">✓ acknowledged</span>
                      ) : canAck ? (
                        <button className="btn py-0.5" onClick={() => void ack(a.id)}>
                          ack
                        </button>
                      ) : (
                        <span className="mono text-[10.5px] text-dim">
                          {user?.role_label} cannot ack
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Kv({ k, v, tone = "text-fg" }: { k: string; v: string; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-1">
      <span className="text-[10.5px] tracking-wider text-dim uppercase">{k}</span>
      <span className={`mono ${tone}`}>{v}</span>
    </div>
  );
}

function Head() {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4">
      <div>
        <div className="label">Stock &amp; IoT · custody of every pallet</div>
        <h1 className="mt-1.5 text-2xl font-bold tracking-tight">
          Inventory <span className="text-cyan">/ what is actually on the ground</span>
        </h1>
        <p className="mt-1 max-w-3xl text-[13px] text-muted">
          Ledger, days-of-supply and live pallet sensors in one view. Sensor frames
          arrive over the telemetry socket; stock levels are the same rows the
          forecasting model reads.
        </p>
      </div>
      <Badge tone="info">pillar 3 · IoT tracking</Badge>
    </div>
  );
}
