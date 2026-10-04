"use client";

import { useState } from "react";
import type { Point } from "@/lib/types";
import { nf } from "@/components/ui";

interface Props {
  series: Point[];
  height?: number;
}

/**
 * History (solid) + quantile fan (p10/p90) + p50 path, with a hard divider at
 * "today" so the operator can see where observation stops and prediction starts.
 */
export default function ForecastChart({ series, height = 320 }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  if (!series.length) return null;

  const W = 900;
  const H = height;
  const padL = 54;
  const padR = 16;
  const padT = 16;
  const padB = 34;

  const hist = series.filter((p) => p.history);
  const fut = series.filter((p) => !p.history);
  const lastHistIdx = hist.length - 1;

  const values: number[] = [];
  for (const p of series) {
    if (p.actual != null) values.push(p.actual);
    if (p.p90 != null) values.push(p.p90);
    if (p.p50 != null) values.push(p.p50);
  }
  const yMax = Math.max(...values, 1) * 1.12;
  const yMin = 0;

  const n = series.length;
  const x = (i: number) => padL + (i / Math.max(1, n - 1)) * (W - padL - padR);
  const y = (v: number) =>
    H - padB - ((v - yMin) / Math.max(1e-9, yMax - yMin)) * (H - padT - padB);

  const histPts = hist
    .map((p, i) => `${x(i).toFixed(1)},${y(p.actual ?? 0).toFixed(1)}`)
    .join(" ");

  const fwdIdx = hist.length;
  const p50Pts = fut
    .map((p, i) => `${x(fwdIdx + i).toFixed(1)},${y(p.p50 ?? 0).toFixed(1)}`)
    .join(" ");
  const upper = fut
    .map((p, i) => `${x(fwdIdx + i).toFixed(1)},${y(p.p90 ?? 0).toFixed(1)}`)
    .join(" ");
  const lower = [...fut]
    .reverse()
    .map((p, i) =>
      `${x(fwdIdx + fut.length - 1 - i).toFixed(1)},${y(p.p10 ?? 0).toFixed(1)}`,
    )
    .join(" ");

  const ticks = 5;
  const gridVals = Array.from({ length: ticks + 1 }, (_, i) => (yMax / ticks) * i);

  const hv = hover != null ? series[hover] : null;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id="fanGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#374fbe" stopOpacity={0.32} />
            <stop offset="100%" stopColor="#374fbe" stopOpacity={0.06} />
          </linearGradient>
        </defs>

        {/* grid */}
        {gridVals.map((v) => (
          <g key={v}>
            <line
              x1={padL}
              y1={y(v)}
              x2={W - padR}
              y2={y(v)}
              stroke="#c7cfbd"
              strokeWidth={1}
            />
            <text
              x={padL - 8}
              y={y(v) + 4}
              textAnchor="end"
              className="mono"
              fontSize={11}
              fill="#63705b"
            >
              {nf(v, 0)}
            </text>
          </g>
        ))}

        {/* today divider */}
        {lastHistIdx >= 0 && (
          <g>
            <line
              x1={x(lastHistIdx)}
              y1={padT}
              x2={x(lastHistIdx)}
              y2={H - padB}
              stroke="#96620d"
              strokeWidth={1.5}
              strokeDasharray="4 4"
            />
            <text
              x={x(lastHistIdx) + 5}
              y={padT + 12}
              className="mono"
              fontSize={10.5}
              fill="#96620d"
            >
              TODAY
            </text>
          </g>
        )}

        {/* uncertainty fan */}
        {fut.length > 0 && (
          <polygon
            points={`${upper} ${lower}`}
            fill="url(#fanGrad)"
            stroke="none"
          />
        )}

        {/* historical actuals */}
        <polyline
          points={histPts}
          fill="none"
          stroke="#576651"
          strokeWidth={1.6}
          strokeLinejoin="round"
        />

        {/* p50 forecast */}
        <polyline
          points={p50Pts}
          fill="none"
          stroke="#374fbe"
          strokeWidth={2.2}
          strokeLinejoin="round"
        />

        {/* hover guide */}
        {hover != null && (
          <g>
            <line
              x1={x(hover)}
              y1={padT}
              x2={x(hover)}
              y2={H - padB}
              stroke="#293c2d"
              strokeWidth={1}
              opacity={0.5}
            />
            <circle
              cx={x(hover)}
              cy={y((hv?.actual ?? hv?.p50) ?? 0)}
              r={4}
              fill={hv?.history ? "#576651" : "#374fbe"}
              stroke="#ecefe4"
              strokeWidth={1.5}
            />
          </g>
        )}

        {/* x hit zones */}
        {series.map((_, i) => (
          <rect
            key={i}
            x={x(i) - (W / n) / 2}
            y={padT}
            width={W / n}
            height={H - padT - padB}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}

        {/* x labels */}
        {[0, Math.floor(n / 3), Math.floor((2 * n) / 3), n - 1].map((i) => (
          <text
            key={i}
            x={x(i)}
            y={H - 12}
            textAnchor="middle"
            className="mono"
            fontSize={10.5}
            fill="#63705b"
          >
            {series[i]?.day.slice(5)}
          </text>
        ))}
      </svg>

      <div className="mono absolute top-2 right-3 flex gap-3 text-[10.5px]">
        <span className="text-muted">— actual</span>
        <span className="text-cyan">— p50</span>
        <span className="text-cyan/70">▨ p10–p90</span>
      </div>

      {hv && (
        <div className="mono pointer-events-none absolute top-2 left-3 border border-line bg-ink2/95 px-3 py-2 text-[11.5px]">
          <div className="text-cyan">{hv.day}</div>
          <div className="text-muted">
            {hv.history
              ? `actual ${nf(hv.actual ?? 0, 1)} kg`
              : `p50 ${nf(hv.p50 ?? 0, 1)} kg · p10 ${nf(hv.p10 ?? 0, 1)} · p90 ${nf(hv.p90 ?? 0, 1)}`}
          </div>
        </div>
      )}
    </div>
  );
}
