"""Deterministic theatre seeding.

Re-running ``seed`` with the same generator seed reproduces the theatre
byte-for-byte, which is why every number in the demo run-sheet stays stable
between rehearsals.
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import func, insert, select

from . import db
from . import repository as repo
from .auth import hash_password
from .config import settings
from .db import (
    alerts,
    audit_log,
    consumption,
    convoys,
    corridors,
    inventory,
    items,
    nodes,
    sensor_nodes,
    sensor_readings,
    users,
)
from .domain.theatre import build_theatre

DEMO_USERS = [
    # username, display name, role, can_override
    ("commander", "Maj Gen R. Sunder", "commander", True),
    ("logistics", "Lt Col A. Menon", "logistics_officer", True),
    ("quartermaster", "Maj P. Rathore", "quartermaster", False),
    ("admin", "System Administrator", "admin", True),
]


def _count(table) -> int:
    with db.session_scope() as s:
        return int(s.execute(select(func.count()).select_from(table)).scalar() or 0)


def _code_id(table, code_col="code") -> dict[str, int]:
    with db.session_scope() as s:
        rows = s.execute(select(table.c.id, table.c[code_col])).all()
    return {code: i for i, code in rows}


def seed(*, force: bool = False, verbose: bool = False) -> dict:
    if force:
        db.metadata.drop_all(db.engine())
    db.init_db()

    if _count(nodes) > 0 and not force:
        return {"skipped": True, "nodes": _count(nodes)}

    b = build_theatre(settings.theatre_seed, settings.history_days)
    ts = repo.now_iso()

    # ---- nodes ------------------------------------------------------------ #
    with db.session_scope() as s:
        s.execute(insert(nodes), [{**n, "tempo": "nominal"} for n in b.nodes])
    node_id = _code_id(nodes)

    # ---- corridors -------------------------------------------------------- #
    corr_rows = [{
        "code": c["code"], "name": c["name"],
        "from_node": node_id[c["from_node"]], "to_node": node_id[c["to_node"]],
        "distance_km": c["distance_km"], "grade_pct": c["grade_pct"],
        "capacity_t": c["capacity_t"], "road_class": c["road_class"],
        "all_weather": c["all_weather"], "closure_risk": c["closure_risk"],
        "altitude_pass_m": c["altitude_pass_m"], "path": c["path"],
    } for c in b.corridors]
    with db.session_scope() as s:
        s.execute(insert(corridors), corr_rows)

    # ---- items ------------------------------------------------------------ #
    with db.session_scope() as s:
        s.execute(insert(items), b.items)
    item_id = _code_id(items)

    # ---- inventory -------------------------------------------------------- #
    inv_rows = []
    for inv in b.inventory:
        nid, iid = node_id[inv["node_code"]], item_id[inv["item_code"]]
        inv_rows.append({
            "node_id": nid, "item_id": iid, "on_hand": inv["on_hand"],
            "reserved": inv["reserved"], "in_transit": inv["in_transit"],
            "min_level": inv["min_level"], "reorder_qty": inv["reorder_qty"],
            "updated_at": ts, "uq_node_item": f"{nid}-{iid}",
        })
    with db.session_scope() as s:
        s.execute(insert(inventory), inv_rows)

    # ---- consumption (the largest table) ---------------------------------- #
    cons_rows = [{
        "node_id": node_id[c["node_code"]], "item_id": item_id[c["item_code"]],
        "day": c["day"], "qty": c["qty"], "tempo": c["tempo"],
        "rainfall_mm": c["rainfall_mm"], "temp_c": c["temp_c"],
        "ops_flag": c["ops_flag"],
    } for c in b.consumption]
    with db.session_scope() as s:
        s.execute(insert(consumption), cons_rows)

    # ---- convoys ---------------------------------------------------------- #
    conv_rows = [{**c, "origin_node": node_id[c["origin_node"]],
                  "dest_node": node_id[c["dest_node"]]} for c in b.convoys]
    with db.session_scope() as s:
        s.execute(insert(convoys), conv_rows)

    # ---- sensor gateways --------------------------------------------------- #
    sensor_rows = [{
        "node_id": node_id[sn["node_code"]], "gateway": sn["gateway"],
        "protocol": sn["protocol"], "battery_pct": sn["battery_pct"],
        "signal_dbm": sn["signal_dbm"], "online": sn["online"],
        "last_seen": ts, "readings_24h": 0,
    } for sn in b.sensors]
    with db.session_scope() as s:
        s.execute(insert(sensor_nodes), sensor_rows)

    # ---- warm telemetry history so charts are never empty ----------------- #
    rng = np.random.default_rng(settings.theatre_seed + 7)
    reading_rows = []
    for sn in b.sensors:
        nid = node_id[sn["node_code"]]
        for _ in range(30):
            for kind, unit, lo, hi in (
                ("weight", "kg", 180.0, 940.0),
                ("temp", "C", -6.0, 14.0),
                ("humidity", "%", 32.0, 78.0),
            ):
                reading_rows.append({
                    "node_id": nid, "ts": ts, "kind": kind,
                    "value": round(float(rng.uniform(lo, hi)), 2), "unit": unit,
                    "online": sn["online"], "topic": f"rahat/{sn['gateway']}/{kind}",
                })
    with db.session_scope() as s:
        s.execute(insert(sensor_readings), reading_rows)

    # ---- alerts ------------------------------------------------------------ #
    alert_rows = [{
        "ts": ts, "severity": a["severity"], "type": a["type"],
        "node_id": node_id.get(a["node_code"]),
        "message": a["message"], "action": a["action"], "acknowledged": False,
    } for a in b.alerts]
    with db.session_scope() as s:
        s.execute(insert(alerts), alert_rows)

    # ---- users + audit ----------------------------------------------------- #
    with db.session_scope() as s:
        existing = {r[0] for r in s.execute(select(users.c.username)).all()}
        new_users = [
            {"username": u, "display_name": disp, "role": role,
             "password_hash": hash_password(u), "can_override": can,
             "created_at": ts}
            for u, disp, role, can in DEMO_USERS if u not in existing
        ]
        if new_users:
            s.execute(insert(users), new_users)
        s.execute(insert(audit_log), [{
            "ts": ts, "username": "system", "role": "admin",
            "action": "seed_theatre", "entity": "theatre",
            "detail": {"seed": settings.theatre_seed, "nodes": len(b.nodes),
                       "corridors": len(b.corridors), "items": len(b.items),
                       "consumption_rows": len(b.consumption)},
        }])

    repo.invalidate()
    stats = {
        "skipped": False, "seed": settings.theatre_seed,
        "nodes": len(b.nodes), "corridors": len(b.corridors),
        "items": len(b.items), "inventory_rows": len(inv_rows),
        "consumption_rows": len(cons_rows), "convoys": len(conv_rows),
        "sensors": len(sensor_rows), "readings": len(reading_rows),
        "alerts": len(alert_rows),
    }
    if verbose:
        print("RAHAT theatre seeded:", stats)
    return stats
