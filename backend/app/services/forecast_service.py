"""Forecast service: builds the pooled dataset, trains the models, and turns a
(node, item) query into a calibrated p10/p50/p90 series plus an *exact*
feature-attribution narrative.

Training is heavy-ish for a pure-numpy booster, so it happens exactly once on a
background thread at process start. Subsequent requests are pure prediction.

Two things matter for correctness and both are easy to get wrong:

* **Everything is scale-invariant.** The booster is fit on ``y / run-rate`` and
  on features divided by the same run-rate, so one pooled model serves a depot's
  diesel draw and a small unit's antibiotic draw without regressing towards
  whichever is bigger.
* **Prediction is recursive.** Each step feeds its own p50 back into the lag
  features, which is exactly how the numbers are consumed by the stockout
  projection in MISSION SIM. A non-recursive forecast would look better on a
  chart and be wrong in the plan.
"""

from __future__ import annotations

import threading
import time
import zlib
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from .. import repository as repo
from ..config import settings
from ..domain.forecast import (
    FEATURE_NAMES,
    SCALE_IDX,
    GBMQuantile,
    Ridge,
    build_row,
    mape,
    mase,
    predict_recursive,
    seasonal_naive_forecast,
    series_scale,
    standardize_features,
    walk_forward_backtest,
)

HISTORY_DAYS = settings.history_days  # 112 observed days, indices 0..111
TODAY = date(2026, 10, 3)

# Human phrasing for every engineered feature, split into drivers that move
# within a horizon (weather/ops/rhythm) and structural baseline terms.
_PHRASES: dict[str, tuple[str, str]] = {
    "qty_rollmean7": ("7-day consumption run-rate", "dynamic"),
    "qty_rollmean14": ("14-day consumption run-rate", "dynamic"),
    "qty_rollstd7": ("recent consumption volatility", "dynamic"),
    "qty_lag1": ("yesterday's actual draw", "dynamic"),
    "qty_lag2": ("draw 2 days ago", "dynamic"),
    "qty_lag3": ("draw 3 days ago", "dynamic"),
    "qty_lag7": ("draw 7 days ago", "dynamic"),
    "qty_lag14": ("draw 14 days ago", "dynamic"),
    "qty_lag21": ("draw 21 days ago", "dynamic"),
    "rainfall_mm": ("today's rainfall", "weather"),
    "rain_lag3": ("3-day accumulated rainfall", "weather"),
    "rain_lag7": ("7-day accumulated rainfall", "weather"),
    "temp_c": ("mean temperature (heating load)", "weather"),
    "ops_flag": ("field-exercise activity", "ops"),
    "tempo": ("operational tempo", "ops"),
    "dow_sin": ("day-of-week rhythm", "season"),
    "dow_cos": ("day-of-week rhythm", "season"),
    "doy_sin": ("seasonal position", "season"),
    "doy_cos": ("seasonal position", "season"),
    "personnel_log": ("unit strength", "structure"),
    "isolation_km": ("supply-line isolation", "structure"),
    "elevation_m": ("node altitude", "structure"),
    "is_critical": ("item criticality", "structure"),
    "cat_ration": ("baseline ration demand", "structure"),
    "cat_pol": ("baseline POL demand", "structure"),
    "cat_ammo": ("baseline ammunition demand", "structure"),
    "cat_medical": ("baseline medical demand", "structure"),
    "cat_water": ("baseline water demand", "structure"),
    "cat_maintenance": ("baseline maintenance demand", "structure"),
    "cat_sundry": ("baseline sundry demand", "structure"),
}

# Level features are reported in kg/day; everything else is unitless.
_UNIT = {
    "qty_rollmean7": " kg", "qty_rollmean14": " kg", "qty_rollstd7": " kg",
    "qty_lag1": " kg", "qty_lag2": " kg", "qty_lag3": " kg", "qty_lag7": " kg",
    "qty_lag14": " kg", "qty_lag21": " kg",
    "rainfall_mm": " mm", "rain_lag3": " mm", "rain_lag7": " mm",
    "temp_c": " C", "personnel_log": "", "isolation_km": " km",
    "elevation_m": " m", "tempo": " (0-2)", "ops_flag": "",
}


@dataclass
class ModelBundle:
    X: np.ndarray
    y: np.ndarray
    groups: np.ndarray
    day_idx: np.ndarray
    pairs: list[tuple[str, str]]
    node_meta: dict[str, dict]
    item_meta: dict[str, dict]
    ctxs: list[dict] = field(default_factory=list)
    ctx_by_label: dict[str, dict] = field(default_factory=dict)
    history: dict[str, np.ndarray] = field(default_factory=dict)
    doy: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))
    day_labels: list[str] = field(default_factory=list)
    models: dict[float, GBMQuantile] = field(default_factory=dict)
    ridge: Ridge | None = None
    leaderboard: list[dict] = field(default_factory=list)
    per_pair: dict[str, dict] = field(default_factory=dict)
    trained_at: float = 0.0
    train_ms: float = 0.0
    backtest_ms: float = 0.0
    rows: int = 0
    status: str = "cold"
    error: str = ""


_bundle: ModelBundle | None = None
_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Weather outlook (what the model sees beyond the observed window)
# --------------------------------------------------------------------------- #
def _climate_envelope(doy: float) -> float:
    monsoon = 9.5 * np.exp(-(((doy - 196.0) ** 2) / (2 * 46.0 ** 2)))
    western = 1.4 * np.exp(-(((doy - 40.0) ** 2) / (2 * 30.0 ** 2)))
    return float(monsoon + western)


def weather_outlook(node: dict, horizon: int, *, rainfall_mult: float = 1.0,
                    temp_offset: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic forecast of rainfall and mean temperature.

    Uses ``zlib.crc32`` rather than builtin ``hash`` for the per-node seed:
    builtin string hashing is randomised per interpreter, which would have made
    every rehearsal produce a subtly different theatre.
    """
    elev = node["elevation_m"]
    spatial = 0.72 + 0.05 * (node["lat"] - 34.0) + (0.30 if (node["lon"] - 77.0) < 0 else 0.0)
    lapse = -6.1 * (elev - 1500.0) / 1000.0
    rng = np.random.default_rng(
        (settings.theatre_seed + zlib.crc32(node["code"].encode())) % (2 ** 31)
    )
    rain, temp = np.empty(horizon), np.empty(horizon)
    for h in range(horizon):
        d = TODAY + timedelta(days=h)
        doy = d.timetuple().tm_yday
        burst = float(rng.gamma(shape=0.55, scale=1.9))
        wet = _climate_envelope(doy) * spatial * burst
        wet = wet * 0.18 if rng.random() < 0.31 else wet
        rain[h] = max(0.0, wet) * rainfall_mult
        seasonal = -7.4 * np.cos(2 * np.pi * (doy - 15.0) / 365.0)
        temp[h] = 6.5 + seasonal + lapse + float(rng.normal(0, 1.4)) + temp_offset
    return rain.round(2), temp.round(1)


# --------------------------------------------------------------------------- #
# Dataset + training
# --------------------------------------------------------------------------- #
def _build_dataset(w: repo.World) -> ModelBundle:
    pairs: list[tuple[str, str]] = []
    node_meta: dict[str, dict] = {}
    item_meta: dict[str, dict] = {}

    day_labels = sorted({c["day"] for c in w.consumption})
    day_labels = day_labels[-HISTORY_DAYS:]
    H = len(day_labels)
    day_to_idx = {d: i for i, d in enumerate(day_labels)}
    doy = np.array([date.fromisoformat(d).timetuple().tm_yday for d in day_labels])

    X_rows: list[np.ndarray] = []
    y_vals: list[float] = []
    grp: list[int] = []
    days: list[int] = []
    history: dict[str, np.ndarray] = {}
    ctxs: list[dict] = []
    label_to_idx: dict[str, int] = {}

    for node in w.nodes:
        node_meta[node["code"]] = node
        for item in w.items:
            item_meta[item["code"]] = item
            rows = [r for r in w._cons_index.get((node["code"], item["code"]), [])
                    if r["day"] in day_to_idx]
            if len(rows) < HISTORY_DAYS:
                continue
            label = f"{node['code']}|{item['code']}"
            label_to_idx[label] = len(pairs)
            pairs.append((node["code"], item["code"]))

            values = np.array([r["qty"] for r in rows], dtype=float)
            tempo = np.array([r["tempo"] for r in rows], dtype=object)
            ops = np.array([r["ops_flag"] for r in rows], dtype=float)
            rain = np.array([r["rainfall_mm"] for r in rows], dtype=float)
            temp = np.array([r["temp_c"] for r in rows], dtype=float)
            history[label] = values

            ctxs.append({
                "label": label, "node": node, "item": item,
                "values": values, "rain": rain, "temp": temp,
                "tempo": tempo, "ops": ops, "doy": doy,
            })

            for d in range(30, H):
                f = build_row(ctxs[-1], d, values)
                if f is None:
                    continue
                X_rows.append(f)
                y_vals.append(values[d])
                grp.append(label_to_idx[label])
                days.append(d)

    X = np.vstack(X_rows) if X_rows else np.zeros((0, len(FEATURE_NAMES)))
    bundle = ModelBundle(
        X=X, y=np.array(y_vals), groups=np.array(grp), day_idx=np.array(days),
        pairs=pairs, node_meta=node_meta, item_meta=item_meta,
        ctxs=ctxs, ctx_by_label={c["label"]: c for c in ctxs},
        history=history, doy=doy, day_labels=day_labels, rows=len(y_vals),
    )
    return bundle


def warm(bundle: ModelBundle) -> None:
    """Trains everything on a background thread; flips status to 'ready'."""
    t0 = time.perf_counter()
    bundle.status = "training"
    Xn = standardize_features(bundle.X)
    yn = bundle.y / series_scale(bundle.X)

    for alpha in (0.10, 0.50, 0.90):
        m = GBMQuantile(
            n_estimators=140, lr=0.10, max_depth=4, min_child_samples=70,
            n_bins=28, alpha=alpha,
        )
        m.fit(Xn, yn, FEATURE_NAMES)
        bundle.models[alpha] = m
    bundle.ridge = Ridge(lam=2.0).fit(Xn, yn)
    bundle.train_ms = round((time.perf_counter() - t0) * 1000, 1)

    t1 = time.perf_counter()
    labels = [f"{n}|{i}" for n, i in bundle.pairs]
    bundle.leaderboard, bundle.per_pair = walk_forward_backtest(
        bundle.X, bundle.y, bundle.groups, bundle.day_idx, FEATURE_NAMES,
        pair_labels=labels, ctxs=bundle.ctxs, origins=3, horizon=7,
        n_estimators=85,
    )
    bundle.backtest_ms = round((time.perf_counter() - t1) * 1000, 1)
    bundle.trained_at = time.time()
    bundle.status = "ready"


def get_bundle() -> ModelBundle:
    """Returns the bundle, training it synchronously on first call."""
    global _bundle
    if _bundle is not None:
        return _bundle
    with _lock:
        if _bundle is not None:
            return _bundle
        w = repo.load_world()
        b = _build_dataset(w)
        warm(b)
        _bundle = b
        return _bundle


def warm_in_background() -> None:
    def _run() -> None:
        global _bundle
        try:
            get_bundle()
        except Exception as exc:  # pragma: no cover - surfaced via /health
            with _lock:
                if _bundle is None:
                    err = ModelBundle(
                        X=np.zeros((0, len(FEATURE_NAMES))), y=np.zeros(0),
                        groups=np.zeros(0, dtype=int), day_idx=np.zeros(0, dtype=int),
                        pairs=[], node_meta={}, item_meta={},
                    )
                    err.status = "error"
                    err.error = repr(exc)
                    _bundle = err

    threading.Thread(target=_run, name="rahat-forecast-warm", daemon=True).start()


def reset() -> None:
    global _bundle
    with _lock:
        _bundle = None


def status() -> dict:
    if _bundle is None:
        return {"status": "cold", "message": "model not initialised"}
    return {
        "status": _bundle.status,
        "rows": _bundle.rows,
        "series": len(_bundle.pairs),
        "features": len(FEATURE_NAMES),
        "train_ms": _bundle.train_ms,
        "backtest_ms": _bundle.backtest_ms,
        "error": _bundle.error,
        "leaderboard": _bundle.leaderboard,
        "trained_at": _bundle.trained_at,
    }


# --------------------------------------------------------------------------- #
# Production context construction
# --------------------------------------------------------------------------- #
def _future_doy(horizon: int) -> np.ndarray:
    return np.array([(TODAY + timedelta(days=h)).timetuple().tm_yday
                     for h in range(horizon)], dtype=int)


def _production_ctx(
    b: ModelBundle,
    node_code: str,
    item_code: str,
    *,
    horizon: int,
    tempo_future: str,
    ops_future: int,
    rainfall_mult: float,
    temp_offset: float,
) -> dict:
    label = f"{node_code}|{item_code}"
    if label not in b.history:
        raise KeyError(f"no history for {label}")
    base = b.ctx_by_label[label]
    node = b.node_meta[node_code]
    H = len(b.history[label])

    out_rain, out_temp = weather_outlook(
        node, horizon, rainfall_mult=rainfall_mult, temp_offset=temp_offset
    )
    values = np.zeros(H + horizon, dtype=float)
    values[:H] = b.history[label]
    return {
        "label": label, "node": node, "item": b.item_meta[item_code],
        "values": values,
        "rain": np.concatenate([base["rain"], out_rain]),
        "temp": np.concatenate([base["temp"], out_temp]),
        "tempo": np.concatenate([base["tempo"],
                                 np.array([tempo_future] * horizon, dtype=object)]),
        "ops": np.concatenate([base["ops"],
                               np.array([ops_future] * horizon, dtype=float)]),
        "doy": np.concatenate([b.doy, _future_doy(horizon)]),
        "H": H,
    }


def forecast_batch(
    queries: list[tuple[str, str]],
    *,
    horizon: int,
    tempo_future: str = "nominal",
    ops_future: int = 0,
    rainfall_mult: float = 1.0,
    temp_offset: float = 0.0,
    demand_mult: float = 1.0,
    quantiles: bool = False,
) -> dict[str, dict]:
    """Recursive multi-step forecast for *many* series at once.

    MISSION SIM has to re-forecast every critical item at every forward unit
    before it can re-solve the network. Batching across series (one pooled model
    call per time step instead of one per series) is what turns a multi-second
    solve into a sub-second one.
    """
    b = get_bundle()
    if b.status == "error":
        raise RuntimeError(b.error)

    horizon = max(1, min(horizon, 90))
    ctxs: list[dict] = []
    for node_code, item_code in queries:
        try:
            ctxs.append(_production_ctx(
                b, node_code, item_code, horizon=horizon,
                tempo_future=tempo_future, ops_future=ops_future,
                rainfall_mult=rainfall_mult, temp_offset=temp_offset,
            ))
        except KeyError:
            continue
    if not ctxs:
        return {}

    H = ctxs[0]["H"]
    p50_full = predict_recursive(
        b.models[0.50], ctxs, start_day=H, horizon=horizon,
        demand_mult=demand_mult, keep_values=True,
    )
    p10 = p90 = None
    if quantiles:
        p10 = predict_recursive(b.models[0.10], ctxs, start_day=H,
                                horizon=horizon, demand_mult=demand_mult,
                                write=False)
        p90 = predict_recursive(b.models[0.90], ctxs, start_day=H,
                                horizon=horizon, demand_mult=demand_mult,
                                write=False)

    out: dict[str, dict] = {}
    for ctx in ctxs:
        label = ctx["label"]
        p50 = p50_full[label][H:H + horizon]
        res = {
            "p50": p50,
            "total": float(p50.sum()),
            "mean_daily": float(p50.mean()),
            "peak": float(p50.max()),
            "peak_day": (TODAY + timedelta(days=int(np.argmax(p50)) + 1)).isoformat(),
        }
        if quantiles and p10 is not None and p90 is not None:
            lo, hi = p10[label], p90[label]
            res["p10"] = lo
            res["p90"] = hi
            res["band_pct"] = round(
                float(np.mean((hi - lo) / np.maximum(p50, 1e-6)) * 100), 1)
        out[label] = res
    return out


# --------------------------------------------------------------------------- #
# Attribution narrative
# --------------------------------------------------------------------------- #
def _reasons(contrib: np.ndarray, intercept: float, peak: float,
             feature_values: np.ndarray) -> tuple[list[dict], str]:
    entries = []
    for i in np.argsort(-np.abs(contrib)):
        name = FEATURE_NAMES[i]
        phrase, kind = _PHRASES.get(name, (name, "other"))
        raw = float(feature_values[i])
        entries.append({
            "feature": name, "label": phrase, "kind": kind,
            "contribution": round(float(contrib[i]), 1),
            "value": round(raw, 2),
            "unit": _UNIT.get(name, ""),
            "display": f"{raw:,.0f}{_UNIT.get(name, '')}" if abs(raw) >= 100
            else f"{raw:,.2f}{_UNIT.get(name, '')}",
        })

    # Dynamic drivers (weather / ops / recent run-rate) are what an operator can
    # act on, so the narrative is built from their share of total absolute effect.
    dyn = [e for e in entries if e["kind"] in ("dynamic", "weather", "ops")]
    dyn_abs = sum(abs(e["contribution"]) for e in dyn) or 1.0
    for e in dyn:
        e["share_pct"] = round(abs(e["contribution"]) / dyn_abs * 100.0, 1)

    top = sorted(dyn, key=lambda e: -abs(e["contribution"]))[:3]
    parts = [
        f"{e['label']} ({e['display']}) {'raises' if e['contribution'] >= 0 else 'lowers'} "
        f"it by {abs(e['contribution']):,.0f} kg/day - {e['share_pct']:.0f}% of the swing"
        for e in top if e.get("share_pct", 0) >= 5
    ]
    narrative = (
        f"Peak-day requirement of {peak:,.0f} kg sits "
        f"{'above' if peak >= intercept else 'below'} the modelled baseline of "
        f"{intercept:,.0f} kg/day"
    )
    if parts:
        narrative += ", driven mainly by " + "; ".join(parts)
    narrative += "."
    return entries, narrative


def forecast(
    node_code: str,
    item_code: str,
    *,
    horizon: int = settings.forecast_default_horizon,
    tempo_future: str = "nominal",
    ops_future: int = 0,
    rainfall_mult: float = 1.0,
    temp_offset: float = 0.0,
    demand_mult: float = 1.0,
    history_window: int = 45,
) -> dict:
    b = get_bundle()
    if b.status == "error":
        raise RuntimeError(b.error)

    label = f"{node_code}|{item_code}"
    if label not in b.history:
        raise KeyError(f"no history for {label}")

    item = b.item_meta[item_code]
    hist = b.history[label]
    H = len(hist)
    horizon = max(1, min(horizon, 90))

    ctx = _production_ctx(
        b, node_code, item_code, horizon=horizon, tempo_future=tempo_future,
        ops_future=ops_future, rainfall_mult=rainfall_mult,
        temp_offset=temp_offset,
    )
    # p50 lays down the path, then p10/p90 are read on that same path.
    p50_full = predict_recursive(
        b.models[0.50], [ctx], start_day=H, horizon=horizon,
        demand_mult=demand_mult, keep_values=True,
    )[label]
    p50 = p50_full[H:H + horizon].copy()
    p10 = predict_recursive(b.models[0.10], [ctx], start_day=H, horizon=horizon,
                            demand_mult=demand_mult, write=False)[label]
    p90 = predict_recursive(b.models[0.90], [ctx], start_day=H, horizon=horizon,
                            demand_mult=demand_mult, write=False)[label]

    # Re-derive the peak-day feature row from the forecast path and attribute it.
    h_peak = int(np.argmax(p50))
    peak_row = build_row(ctx, H + h_peak, ctx["values"])
    if peak_row is None:
        raise RuntimeError("feature construction failed for attribution")
    x_n = standardize_features(peak_row.reshape(1, -1))[0]
    scale = max(float(peak_row[SCALE_IDX]), 1.0)
    model = b.models[0.50]
    contrib = model.attribute(x_n) * scale * demand_mult
    intercept = model.intercept * scale * demand_mult
    entries, narrative = _reasons(contrib, intercept, float(p50[h_peak]), peak_row)

    start = max(0, H - history_window)
    series = [
        {"day": b.day_labels[start + i], "actual": round(float(v), 1),
         "p50": None, "p10": None, "p90": None, "history": True}
        for i, v in enumerate(hist[start:])
    ]
    series += [
        {
            "day": (TODAY + timedelta(days=h + 1)).isoformat(),
            "actual": None,
            "p50": round(float(p50[h]), 1),
            "p10": round(float(p10[h]), 1),
            "p90": round(float(p90[h]), 1),
            "history": False,
        }
        for h in range(horizon)
    ]

    champion = b.per_pair.get(label, {}).get("gbm_quantile", {})
    naive_pred = seasonal_naive_forecast(hist, horizon)

    return {
        "node_code": node_code,
        "item_code": item_code,
        "item_name": item["name"],
        "category": item["category"],
        "horizon": horizon,
        "model": "gbm_quantile (alpha 0.10 / 0.50 / 0.90)",
        "series": series,
        "summary": {
            "total_kg": round(float(p50.sum()), 1),
            "daily_mean": round(float(p50.mean()), 1),
            "peak_kg": round(float(p50.max()), 1),
            "peak_day": (TODAY + timedelta(days=h_peak + 1)).isoformat(),
            "p10_total_kg": round(float(p10.sum()), 1),
            "p90_total_kg": round(float(p90.sum()), 1),
            "band_width_pct": round(
                float(np.mean((p90 - p10) / np.maximum(p50, 1e-6)) * 100.0), 1),
            "naive_total_kg": round(float(naive_pred.sum()), 1),
            "history_mean_kg": round(float(hist.mean()), 1),
        },
        "attribution": entries[:12],
        "narrative": narrative,
        "metrics": {
            "series": champion,
            "leaderboard": b.leaderboard,
            "mape": champion.get("mape"),
            "mase": champion.get("mase"),
        },
        "inputs": {
            "tempo_future": tempo_future, "ops_future": ops_future,
            "rainfall_mult": rainfall_mult, "temp_offset": temp_offset,
            "demand_mult": demand_mult,
        },
        "trained_at": b.trained_at,
        "train_ms": b.train_ms,
        "backtest_ms": b.backtest_ms,
    }
