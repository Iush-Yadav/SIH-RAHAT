"""RAHAT REST + WebSocket API.

Grouped by the four pillars of PS SIH26251 so a judge browsing /docs can see the
problem statement mapped straight onto the endpoints.
"""

from __future__ import annotations

import math
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect, WebSocketException
from fastapi.responses import PlainTextResponse
from starlette.requests import HTTPConnection
from pydantic import BaseModel, Field

from . import auth, repository as repo, telemetry
from .config import settings
from .db import audit_log as audit_t
from .domain import resilience as resilience_domain
from .domain import simulate as sim
from .domain.forecast import FEATURE_NAMES
from .domain.geo import LocalProjection
from .domain.optimize import TheatreGraph, consolidate, reallocate, solve_routes
from .services import forecast_service as fs

# --------------------------------------------------------------------------- #
# Auth - enforced at router level so no future endpoint can ship unprotected
# --------------------------------------------------------------------------- #
PUBLIC_PATHS = {
    "/api/v1/auth/login",   # must be callable before a token exists
    "/api/v1/auth/roles",   # role labels only, needed by the login screen
    "/api/v1/health",       # readiness probe for the container orchestrator
}


def require_auth(
    request: HTTPConnection,
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict:
    """Validates the bearer JWT for every route under ``/api/v1``.

    ``token`` is accepted as a query parameter solely because a browser
    WebSocket cannot set an ``Authorization`` header on the handshake; it is
    taken from the same signed cookie-free token the login endpoint issues.
    """
    if request.url.path in PUBLIC_PATHS:
        return {"username": "system", "role": "admin", "public": True}

    payload = None
    if authorization and authorization.lower().startswith("bearer "):
        payload = auth.decode_token(authorization.split(" ", 1)[1].strip())
    elif token and request.scope["type"] == "websocket":
        payload = auth.decode_token(token)
    if payload is None:
        if request.scope["type"] == "websocket":
            raise WebSocketException(code=1008, reason="Not authenticated")
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"username": payload["sub"], "role": payload.get("role", "logistics_officer")}


class LoginBody(BaseModel):
    username: str
    password: str = ""


def whoami(principal: dict = Depends(require_auth)) -> dict:
    p = dict(principal)
    p["perms"] = auth.permissions(p["role"])
    p["role_label"] = auth.ROLES.get(p["role"], {}).get("label", p["role"])
    return p


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_auth)])


@router.post("/auth/login")
def login(body: LoginBody) -> dict:
    user = repo.find_user(body.username.strip().lower())
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    pw = body.password
    if not auth.verify_password(pw, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = auth.create_token(user["username"], user["role"])
    repo.log_audit(user["username"], user["role"], "login", "session")
    return {
        "token": token, "username": user["username"],
        "display_name": user["display_name"], "role": user["role"],
        "role_label": auth.ROLES.get(user["role"], {}).get("label", user["role"]),
        "perms": auth.permissions(user["role"]),
    }


@router.get("/auth/me")
def me(user: dict = Depends(whoami)) -> dict:
    return user


@router.get("/auth/roles")
def roles() -> dict:
    return auth.ROLES


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #
@router.get("/health")
def health() -> dict:
    m = fs.status()
    return {
        "status": "ok" if m.get("status") != "error" else "degraded",
        "app": settings.app_name, "version": settings.version,
        "ps": settings.ps_number, "model": m,
        "db_version": repo.version(),
        "telemetry_ticks": telemetry.hub.ticks,
    }


@router.get("/meta")
def meta() -> dict:
    w = repo.load_world()
    return {
        "app": settings.app_name,
        "tagline": settings.app_tagline,
        "ps_number": settings.ps_number,
        "version": settings.version,
        "theatre_seed": settings.theatre_seed,
        "history_days": settings.history_days,
        "today": "2026-10-03",
        "scenarios": [
            {"key": s.key, "label": s.label, "description": s.description,
             "icon": s.icon, "severity": s.severity,
             "talking_point": s.talking_point}
            for s in sim.SCENARIOS
        ],
        "features": len(FEATURE_NAMES),
        "counts": {
            "nodes": len(w.nodes), "corridors": len(w.corridors),
            "items": len(w.items), "inventory": len(w.inventory),
            "convoys": len(w.convoys), "alerts": len(w.alerts),
            "consumption_rows": len(w.consumption),
        },
        "categories": sorted({i["category"] for i in w.items}),
        "themes": [
            "AI/ML demand forecasting", "GIS-enabled logistics planning",
            "IoT inventory tracking", "Integrated predictive logistics",
        ],
    }


# --------------------------------------------------------------------------- #
# Theatre / GIS
# --------------------------------------------------------------------------- #
_theatre_cache: dict = {"v": -1, "data": None}


@router.get("/theatre")
def theatre() -> dict:
    if _theatre_cache["v"] == repo.version() and _theatre_cache["data"]:
        return _theatre_cache["data"]

    w = repo.load_world()
    lats = [n["lat"] for n in w.nodes]
    lons = [n["lon"] for n in w.nodes]
    lat0 = (min(lats) + max(lats)) / 2
    lon0 = (min(lons) + max(lons)) / 2
    proj = LocalProjection(lat0, lon0)

    node_out = []
    for n in w.nodes:
        x, y = proj.to_xy(n["lat"], n["lon"])
        node_out.append({
            "id": n["id"], "code": n["code"], "name": n["name"], "type": n["type"],
            "lat": n["lat"], "lon": n["lon"], "x": round(x, 4), "y": round(y, 4),
            "elevation_m": n["elevation_m"], "personnel": n["personnel"],
            "district": n["district"], "access_road": n["access_road"],
            "isolation_km": n["isolation_km"], "capacity_t": n["capacity_t"],
            "is_critical": n["is_critical"],
        })

    node_xy = {n["code"]: (n["x"], n["y"]) for n in node_out}
    corr_out = []
    for c in w.corridors:
        a = w.node_by_code.get(c["from_node"])
        b = w.node_by_code.get(c["to_node"])
        if not a or not b:
            continue
        path_xy = []
        for lat, lon in (c["path"] or []):
            px, py = proj.to_xy(lat, lon)
            path_xy.append([round(px, 4), round(py, 4)])
        if len(path_xy) < 2:
            path_xy = [list(node_xy[a["code"]]), list(node_xy[b["code"]])]
        corr_out.append({
            "id": c["id"], "code": c["code"], "name": c["name"],
            "from": a["code"], "to": b["code"],
            "from_id": c["from_id"], "to_id": c["to_id"],
            "distance_km": c["distance_km"], "grade_pct": c["grade_pct"],
            "road_class": c["road_class"], "all_weather": c["all_weather"],
            "closure_risk": c["closure_risk"], "capacity_t": c["capacity_t"],
            "altitude_pass_m": c["altitude_pass_m"],
            "path": path_xy,
            "mid": path_xy[len(path_xy) // 2],
        })

    xs = [n["x"] for n in node_out]
    ys = [n["y"] for n in node_out]
    data = {
        "anchor": {"lat": lat0, "lon": lon0,
                   "km_per_deg_lat": round(proj.km_per_deg_lat, 4),
                   "km_per_deg_lon": round(proj.km_per_deg_lon, 4)},
        "bounds": {"min_x": math.floor(min(xs)) - 6, "max_x": math.ceil(max(xs)) + 6,
                   "min_y": math.floor(min(ys)) - 6, "max_y": math.ceil(max(ys)) + 6},
        "nodes": node_out,
        "corridors": corr_out,
        "elevation_profile": _elevation_lines(proj, w),
    }
    _theatre_cache["v"] = repo.version()
    _theatre_cache["data"] = data
    return data


def _elevation_lines(proj: LocalProjection, w) -> list[list[list[float]]]:
    """Stylised contour rings for the map backdrop (deterministic, no tiles)."""
    from .domain.theatre import elevation_at

    lines = []
    lats = [n["lat"] for n in w.nodes]
    lons = [n["lon"] for n in w.nodes]
    lat_min, lat_max = min(lats) - 0.18, max(lats) + 0.18
    lon_min, lon_max = min(lons) - 0.22, max(lons) + 0.22

    for band in range(500, 5800, 500):
        pts: list[list[float]] = []
        step = 0.035
        lat = lat_min
        while lat <= lat_max:
            lon = lon_min
            while lon <= lon_max:
                if abs(elevation_at(lat, lon) - band) < 45:
                    x, y = proj.to_xy(lat, lon)
                    pts.append([round(x, 3), round(y, 3)])
                lon += step
            lat += step
        if len(pts) >= 4:
            # Split into runs so contours read as terrain, not a starburst.
            lines.append(pts[:600])
    return lines


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@router.get("/kpis")
def kpis() -> dict:
    w = repo.load_world()
    units = [n for n in w.nodes if n["type"] == "unit"]
    depots = [n for n in w.nodes if n["type"] in ("depot", "railhead", "airfield")]
    crit = [i for i in w.items if i["is_critical"]]

    inv = w.inventory
    cons_idx = w._cons_index

    pairs_ok = 0
    pairs_total = 0
    at_risk: set[str] = set()
    dos_rows = []
    unit_cover: dict[str, float] = {}
    for u in units:
        worst_dos = math.inf
        for it in crit:
            row = next((r for r in inv
                        if r["node_id"] == u["id"] and r["item_id"] == it["id"]), None)
            if not row:
                continue
            pairs_total += 1
            ok = (row["on_hand"] + row["in_transit"]) >= row["min_level"]
            pairs_ok += int(ok)
            if not ok:
                at_risk.add(u["code"])
            hist = cons_idx.get((u["code"], it["code"]), [])
            recent = [h["qty"] for h in hist[-14:]]
            rate = (sum(recent) / len(recent)) if recent else 0.0
            dos = row["on_hand"] / rate if rate > 0 else math.inf
            worst_dos = min(worst_dos, dos)
            dos_rows.append({
                "node": u["code"], "item": it["code"], "name": it["name"],
                "on_hand": row["on_hand"], "min_level": row["min_level"],
                "in_transit": row["in_transit"],
                "dos": round(dos, 1) if math.isfinite(dos) else 999,
            })
        unit_cover[u["code"]] = round(worst_dos, 1) if math.isfinite(worst_dos) else 999

    active = [c for c in w.convoys if c["status"] in ("in_transit", "loading")]
    tonnes_transit = sum(c["load_t"] for c in active)
    km = sum(c["distance_km"] for c in w.convoys) or 1.0
    cost = sum(c["distance_km"] * (58.0 + 13.0 * c["load_t"]) for c in w.convoys)
    tonne_km = sum(c["distance_km"] * c["load_t"] for c in w.convoys) or 1.0

    node_map = w.node_by_code
    frag = resilience_domain.fragility_index(
        w.corridors, node_map, [d["code"] for d in depots], [u["code"] for u in units])

    online = sum(1 for s in w.sensors if s.get("online"))
    open_alerts = [a for a in w.alerts if not a.get("acknowledged")]

    return {
        "units_total": len(units),
        "units_at_risk": len(at_risk),
        "unit_risk_list": sorted(at_risk),
        "fill_rate_pct": round(pairs_ok / pairs_total * 100, 1) if pairs_total else 0.0,
        "convoys_active": len(active),
        "convoys_total": len(w.convoys),
        "tonnes_in_transit": round(tonnes_transit, 1),
        "cost_per_tonne_km": round(cost / tonne_km, 1),
        "network_efficiency_index": frag,
        "sensor_online_pct": round(online / max(len(w.sensors), 1) * 100, 1),
        "alerts_open": len(open_alerts),
        "alerts_critical": sum(1 for a in open_alerts if a["severity"] == "critical"),
        "model_status": fs.status().get("status"),
        "dos": sorted(dos_rows, key=lambda r: r["dos"])[:12],
        "unit_days_of_supply": unit_cover,
    }


@router.get("/alerts")
def get_alerts(limit: int = Query(50, le=200)) -> dict:
    w = repo.load_world()
    out = []
    for a in w.alerts[:limit]:
        node = w.nodes and next((n for n in w.nodes if n["id"] == a.get("node_id")), None)
        out.append({
            "id": a["id"], "ts": a["ts"], "severity": a["severity"],
            "type": a["type"], "message": a["message"], "action": a["action"],
            "acknowledged": a["acknowledged"], "node": node["code"] if node else None,
        })
    return {"items": out, "open": sum(1 for a in out if not a["acknowledged"])}


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, user: dict = Depends(whoami)) -> dict:
    if "acknowledge" not in user["perms"] and "admin" not in user["perms"]:
        raise HTTPException(status_code=403, detail="Role cannot acknowledge alerts")
    repo.acknowledge_alert(alert_id, user["username"])
    return {"ok": True}


@router.get("/convoys")
def get_convoys() -> dict:
    w = repo.load_world()
    t = theatre()
    path_by_corr = {}
    for c in t["corridors"]:
        path_by_corr[c["code"]] = c["path"]
    pair_to_corr = {(c["from"], c["to"]): c for c in t["corridors"]}
    pair_to_corr.update({(c["to"], c["from"]): c for c in t["corridors"]})

    corr_code = {c["id"]: c["code"] for c in w.corridors}
    corr_lookup = {c["code"]: c for c in w.corridors}

    out = []
    for cv in w.convoys:
        o = w.nodes and next((n for n in w.nodes if n["id"] == cv["origin_node"]), None)
        d = next((n for n in w.nodes if n["id"] == cv["dest_node"]), None)
        if not o or not d:
            continue
        legs = w.legs.get(cv["id"], [])
        route: list[list[float]] = []
        for lg in legs:
            code = corr_code.get(lg["corridor_id"], "")
            pts = path_by_corr.get(code)
            if pts:
                if not route:
                    route.extend(pts)
                else:
                    route.extend(pts[1:])
        if not route:
            c = pair_to_corr.get((o["code"], d["code"]))
            route = c["path"] if c else []
        out.append({
            "id": cv["id"], "code": cv["code"], "vehicle_type": cv["vehicle_type"],
            "capacity_t": cv["capacity_t"], "status": cv["status"],
            "load_t": cv["load_t"], "distance_km": cv["distance_km"],
            "fuel_l": cv["fuel_l"], "risk_score": cv["risk_score"],
            "origin": o["code"], "dest": d["code"], "origin_name": o["name"],
            "dest_name": d["name"], "manifest": cv["manifest"],
            "route": route, "plan_id": cv["plan_id"], "kind": cv["kind"],
            "progress_seed": (cv["id"] * 137) % 1000 / 1000.0,
        })
    return {"items": out}


# --------------------------------------------------------------------------- #
# Inventory & IoT
# --------------------------------------------------------------------------- #
@router.get("/inventory")
def get_inventory(node: str | None = None, category: str | None = None) -> dict:
    w = repo.load_world()
    node_id_code = {n["id"]: n["code"] for n in w.nodes}
    item_by_id = {i["id"]: i for i in w.items}
    rows = []
    for inv in w.inventory:
        ncode = node_id_code[inv["node_id"]]
        it = item_by_id[inv["item_id"]]
        if node and ncode != node:
            continue
        if category and it["category"] != category:
            continue
        hist = w._cons_index.get((ncode, it["code"]), [])
        recent = [h["qty"] for h in hist[-14:]]
        rate = (sum(recent) / len(recent)) if recent else 0.0
        dos = inv["on_hand"] / rate if rate > 0 else 999
        cover = inv["on_hand"] + inv["in_transit"]
        rows.append({
            "node": ncode, "node_type": next(
                (n["type"] for n in w.nodes if n["code"] == ncode), ""),
            "item": it["code"], "name": it["name"], "category": it["category"],
            "critical": it["is_critical"], "on_hand": inv["on_hand"],
            "reserved": inv["reserved"], "in_transit": inv["in_transit"],
            "min_level": inv["min_level"], "reorder_qty": inv["reorder_qty"],
            "daily_rate": round(rate, 1),
            "dos_days": round(dos, 1) if math.isfinite(dos) else 999,
            "fill_pct": round(cover / inv["min_level"] * 100, 1) if inv["min_level"] else 100.0,
            "status": "critical" if dos < 6 else "low" if dos < 9 else "ok",
        })
    rows.sort(key=lambda r: r["dos_days"])
    return {"items": rows, "count": len(rows)}


@router.get("/sensors")
def get_sensors() -> dict:
    snap = telemetry.hub.snapshot()
    w = repo.load_world()
    meta = {}
    for s in w.sensors:
        node = next((n for n in w.nodes if n["id"] == s["node_id"]), None)
        if node:
            meta[s["node_id"]] = {
                "gateway": s["gateway"], "protocol": s["protocol"],
                "battery_pct": s["battery_pct"], "signal_dbm": s["signal_dbm"],
                "online": s["online"], "node_code": node["code"],
                "elevation_m": node["elevation_m"],
            }
    nodes_out = []
    for n in snap["nodes"]:
        nodes_out.append({**meta.get(n["node_id"], {}), **n})
    return {
        "nodes": nodes_out, "ticks": snap["ticks"], "clients": snap["clients"],
        "mqtt": snap["mqtt"], "uptime_s": snap["uptime_s"],
        "online_pct": round(sum(1 for m in meta.values() if m["online"])
                            / max(len(meta), 1) * 100, 1),
    }


# --------------------------------------------------------------------------- #
# Forecasting  (pillar 1)
# --------------------------------------------------------------------------- #
@router.get("/forecast")
def get_forecast(
    node: str = Query("U-21"),
    item: str = Query("POL-DIE"),
    horizon: int = Query(30, ge=1, le=90),
    tempo: str = Query("nominal"),
    ops: int = Query(0),
    rainfall_mult: float = Query(1.0, ge=0.0, le=6.0),
    temp_offset: float = Query(0.0, ge=-25.0, le=25.0),
    demand_mult: float = Query(1.0, ge=0.2, le=4.0),
) -> dict:
    try:
        return fs.forecast(
            node, item, horizon=horizon, tempo_future=tempo, ops_future=ops,
            rainfall_mult=rainfall_mult, temp_offset=temp_offset,
            demand_mult=demand_mult,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/forecast/series")
def forecast_series() -> dict:
    """Every (node, item) pair with a one-line summary - powers the picker."""
    b = fs.get_bundle()
    if b.status == "error":
        raise HTTPException(status_code=503, detail=b.error)
    return {
        "status": b.status,
        "pairs": [{"node": n, "item": i, "label": f"{n} | {i}"}
                  for n, i in b.pairs],
        "leaderboard": b.leaderboard,
        "train_ms": b.train_ms, "backtest_ms": b.backtest_ms, "rows": b.rows,
    }


@router.get("/forecast/leaderboard")
def leaderboard() -> dict:
    b = fs.get_bundle()
    if b.status == "error":
        raise HTTPException(status_code=503, detail=b.error)
    return {
        "leaderboard": b.leaderboard, "per_pair": b.per_pair,
        "rows": b.rows, "series": len(b.pairs), "features": len(FEATURE_NAMES),
        "train_ms": b.train_ms, "backtest_ms": b.backtest_ms,
        "status": b.status, "models": ["seasonal_naive", "ridge", "gbm_quantile"],
        "method": "expanding-window walk-forward, 3 origins x 7 days, scored per series",
    }


# --------------------------------------------------------------------------- #
# Planning  (pillar 2 - GIS route optimisation)
# --------------------------------------------------------------------------- #
class RoutePlanBody(BaseModel):
    demands: dict[str, float] = Field(default_factory=dict)
    horizon: int = Field(14, ge=1, le=45)
    close: list[str] = Field(default_factory=list)
    adverse: bool = False
    capacity_mult: float = Field(1.0, ge=0.2, le=1.0)


@router.post("/plan/routes")
def plan_routes(body: RoutePlanBody, user: dict = Depends(whoami)) -> dict:
    w = repo.load_world()
    units = [n for n in w.nodes if n["type"] == "unit"]
    depots = [n for n in w.nodes if n["type"] in ("depot", "railhead", "airfield")]
    crit = [i for i in w.items if i["is_critical"]]

    demands = body.demands
    if not demands:
        queries = [(u["code"], it["code"]) for u in units for it in crit]
        fc = fs.forecast_batch(queries, horizon=body.horizon)
        for u in units:
            total = sum(fc.get(f"{u['code']}|{it['code']}", {}).get("total", 0.0)
                        for it in crit)
            demands[u["code"]] = round(total / 1000.0, 2)

    closed_ids = {c["id"] for c in w.corridors if c["code"] in set(body.close)}
    g = TheatreGraph(w.corridors, w.node_by_code, closed_corridors=closed_ids,
                     adverse_weather=body.adverse)

    fleet = [
        {"code": c["code"], "vehicle_type": c["vehicle_type"],
         "capacity_t": c["capacity_t"]}
        for c in w.convoys
    ]
    keep = max(1, int(math.ceil(len(fleet) * body.capacity_mult)))
    fleet = fleet[:keep]

    t0 = time.perf_counter()
    base, opt = solve_routes(
        g, [d["code"] for d in depots], demands, fleet,
        required_by_days=float(body.horizon))
    elapsed = round((time.perf_counter() - t0) * 1000, 1)

    def pack(p):
        return {
            "solver": p.solver, "solve_ms": p.solve_ms,
            "distance_km": p.total_distance_km, "cost_inr": p.total_cost_inr,
            "fuel_l": p.total_fuel_l, "hours": round(p.total_hours, 1),
            "utilisation_pct": p.utilisation_pct, "worst_risk": p.worst_risk,
            "unserved": p.unserved, "served": p.served,
            "routes": [{
                "vehicle": r.vehicle, "vehicle_type": r.vehicle_type,
                "capacity_t": r.capacity_t, "depot": r.depot, "visits": r.visits,
                "load_t": r.load_t, "distance_km": r.distance_km,
                "hours": round(r.hours, 1), "fuel_l": r.fuel_l,
                "cost_inr": r.cost_inr, "risk": r.risk,
                "eta_hours": round(r.eta_hours, 1),
                "slack_days": r.slack_days, "breached": r.breached,
                "legs": [{
                    "from": l.from_node, "to": l.to_node,
                    "corridor": l.corridor_code, "km": l.distance_km,
                    "road": l.road_class, "hours": round(l.hours, 2),
                    "risk": l.risk,
                } for l in r.legs],
            } for r in p.routes],
        }

    b, o = pack(base), pack(opt)
    return {
        "demands_t": demands, "horizon": body.horizon,
        "fleet": fleet, "closed": list(body.close), "adverse": body.adverse,
        "baseline": b, "optimised": o, "total_ms": elapsed,
        "improvement": {
            "distance_km": round(b["distance_km"] - o["distance_km"], 1),
            "distance_pct": round((b["distance_km"] - o["distance_km"])
                                  / max(b["distance_km"], 1e-9) * 100, 1),
            "cost_inr": round(b["cost_inr"] - o["cost_inr"]),
            "cost_pct": round((b["cost_inr"] - o["cost_inr"])
                              / max(b["cost_inr"], 1e-9) * 100, 1),
            "fuel_l": round(b["fuel_l"] - o["fuel_l"], 1),
            "utilisation_pct": round(o["utilisation_pct"] - b["utilisation_pct"], 1),
        },
        "cost_model": {
            "vehicle_base_inr_per_km": 58.0,
            "vehicle_tonne_inr_per_km": 13.0,
            "fuel_l_per_km_base": 0.28,
            "fuel_l_per_km_per_tonne": 0.055,
            "risk_cost_weight": 0.60,
        },
    }


class ConsolidateBody(BaseModel):
    lines: list[dict] = Field(default_factory=list)
    horizon: int = Field(14, ge=1, le=45)


@router.post("/plan/consolidate")
def plan_consolidate(body: ConsolidateBody) -> dict:
    w = repo.load_world()
    units = [n for n in w.nodes if n["type"] == "unit"]
    crit = [i for i in w.items if i["is_critical"]]
    lines = body.lines
    if not lines:
        queries = [(u["code"], it["code"]) for u in units for it in crit]
        fc = fs.forecast_batch(queries, horizon=body.horizon)
        item_meta = {i["code"]: i for i in w.items}
        for u in units:
            for it in crit:
                r = fc.get(f"{u['code']}|{it['code']}")
                if not r:
                    continue
                kg = r["total"]
                lines.append({
                    "code": it["code"], "name": it["name"],
                    "category": it["category"], "destination": u["code"],
                    "qty_kg": round(kg, 1),
                    "volume_l": round(kg * 0.62, 1),
                })
    fleet = [{"code": c["code"], "vehicle_type": c["vehicle_type"],
              "capacity_t": c["capacity_t"]} for c in w.convoys]
    result = consolidate(lines, fleet)
    result["total_kg"] = round(sum(l["qty_kg"] for l in lines), 1)
    return result


class ReallocateBody(BaseModel):
    to: str
    horizon: int = Field(14, ge=1, le=45)
    max_ship_t: float = Field(6.0, ge=0.5, le=14.0)


@router.post("/plan/reallocate")
def plan_reallocate(body: ReallocateBody) -> dict:
    w = repo.load_world()
    crit = [i for i in w.items if i["is_critical"]]
    if body.to not in w.node_by_code:
        raise HTTPException(status_code=404, detail="unknown node")
    node_id_code = {n["id"]: n["code"] for n in w.nodes}
    item_by_id = {i["id"]: i for i in w.items}

    balances: dict[str, dict[str, float]] = {}
    for inv in w.inventory:
        ncode = node_id_code[inv["node_id"]]
        it = item_by_id[inv["item_id"]]
        if not it["is_critical"]:
            continue
        floor = inv["min_level"] * (0.5 if w.node_by_code[ncode]["type"] != "unit" else 1.0)
        balances.setdefault(ncode, {})[it["code"]] = round(inv["on_hand"] - floor, 1)

    demands = {body.to: 12.0}
    g = TheatreGraph(w.corridors, w.node_by_code)
    fleet = [{"code": c["code"], "vehicle_type": c["vehicle_type"],
              "capacity_t": c["capacity_t"]} for c in w.convoys]
    moves = reallocate(g, balances, demands, fleet, max_ship_t=body.max_ship_t)
    moves = [m for m in moves if m["to"] == body.to]
    return {
        "movements": moves,
        "total_t": round(sum(m["qty_t"] for m in moves), 1),
        "total_cost_inr": round(sum(m["cost_inr"] for m in moves)),
        "from": sorted({m["from"] for m in moves}),
    }


# --------------------------------------------------------------------------- #
# Mission simulation  (the hero endpoint)
# --------------------------------------------------------------------------- #
class SimBody(BaseModel):
    scenario: str = "cloudburst"
    horizon: int = Field(14, ge=3, le=45)
    overrides: dict = Field(default_factory=dict)


@router.post("/simulate")
def simulate(body: SimBody, user: dict = Depends(whoami)) -> dict:
    if "simulate" not in user["perms"]:
        raise HTTPException(status_code=403, detail="Role cannot run simulations")
    try:
        result = sim.evaluate(
            body.scenario, overrides=body.overrides or None,
            horizon=body.horizon, username=user["username"],
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    sim_id = repo.save_simulation({
        "created_at": repo.now_iso(),
        "scenario": body.scenario,
        "label": result["label"],
        "params": result["params"],
        "solve_ms": result["solve_ms"],
        "solver": result["plans"]["rahat"]["solver"],
        "result": {
            "delta": result["delta"], "plans": result["plans"],
            "stranded": result["stranded"], "prestage_t": result["prestage_t"],
            "horizon": result["horizon"], "severity": result["severity"],
        },
        "username": user["username"],
    })
    result["id"] = sim_id
    repo.log_audit(user["username"], user["role"], "run_simulation", "simulation",
                   {"scenario": body.scenario, "solve_ms": result["solve_ms"]})
    return result


@router.get("/scenarios")
def scenarios() -> dict:
    return {"items": [
        {"key": s.key, "label": s.label, "description": s.description,
         "icon": s.icon, "severity": s.severity, "params": s.params,
         "talking_point": s.talking_point}
        for s in sim.SCENARIOS
    ]}


@router.get("/simulations")
def list_simulations(limit: int = Query(25, le=100)) -> dict:
    return {"items": repo.list_simulations(limit)}


@router.get("/simulations/{sim_id}")
def get_simulation(sim_id: int) -> dict:
    row = repo.get_simulation(sim_id)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    return row


@router.get("/simulations/{sim_id}/briefing", response_class=PlainTextResponse)
def briefing(sim_id: int) -> str:
    row = repo.get_simulation(sim_id)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    r = row.get("result", {})
    return (
        f"RAHAT BRIEFING NOTE - {row['label']}\n"
        f"Generated {row['created_at']} | Solver {row['solver']} | "
        f"{row['solve_ms']} ms | Horizon {r.get('horizon', 14)} days\n"
        f"Units at risk: {r.get('delta', {}).get('units_at_risk_before', 0)} -> "
        f"{r.get('delta', {}).get('units_at_risk_after', 0)}\n"
    )


# --------------------------------------------------------------------------- #
# Resilience
# --------------------------------------------------------------------------- #
@router.get("/resilience/fragility")
def fragility() -> dict:
    w = repo.load_world()
    units = [n for n in w.nodes if n["type"] == "unit"]
    depots = [n for n in w.nodes if n["type"] in ("depot", "railhead", "airfield")]
    t0 = time.perf_counter()
    data = resilience_domain.fragility(
        w.corridors, w.node_by_code, [d["code"] for d in depots],
        [u["code"] for u in units])
    data["compute_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return data


@router.get("/resilience/stress")
def stress(max_failures: int = Query(5, ge=1, le=10)) -> dict:
    w = repo.load_world()
    units = [n for n in w.nodes if n["type"] == "unit"]
    depots = [n for n in w.nodes if n["type"] in ("depot", "railhead", "airfield")]
    return resilience_domain.stress_curve(
        w.corridors, w.node_by_code, [d["code"] for d in depots],
        [u["code"] for u in units], max_failures=max_failures)


# --------------------------------------------------------------------------- #
# Admin / evidence
# --------------------------------------------------------------------------- #
@router.get("/admin/audit")
def audit(limit: int = Query(50, le=200)) -> dict:
    with repo.db.session_scope() as s:
        from sqlalchemy import select
        rows = s.execute(
            select(audit_t).order_by(audit_t.c.id.desc()).limit(limit)
        ).mappings().all()
    return {"items": [dict(r) for r in rows]}


@router.get("/admin/users")
def admin_users(user: dict = Depends(whoami)) -> dict:
    if "admin" not in user["perms"]:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return {"items": [
        {k: v for k, v in u.items() if k != "password_hash"}
        for u in repo.list_users()
    ]}


@router.post("/admin/retrain")
def retrain(user: dict = Depends(whoami)) -> dict:
    if "retrain" not in user["perms"]:
        raise HTTPException(status_code=403, detail="Role cannot retrain models")
    fs.reset()
    t0 = time.perf_counter()
    status = fs.status()
    fs.get_bundle()
    repo.log_audit(user["username"], user["role"], "retrain_models", "model")
    return {"ok": True, "before": status, "after": fs.status(),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #
@router.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket, token: str | None = None) -> None:
    await ws.accept()
    stream = telemetry.hub.subscribe()
    try:
        while True:
            msg = await anext(stream)
            await ws.send_json(msg)
    except (WebSocketDisconnect, StopAsyncIteration):
        pass
    finally:
        await stream.aclose()
