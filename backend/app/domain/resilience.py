"""Network resilience analysis.

Answers three questions evaluators care about: where is the network fragile,
what breaks first, and how fast does capability degrade as corridors fail.
"""

from __future__ import annotations

import math

from ..config import settings
from .optimize import TheatreGraph


def _coverage(graph: TheatreGraph, depots: list[str], units: list[str],
              vehicle_t: float) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for u in units:
        best, best_path = math.inf, []
        for d in depots:
            legs, cost = graph.path(d, u, vehicle_t)
            if cost < best:
                best, best_path = cost, legs
        out[u] = {
            "reachable": math.isfinite(best),
            "cost": best,
            "legs": best_path,
            "km": round(sum(l.distance_km for l in best_path), 1),
            "risk": round(max((l.risk for l in best_path), default=0.0), 2),
            "hours": round(sum(l.hours for l in best_path), 1),
        }
    return out


def _efficiency(cov: dict[str, dict]) -> float:
    vals = [1.0 / c["cost"] for c in cov.values() if c["reachable"] and c["cost"] > 0]
    return round(sum(vals), 5)


def fragility(corridors: list[dict], nodes: dict[str, dict],
              depots: list[str], units: list[str],
              vehicle_t: float = 12.0) -> dict:
    """Ranks every corridor by blast radius: what fails if it fails."""
    base_graph = TheatreGraph(corridors, nodes)
    base = _coverage(base_graph, depots, units, vehicle_t)
    base_eff = _efficiency(base)

    rows = []
    for c in corridors:
        g = TheatreGraph(corridors, nodes, closed_corridors={c["id"]})
        cov = _coverage(g, depots, units, vehicle_t)
        lost = [u for u in units if not cov[u]["reachable"]]
        detour = [
            {"node": u, "extra_km": round(cov[u]["km"] - base[u]["km"], 1)}
            for u in units
            if cov[u]["reachable"] and base[u]["reachable"]
            and cov[u]["km"] > base[u]["km"] + 0.05
        ]
        eff = _efficiency(cov)
        rows.append({
            "id": c["id"], "code": c["code"], "name": c["name"],
            "road_class": c["road_class"], "all_weather": c["all_weather"],
            "distance_km": c["distance_km"], "closure_risk": c["closure_risk"],
            "capacity_t": c["capacity_t"],
            "units_lost": lost,
            "blast_radius": len(lost),
            "detours": detour,
            "detour_km": round(sum(d["extra_km"] for d in detour), 1),
            "efficiency_drop_pct": round(
                (base_eff - eff) / base_eff * 100.0, 1) if base_eff else 0.0,
            "single_point": bool(lost),
            "severity": "critical" if lost else (
                "high" if len(detour) >= 3 else "medium" if detour else "low"),
        })

    rows.sort(key=lambda r: (r["blast_radius"], r["efficiency_drop_pct"],
                             r["detour_km"]), reverse=True)

    # Per-unit bottleneck view: how many independent all-weather axes each unit has.
    node_axes = []
    for u in units:
        incident = [c for c in corridors
                    if c["from_node"] == u or c["to_node"] == u]
        aw = [c for c in incident if c["all_weather"]]
        worst = None
        for c in incident:
            g = TheatreGraph(corridors, nodes, closed_corridors={c["id"]})
            cov = _coverage(g, depots, units, vehicle_t)
            if not cov[u]["reachable"]:
                worst = c["code"]
                break
        node_axes.append({
            "node": u,
            "name": nodes[u]["name"] if u in nodes else u,
            "axes": len(incident),
            "all_weather_axes": len(aw),
            "sole_axis": worst,
            "isolation_km": nodes[u].get("isolation_km", 0.0) if u in nodes else 0.0,
            "vulnerable": worst is not None or len(aw) <= 1,
        })

    return {
        "base_efficiency": base_eff,
        "corridors": rows,
        "single_points": [r for r in rows if r["single_point"]],
        "nodes": sorted(node_axes, key=lambda r: (r["vulnerable"], r["all_weather_axes"])),
        "coverage": {u: {k: v for k, v in c.items() if k != "legs"}
                     for u, c in base.items()},
    }


def stress_curve(corridors: list[dict], nodes: dict[str, dict],
                 depots: list[str], units: list[str],
                 max_failures: int = 5, vehicle_t: float = 12.0) -> dict:
    """Greedily closes the most damaging corridor at each step and measures
    how the network degrades - the classic 'stress test' curve."""
    remaining = {c["id"] for c in corridors}
    base_graph = TheatreGraph(corridors, nodes)
    base = _coverage(base_graph, depots, units, vehicle_t)
    base_eff = _efficiency(base)

    points = [{
        "failed": 0, "closed": [], "unreachable": 0,
        "efficiency_pct": 100.0, "mean_km": round(
            sum(c["km"] for c in base.values()) / max(len(base), 1), 1),
        "mean_risk": round(
            sum(c["risk"] for c in base.values()) / max(len(base), 1), 2),
        "label": "Nominal",
    }]
    closed: list[int] = []
    codes_by_id = {c["id"]: c for c in corridors}

    for k in range(1, max_failures + 1):
        if not remaining:
            break
        best_id, best_score, best_cov = None, -1.0, None
        for cid in list(remaining):
            g = TheatreGraph(corridors, nodes, closed_corridors=closed + [cid])
            cov = _coverage(g, depots, units, vehicle_t)
            lost = sum(1 for c in cov.values() if not c["reachable"])
            eff_drop = (base_eff - _efficiency(cov)) / base_eff * 100.0 if base_eff else 0
            score = lost * 1000.0 + eff_drop
            if score > best_score:
                best_id, best_score, best_cov = cid, score, cov
        if best_id is None:
            break
        remaining.discard(best_id)
        closed.append(best_id)
        cov = best_cov or {}
        lost = sum(1 for c in cov.values() if not c["reachable"])
        eff = _efficiency(cov)
        points.append({
            "failed": k,
            "closed": [codes_by_id[c]["code"] for c in closed],
            "closed_names": [codes_by_id[c]["name"] for c in closed],
            "unreachable": lost,
            "efficiency_pct": round(eff / base_eff * 100.0, 1) if base_eff else 0.0,
            "mean_km": round(sum(c["km"] for c in cov.values()) / max(len(cov), 1), 1),
            "mean_risk": round(sum(c["risk"] for c in cov.values()) / max(len(cov), 1), 2),
            "label": f"{k} corridor{'s' if k > 1 else ''} down",
        })

    return {"base_efficiency": base_eff, "points": points,
            "critical_threshold": next(
                (p["failed"] for p in points if p["unreachable"] > 0), None)}


def fragility_index(corridors: list[dict], nodes: dict[str, dict],
                    depots: list[str], units: list[str],
                    vehicle_t: float = 12.0) -> float:
    """0-100 composite: higher means the network tolerates more failure.

    Built from edge-connectivity and redundancy so it can be shown as a single
    headline number on the dashboard.
    """
    g = TheatreGraph(corridors, nodes)
    cov = _coverage(g, depots, units, vehicle_t)
    reachable = sum(1 for c in cov.values() if c["reachable"])
    base = reachable / max(len(units), 1)

    # Mean count of all-weather axes leaving each forward unit.
    redundancy = 0.0
    for u in units:
        aw = sum(1 for c in corridors if (c["from_node"] == u or c["to_node"] == u)
                 and c["all_weather"])
        redundancy += min(aw, 3) / 3.0
    redundancy /= max(len(units), 1)

    # How much of the network is all-weather.
    aw_frac = sum(1 for c in corridors if c["all_weather"]) / max(len(corridors), 1)

    score = 100.0 * (0.45 * base + 0.35 * redundancy + 0.20 * aw_frac)
    return round(score, 1)
