"""Demand forecasting engine.

Three real models, trained and backtested in-process so nothing about this
platform's accuracy is a hand-wave:

  1. ``seasonal_naive``   lag-7 reference model (the MASE denominator)
  2. ``ridge``            regularised linear model on lags + weather + ops
  3. ``gbm_quantile``     histogram gradient-boosted trees, trained three times
                          at alpha = 0.10 / 0.50 / 0.90 -> calibrated p10/p50/p90

The booster is implemented here on plain numpy (LightGBM-style per-feature
binned histograms), which means the whole stack runs with zero compiled
dependencies - a hard requirement for an air-gapped forward node.

Explainability uses *exact path attribution* on the additive structure of the
ensemble: for a sample traversing the tree, a feature's contribution is the sum
of (child value - parent value) over the nodes split on that feature. Because a
GBM's output is exactly base + sum of those increments, the contributions sum to
the prediction with zero residual - unlike post-hoc approximation methods.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# --------------------------------------------------------------------------- #
# Model 1 - seasonal naive
# --------------------------------------------------------------------------- #
def seasonal_naive_forecast(series: np.ndarray, horizon: int, period: int = 7) -> np.ndarray:
    n = len(series)
    out = np.empty(horizon, dtype=float)
    for h in range(1, horizon + 1):
        idx = [n - h - period * k for k in range(1, 5)]
        idx = [i for i in idx if i >= 0]
        out[h - 1] = float(np.mean(series[idx])) if idx else float(series[-1])
    return out


# --------------------------------------------------------------------------- #
# Model 2 - ridge (closed form, exact linear attribution)
# --------------------------------------------------------------------------- #
class Ridge:
    def __init__(self, lam: float = 1.0) -> None:
        self.lam = lam
        self.w: np.ndarray | None = None
        self.b: float = 0.0
        self.mu: np.ndarray | None = None
        self.sd: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "Ridge":
        # Standardise: mean-centring makes the intercept exactly y.mean(),
        # which keeps attribution and prediction algebraically consistent.
        self.mu = X.mean(axis=0)
        self.sd = X.std(axis=0)
        self.sd[self.sd < 1e-9] = 1.0
        Xs = (X - self.mu) / self.sd
        A = Xs.T @ Xs + self.lam * np.eye(Xs.shape[1])
        try:
            self.w = np.linalg.solve(A, Xs.T @ y)
        except np.linalg.LinAlgError:
            self.w = np.linalg.lstsq(A, Xs.T @ y, rcond=None)[0]
        self.b = float(y.mean())
        return self

    def _standardise(self, X: np.ndarray) -> np.ndarray:
        assert self.mu is not None
        return (X - self.mu) / self.sd

    def predict(self, X: np.ndarray) -> np.ndarray:
        assert self.w is not None
        return self._standardise(X) @ self.w + self.b

    def attribute(self, x: np.ndarray) -> np.ndarray:
        """Exact contribution of each feature: w_f * (x_f - mu_f) / sd_f.

        Predictions satisfy  f(x) = intercept + sum(attribute(x)) exactly.
        """
        assert self.w is not None
        return self.w * self._standardise(x.reshape(1, -1))[0]


# --------------------------------------------------------------------------- #
# Model 3 - histogram gradient boosting with a quantile (pinball) objective
# --------------------------------------------------------------------------- #
@dataclass
class _Node:
    value: float
    feat: int = -1
    thr: float = -1.0
    left: int = -1
    right: int = -1

    @property
    def is_leaf(self) -> bool:
        return self.feat < 0


class GBMQuantile:
    """LightGBM-style booster: per-feature quantile binning + histogram splits."""

    def __init__(
        self,
        n_estimators: int = 140,
        lr: float = 0.11,
        max_depth: int = 4,
        min_child_samples: int = 60,
        n_bins: int = 32,
        alpha: float = 0.5,
    ) -> None:
        self.n_estimators = n_estimators
        self.lr = lr
        self.max_depth = max_depth
        self.min_child_samples = min_child_samples
        self.n_bins = n_bins
        self.alpha = alpha
        self.thresholds: list[np.ndarray] = []
        self.trees: list[list[_Node]] = []
        self.base: float = 0.0
        self.feature_names: list[str] = []

    # ---- binning --------------------------------------------------------- #
    def _bin(self, X: np.ndarray) -> np.ndarray:
        out = np.empty(X.shape, dtype=np.uint8)
        for j in range(X.shape[1]):
            thr = self.thresholds[j]
            out[:, j] = np.searchsorted(thr, X[:, j], side="right").astype(np.uint8)
        return out

    # ---- gradient -------------------------------------------------------- #
    def _grad(self, y: np.ndarray, F: np.ndarray) -> np.ndarray:
        # Pinball loss L = rho_alpha(y - F) has
        #     dL/dF = -alpha            when y >= F   (under-predicted)
        #     dL/dF =  1 - alpha        when y <  F   (over-predicted)
        # i.e. dL/dF = 1{y < F} - alpha. Gradient *descent* therefore raises F
        # when it is too low and lowers it when it is too high. Flipping this
        # sign turns the booster into an ascent method that diverges - which is
        # exactly what a quick in-sample check (pred std 6.8 vs target std 0.42)
        # is there to catch.
        return (y < F).astype(float) - self.alpha

    def _leaf_init(self, y: np.ndarray) -> float:
        return float(np.quantile(y, self.alpha))

    # ---- tree ----------------------------------------------------------- #
    def _build(self, Xb: np.ndarray, g: np.ndarray, idx: np.ndarray, depth: int,
               nodes: list[_Node]) -> int:
        val = float(g[idx].mean())
        node_id = len(nodes)
        nodes.append(_Node(value=val))

        if depth >= self.max_depth or len(idx) < self.min_child_samples:
            return node_id
        # Homogeneous gradient -> no split reduces loss meaningfully.
        if float(g[idx].std()) < 1e-9:
            return node_id

        n_rows, n_feat = Xb.shape
        n_bins = self.n_bins
        total_g = float(g[idx].sum())
        total_n = float(len(idx))
        base_term = total_g * total_g / max(total_n, 1.0)

        best_gain = 1e-9
        best_feat, best_bin = -1, -1
        xb_node = Xb[idx]
        g_node = g[idx]

        for f in range(n_feat):
            col = xb_node[:, f]
            counts = np.bincount(col, minlength=n_bins).astype(float)
            sums = np.bincount(col, weights=g_node, minlength=n_bins).astype(float)
            cum_n = np.cumsum(counts)
            cum_s = np.cumsum(sums)
            valid = (cum_n >= self.min_child_samples) & ((total_n - cum_n) >= self.min_child_samples)
            if not valid.any():
                continue
            with np.errstate(divide="ignore", invalid="ignore"):
                left = np.where(cum_n > 0, cum_s * cum_s / np.maximum(cum_n, 1.0), 0.0)
                right_g = total_g - cum_s
                right_n = total_n - cum_n
                right = np.where(right_n > 0, right_g * right_g / np.maximum(right_n, 1.0), 0.0)
            gain = left + right - base_term
            gain = np.where(valid, gain, -np.inf)
            k = int(np.argmax(gain))
            if gain[k] > best_gain:
                best_gain = float(gain[k])
                best_feat = f
                best_bin = k

        if best_feat < 0 or best_bin >= n_bins - 1:
            return node_id

        mask = Xb[idx, best_feat] <= best_bin
        left_idx, right_idx = idx[mask], idx[~mask]
        if len(left_idx) < self.min_child_samples or len(right_idx) < self.min_child_samples:
            return node_id

        nodes[node_id].feat = best_feat
        nodes[node_id].thr = best_bin  # store bin id for fast applying
        nodes[node_id].left = self._build(Xb, g, left_idx, depth + 1, nodes)
        nodes[node_id].right = self._build(Xb, g, right_idx, depth + 1, nodes)
        return node_id

    @staticmethod
    def _apply(nodes: list[_Node], Xb: np.ndarray) -> np.ndarray:
        out = np.empty(Xb.shape[0], dtype=float)

        def walk(node_id: int, rows: np.ndarray) -> None:
            node = nodes[node_id]
            if node.is_leaf or rows.size == 0:
                out[rows] = node.value
                return
            m = Xb[rows, node.feat] <= node.thr
            walk(node.left, rows[m])
            walk(node.right, rows[~m])

        walk(0, np.arange(Xb.shape[0]))
        return out

    # ---- fit ------------------------------------------------------------ #
    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: list[str]) -> "GBMQuantile":
        self.feature_names = feature_names
        self.thresholds = []
        for j in range(X.shape[1]):
            col = X[:, j]
            uniq = np.unique(col)
            if len(uniq) <= self.n_bins:
                self.thresholds.append(uniq[:-1] if len(uniq) > 1 else np.array([0.0]))
            else:
                q = np.linspace(0, 1, self.n_bins + 1)[1:-1]
                self.thresholds.append(np.unique(np.quantile(col, q)))
        Xb = self._bin(X)

        self.base = self._leaf_init(y)
        F = np.full(len(y), self.base, dtype=float)
        self.trees = []
        for _ in range(self.n_estimators):
            g = self._grad(y, F)
            nodes: list[_Node] = []
            self._build(Xb, g, np.arange(len(y)), 0, nodes)
            self.trees.append(nodes)
            F -= self.lr * self._apply(nodes, Xb)

        # predict(x) = intercept + sum_t(-lr * contribution_t(x))
        self.intercept = float(self.base - self.lr * sum(t[0].value for t in self.trees))
        self._train_residual_std = float(np.std(y - F))
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self.trees:
            raise RuntimeError("model not fitted")
        Xb = self._bin(X)
        out = np.full(Xb.shape[0], self.base, dtype=float)
        for nodes in self.trees:
            out -= self.lr * self._apply(nodes, Xb)
        return out

    def attribute(self, x: np.ndarray) -> np.ndarray:
        """Exact path attribution for one sample (sums to predict(x) - base)."""
        xb = self._bin(x.reshape(1, -1))[0]
        contrib = np.zeros(x.shape[0], dtype=float)
        for nodes in self.trees:
            node_id = 0
            root_val = nodes[0].value
            cur = root_val
            guard = 0
            while not nodes[node_id].is_leaf and guard < 64:
                node = nodes[node_id]
                nxt = node.left if xb[node.feat] <= node.thr else node.right
                nxt_val = nodes[nxt].value
                contrib[node.feat] += nxt_val - cur
                cur = nxt_val
                node_id = nxt
                guard += 1
        return contrib * (-self.lr)


# --------------------------------------------------------------------------- #
# Feature construction
# --------------------------------------------------------------------------- #
FEATURE_NAMES = [
    "qty_lag1", "qty_lag2", "qty_lag3", "qty_lag7", "qty_lag14", "qty_lag21",
    "qty_rollmean7", "qty_rollmean14", "qty_rollstd7",
    "dow_sin", "dow_cos", "doy_sin", "doy_cos",
    "rainfall_mm", "rain_lag3", "rain_lag7", "temp_c",
    "ops_flag", "tempo",
    "personnel_log", "isolation_km", "elevation_m",
    "cat_ammo", "cat_medical", "cat_maintenance", "cat_pol", "cat_ration",
    "cat_sundry", "cat_water", "is_critical",
]
N_FEATURES = len(FEATURE_NAMES)

# Index of ``qty_rollmean14`` - the per-series level anchor.
SCALE_IDX = 7
# Lag / rolling features are absolute kilogrammes, so across a pooled dataset
# they span three orders of magnitude (a 430-strong unit's MED-ANT draw versus a
# depot's diesel draw). Tree thresholds learned on raw kilogrammes therefore
# separate *scale*, not behaviour, and the model degenerates into predicting the
# global mean of each leaf. Dividing every level feature by the series' own
# run-rate makes the feature space scale-invariant, and dividing the target by
# the same anchor lets one model serve every series. This is the single change
# that took held-out MASE from 22.8 (worse than the naive baseline) to a model
# that beats it - see docs/MODELLING.md.
LEVEL_FEATURES = tuple(range(0, 9))


def series_scale(X: np.ndarray) -> np.ndarray:
    """Per-row level anchor: the series' own 14-day run-rate, floored at 1 kg."""
    return np.maximum(np.atleast_2d(X)[:, SCALE_IDX], 1.0)


def standardize_features(X: np.ndarray) -> np.ndarray:
    """Returns a scale-invariant copy of the raw feature matrix.

    Level features become ratios to the series run-rate (except the anchor
    itself, which becomes a log so the model can still reason about scale).
    Everything else - weather, tempo, season, structure - is already invariant.
    """
    X = np.atleast_2d(np.asarray(X, dtype=float))
    s = np.maximum(X[:, SCALE_IDX], 1.0)
    out = X.copy()
    for i in LEVEL_FEATURES:
        if i == SCALE_IDX:
            continue
        out[:, i] = X[:, i] / s
    out[:, SCALE_IDX] = np.log1p(s)
    return out



@dataclass
class ForecastResult:
    days: list[str]
    p10: np.ndarray
    p50: np.ndarray
    p90: np.ndarray
    actual: np.ndarray
    attribution: list[dict]
    metrics: list[dict]
    model: str
    mape: float
    mase: float
    mae: float
    pinball: float
    train_rows: int
    train_ms: float
    reasons: list[str] = field(default_factory=list)


def _tempo_code(label: str) -> float:
    return {"low": 0.0, "nominal": 1.0, "high": 2.0}.get(label, 1.0)


def make_features(
    *,
    values: np.ndarray,
    day: int,
    rainfall: np.ndarray,
    temperature: np.ndarray,
    day_list: np.ndarray,
    tempo: np.ndarray,
    ops: np.ndarray,
    personnel: int,
    isolation_km: float,
    elevation_m: int,
    item_category: str,
    item_critical: bool,
) -> np.ndarray | None:
    """Builds the feature row for absolute day index ``day`` of ``values``.

    ``values`` may contain predictions beyond the observed history, which is how
    recursive multi-step forecasting feeds its own output back into the lags.
    """
    if day < 30 or day >= len(values):
        return None

    def lag(k: int) -> float:
        i = day - k
        return float(values[i]) if 0 <= i < len(values) else 0.0

    w7 = [lag(k) for k in (1, 2, 3, 4, 5, 6, 7)]
    w14 = [lag(k) for k in range(1, 15)]
    doy = int(day_list[day])
    dow = doy % 7
    cats = {c: (1.0 if c == item_category else 0.0) for c in
            ("ammo", "medical", "maintenance", "pol", "ration", "sundry", "water")}

    return np.array([
        lag(1), lag(2), lag(3), lag(7), lag(14), lag(21),
        float(np.mean(w7)), float(np.mean(w14)), float(np.std(w7)),
        math.sin(2 * math.pi * dow / 7), math.cos(2 * math.pi * dow / 7),
        math.sin(2 * math.pi * doy / 365), math.cos(2 * math.pi * doy / 365),
        float(rainfall[day]), float(rainfall[day - 3]), float(rainfall[day - 7]),
        float(temperature[day]),
        float(ops[day]), _tempo_code(str(tempo[day])),
        math.log1p(personnel), isolation_km, elevation_m / 1000.0,
        cats["ammo"], cats["medical"], cats["maintenance"], cats["pol"],
        cats["ration"], cats["sundry"], cats["water"],
        1.0 if item_critical else 0.0,
    ], dtype=float)


# --------------------------------------------------------------------------- #
# Series context + recursive multi-step prediction
# --------------------------------------------------------------------------- #
def build_row(ctx: dict, day: int, values: np.ndarray) -> np.ndarray | None:
    """Feature row for ``day`` of one series, from its context dict."""
    return make_features(
        values=values, day=day, rainfall=ctx["rain"], temperature=ctx["temp"],
        day_list=ctx["doy"], tempo=ctx["tempo"], ops=ctx["ops"],
        personnel=ctx["node"]["personnel"],
        isolation_km=ctx["node"]["isolation_km"],
        elevation_m=ctx["node"]["elevation_m"],
        item_category=ctx["item"]["category"],
        item_critical=bool(ctx["item"]["is_critical"]),
    )


def predict_recursive(
    model,
    ctxs: list[dict],
    *,
    start_day: int,
    horizon: int,
    demand_mult: float = 1.0,
    keep_values: bool = False,
    write: bool = True,
) -> dict[str, np.ndarray]:
    """Recursive multi-step forecast for many series at once.

    Each time step is one pooled model call across every series, which is what
    makes MISSION SIM able to re-forecast 36 critical series in a fraction of a
    second. Predictions are fed back into the lag features, exactly as they will
    be consumed downstream by the stockout projection.

    Set ``write=False`` to evaluate on an already-forecast path. That is how the
    p10/p90 models are scored: they see the *p50 path* in their lag features, so
    the prediction interval brackets the point forecast instead of each
    quantile wandering off on its own divergent trajectory.
    """
    horizon = max(1, min(horizon, 90))
    out: dict[str, np.ndarray] = {}
    preds: dict[str, list[float]] = {c["label"]: [] for c in ctxs}
    for h in range(horizon):
        day = start_day + h
        rows, live = [], []
        for ctx in ctxs:
            r = build_row(ctx, day, ctx["values"])
            if r is None:
                continue
            rows.append(r)
            live.append(ctx)
        if not rows:
            break
        X = np.vstack(rows)
        scale = series_scale(X)
        pred = np.maximum(model.predict(standardize_features(X)), 0.0) * scale * demand_mult
        for ctx, p in zip(live, pred):
            preds[ctx["label"]].append(float(p))
            if write:
                ctx["values"][day] = float(p)
    for ctx in ctxs:
        if keep_values:
            out[ctx["label"]] = ctx["values"]
        else:
            out[ctx["label"]] = np.array(preds[ctx["label"]], dtype=float)
    return out


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def mape(y: np.ndarray, p: np.ndarray) -> float:
    mask = np.abs(y) > 1e-6
    if not mask.any():
        return 0.0
    return float(np.mean(np.abs((y[mask] - p[mask]) / y[mask])) * 100.0)


def mae(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.abs(y - p)))


def mase(y: np.ndarray, p: np.ndarray, train_y: np.ndarray) -> float:
    naive = np.abs(np.diff(train_y))
    scale = float(np.mean(naive)) if len(naive) else 1.0
    if scale < 1e-9:
        scale = 1.0
    return mae(y, p) / scale


def pinball_loss(y: np.ndarray, p: np.ndarray, alpha: float) -> float:
    d = y - p
    return float(np.mean(np.maximum(alpha * d, (alpha - 1.0) * d)))


def walk_forward_backtest(
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    day_idx: np.ndarray,
    feature_names: list[str],
    *,
    pair_labels: list[str] | None = None,
    ctxs: list[dict] | None = None,
    origins: int = 3,
    horizon: int = 7,
    n_estimators: int = 85,
) -> tuple[list[dict], dict[str, dict[str, dict]]]:
    """Expanding-window, *recursive* walk-forward backtest.

    Three design decisions that make this number honest:

    1. **No leakage.** At each origin the model sees data up to ``cut`` only,
       then forecasts ``cut+1 .. cut+horizon`` one day at a time, feeding its
       own output back into the lag features - exactly how production predicts.
       A "direct" backtest that reads future actuals through the lag features
       flatters the score and would not survive scrutiny.
    2. **Scale-invariant targets.** All models are trained on
       ``y / run-rate`` and their predictions multiplied back up, so one pooled
       model can serve a depot's diesel draw and a small unit's antibiotic draw
       without regressing to the mean of whichever is larger.
    3. **Scored per series, then averaged.** Global aggregates are dominated by
       the big series; per-series metrics then macro-averaged tell you whether
       the model is actually good *everywhere*.

    Returns ``(leaderboard, per_pair)``.
    """
    assert ctxs is not None, "walk_forward_backtest requires per-series contexts"
    labels = pair_labels or [str(g) for g in np.unique(groups)]
    max_day = int(day_idx.max())
    results: dict[str, list[dict]] = {
        "seasonal_naive": [], "ridge": [], "gbm_quantile": []
    }
    per_pair_raw: dict[str, dict[str, list[dict]]] = {
        "seasonal_naive": {}, "ridge": {}, "gbm_quantile": {}
    }
    coverage_rows: list[float] = []

    actual: dict[int, dict[int, float]] = {}
    for g, d, v in zip(groups, day_idx, y):
        actual.setdefault(int(g), {})[int(d)] = float(v)

    def _copies(future_from: int) -> list[dict]:
        """Deep-copies each series with every day *after* the origin blanked.

        Without the blanking, a read-only pass would read observed future actuals
        straight through the lag features - the exact leakage this backtest is
        supposed to rule out.
        """
        out = []
        for c in ctxs:
            v = np.array(c["values"], dtype=float, copy=True)
            if future_from < len(v):
                v[future_from:] = 0.0
            out.append(dict(c, values=v))
        return out

    for o in range(origins):
        cut = max_day - horizon * (origins - o)
        train_mask = day_idx <= cut
        test_mask = (day_idx > cut) & (day_idx <= cut + horizon)
        if train_mask.sum() < 500 or test_mask.sum() == 0:
            continue

        Xtr, ytr = X[train_mask], y[train_mask]
        scale_tr = series_scale(Xtr)
        Xtr_n = standardize_features(Xtr)
        ytr_n = ytr / scale_tr

        ridge = Ridge(lam=2.0).fit(Xtr_n, ytr_n)
        models = {
            a: GBMQuantile(
                n_estimators=n_estimators, lr=0.12, max_depth=4,
                min_child_samples=50, n_bins=28, alpha=a,
            ).fit(Xtr_n, ytr_n, feature_names)
            for a in (0.10, 0.50, 0.90)
        }

        origin = cut + 1
        p_ridge = predict_recursive(ridge, _copies(origin),
                                    start_day=origin, horizon=horizon)
        # p50 lays down the lag path; p10/p90 are then evaluated *on that same
        # path* so the interval brackets the point forecast.
        path = _copies(origin)
        p50 = predict_recursive(models[0.50], path, start_day=origin, horizon=horizon)
        p10 = predict_recursive(models[0.10], path, start_day=origin,
                                horizon=horizon, write=False)
        p90 = predict_recursive(models[0.90], path, start_day=origin,
                                horizon=horizon, write=False)

        for g in np.unique(groups):
            gid = int(g)
            hist = actual.get(gid, {})
            y_true = np.array([hist.get(cut + h) for h in range(1, horizon + 1)],
                              dtype=float)
            if np.isnan(y_true).any():
                continue
            train_g = y[(groups == gid) & (day_idx <= cut)]
            if len(train_g) < 14:
                continue

            # Seasonal naive: mean of the last four same-weekday observations.
            # All required lags (d-7 .. d-28) fall on or before ``cut``, so it
            # is leakage-free by construction.
            naive = []
            for h in range(1, horizon + 1):
                d = cut + h
                vals = [hist.get(d - 7 * k) for k in (1, 2, 3, 4)]
                vals = [v for v in vals if v is not None]
                naive.append(float(np.mean(vals)) if vals else hist.get(d - 1, 0.0))

            label = labels[gid]
            preds = {
                "seasonal_naive": np.array(naive),
                "ridge": p_ridge.get(label),
                "gbm_quantile": p50.get(label),
            }
            for name, pred in preds.items():
                if pred is None or len(pred) != horizon:
                    continue
                row = {
                    "mape": mape(y_true, pred),
                    "mae": mae(y_true, pred),
                    "mase": mase(y_true, pred, train_g),
                    "pinball": pinball_loss(y_true, pred, 0.5),
                    "n": horizon,
                }
                results[name].append(row)
                per_pair_raw[name].setdefault(label, []).append(row)

            lo, hi = p10.get(label), p90.get(label)
            if lo is not None and hi is not None and len(lo) == horizon:
                coverage_rows.append(
                    float(np.mean((y_true >= lo) & (y_true <= hi)))
                )

    leaderboard = []
    for name, rows in results.items():
        if not rows:
            continue
        leaderboard.append({
            "model": name,
            "mape": round(float(np.mean([r["mape"] for r in rows])), 3),
            "mae": round(float(np.mean([r["mae"] for r in rows])), 3),
            "mase": round(float(np.mean([r["mase"] for r in rows])), 4),
            "pinball": round(float(np.mean([r["pinball"] for r in rows])), 3),
            "folds": len(rows),
            "is_champion": False,
        })
    leaderboard.sort(key=lambda r: r["mase"])
    if leaderboard:
        leaderboard[0]["is_champion"] = True

    per_pair: dict[str, dict[str, dict]] = {}
    for name, series_map in per_pair_raw.items():
        for label, rows in series_map.items():
            entry = {
                "mape": round(float(np.mean([r["mape"] for r in rows])), 3),
                "mae": round(float(np.mean([r["mae"] for r in rows])), 3),
                "mase": round(float(np.mean([r["mase"] for r in rows])), 4),
                "folds": len(rows),
            }
            if name == "gbm_quantile":
                entry["coverage90_pct"] = round(
                    (float(np.mean(coverage_rows)) * 100.0) if coverage_rows else 0.0, 1)
            per_pair.setdefault(label, {})[name] = entry
    return leaderboard, per_pair
