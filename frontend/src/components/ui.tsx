"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/* ── Data-loading primitive ────────────────────────────────────────── */

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

export function useLoad<T>(
  fn: () => Promise<T>,
  deps: readonly unknown[] = [],
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const fnRef = useRef(fn);

  // Keep the latest loader without making it a dependency of the run effect —
  // callers routinely pass a new inline closure on every render.
  useEffect(() => {
    fnRef.current = fn;
  });

  useEffect(() => {
    let alive = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError(null);
    fnRef
      .current()
      .then((d) => {
        if (alive) setData(d);
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}

/** Debounced value — used for text inputs feeding queries. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/* ── Formatting ────────────────────────────────────────────────────── */

export const nf = (n: number, d = 0) =>
  Number.isFinite(n)
    ? n.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d })
    : "—";

export const pct = (n: number, d = 1) => `${nf(n, d)}%`;

export const inr = (n: number) => {
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1e7) return `₹${nf(n / 1e7, 2)} Cr`;
  if (Math.abs(n) >= 1e5) return `₹${nf(n / 1e5, 2)} L`;
  return `₹${nf(n, 0)}`;
};

export const hhmm = (iso: string) => (iso ? iso.slice(11, 16) : "—");
export const ddmm = (iso: string) => (iso ? iso.slice(5, 10).replace("-", "/") : "—");

export function tone(v: number, good: number, bad: number) {
  if (v >= good) return "text-green";
  if (v <= bad) return "text-red";
  return "text-amber";
}

/* ── Presentation ──────────────────────────────────────────────────── */

export function Panel({
  title,
  right,
  children,
  className = "",
  bodyClass = "p-4",
}: {
  title?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <section className={`panel relative ${className}`}>
      {title && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="label">{title}</h2>
          {right}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  sub,
  accent = "text-fg",
  live,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  accent?: string;
  live?: boolean;
}) {
  return (
    <div className="panel stat-card px-4 py-3.5">
      <div className="flex items-center gap-2">
        <span className="label">{label}</span>
        {live && <span className="h-1.5 w-1.5 rounded-full bg-green dot-live" />}
      </div>
      <div className={`mono mt-1.5 text-[26px] leading-none font-semibold ${accent}`}>
        {value}
      </div>
      {sub && <div className="mono mt-1.5 text-[11px] text-dim">{sub}</div>}
    </div>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad" | "info";
}) {
  const map = {
    neutral: "border-line2 text-muted",
    good: "border-green/45 text-green bg-green/8",
    warn: "border-amber/45 text-amber bg-amber/8",
    bad: "border-red/45 text-red bg-red/10",
    info: "border-cyan/45 text-cyan bg-cyan/8",
  } as const;
  return (
    <span
      className={`mono inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[10px] tracking-wider uppercase ${map[tone]}`}
    >
      {children}
    </span>
  );
}

export function Bar({
  value,
  max = 100,
  color = "bg-cyan",
  height = 6,
}: {
  value: number;
  max?: number;
  color?: string;
  height?: number;
}) {
  const w = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div
      className="w-full overflow-hidden rounded-full bg-line"
      style={{ height }}
      role="presentation"
    >
      <div
        className={`h-full rounded-full transition-[width] duration-500 ${color}`}
        style={{ width: `${w}%` }}
      />
    </div>
  );
}

export function Delta({ v, unit = "%", inverse = false }: { v: number; unit?: string; inverse?: boolean }) {
  const good = inverse ? v < 0 : v > 0;
  const zero = Math.abs(v) < 1e-9;
  const cls = zero ? "text-muted" : good ? "text-green" : "text-red";
  const arrow = zero ? "→" : v > 0 ? "▲" : "▼";
  return (
    <span className={`mono text-[12px] font-semibold ${cls}`}>
      {arrow} {Math.abs(v).toFixed(1)}
      {unit}
    </span>
  );
}

export function Loading({ label = "loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 py-6">
      <div className="relative h-[3px] w-28 overflow-hidden rounded bg-line">
        <div className="sweep absolute inset-y-0 w-1/3 bg-cyan" />
      </div>
      <span className="label animate-pulse">{label}…</span>
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-center justify-between gap-4 border border-red/40 bg-red/8 px-4 py-3">
      <span className="mono text-[12px] text-red">{message}</span>
      {onRetry && (
        <button className="btn btn-danger" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ message }: { message: string }) {
  return <div className="label py-6 text-center">{message}</div>;
}

/* ── Sparkline ─────────────────────────────────────────────────────── */

export function Sparkline({
  values,
  width = 160,
  height = 34,
  color = "#374fbe",
  fill = true,
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  fill?: boolean;
}) {
  if (!values.length) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => {
    const x = (i / Math.max(1, values.length - 1)) * (width - 4) + 2;
    const y = height - 3 - ((v - min) / span) * (height - 8);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <svg width={width} height={height} className="overflow-visible">
      {fill && (
        <polygon
          points={`2,${height - 2} ${pts.join(" ")} ${width - 2},${height - 2}`}
          fill={color}
          opacity={0.12}
        />
      )}
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
      />
      <circle
        cx={pts[pts.length - 1].split(",")[0]}
        cy={pts[pts.length - 1].split(",")[1]}
        r={2.2}
        fill={color}
      />
    </svg>
  );
}

/* ── Table ─────────────────────────────────────────────────────────── */

export function Table({
  head,
  children,
  className = "",
}: {
  head: string[];
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`overflow-x-auto ${className}`}>
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-line">
            {head.map((h, i) => (
              <th
                key={`${h}-${i}`}
                className="label whitespace-nowrap px-2 py-2 font-semibold"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Td({
  children,
  className = "",
  mono = false,
}: {
  children: React.ReactNode;
  className?: string;
  mono?: boolean;
}) {
  return (
    <td
      className={`px-2 py-1.5 text-[12.5px] ${mono ? "mono" : ""} ${className}`}
    >
      {children}
    </td>
  );
}
