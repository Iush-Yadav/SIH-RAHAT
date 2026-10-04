"""Repository layer.

All SQL lives here. ``load_world()`` returns the whole theatre in one pass and
is cached behind a version counter that any mutation bumps, so the dashboard
never issues a dozen queries to render - and never serves stale data after a
scenario is committed.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import delete, insert, select, update

from . import db
from .db import (
    alerts,
    audit_log,
    consumption,
    convoys,
    corridors,
    forecasts,
    inventory,
    items,
    legs,
    nodes,
    sensor_nodes,
    sensor_readings,
    simulations,
    users,
)

_lock = threading.Lock()
_version = 0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bump() -> None:
    global _version
    with _lock:
        _version += 1


def version() -> int:
    return _version


# --------------------------------------------------------------------------- #
# World
# --------------------------------------------------------------------------- #
@dataclass
class World:
    nodes: list[dict] = field(default_factory=list)
    corridors: list[dict] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    inventory: list[dict] = field(default_factory=list)
    consumption: list[dict] = field(default_factory=list)
    convoys: list[dict] = field(default_factory=list)
    legs: dict[int, list[dict]] = field(default_factory=dict)
    alerts: list[dict] = field(default_factory=list)
    sensors: list[dict] = field(default_factory=list)
    node_by_code: dict[str, dict] = field(default_factory=dict)
    item_by_code: dict[str, dict] = field(default_factory=dict)
    loaded_at: float = 0.0

    # ---- derived helpers ------------------------------------------------- #
    def history(self, node_code: str, item_code: str) -> np.ndarray:
        rows = self._cons_index.get((node_code, item_code), [])
        return np.array([r["qty"] for r in rows], dtype=float)

    def weather(self, node_code: str) -> tuple[np.ndarray, np.ndarray]:
        rows = self._cons_index.get((node_code, self.items[0]["code"]), [])
        return (
            np.array([r["rainfall_mm"] for r in rows], dtype=float),
            np.array([r["temp_c"] for r in rows], dtype=float),
        )

    _cons_index: dict = field(default_factory=dict, repr=False)


_WORLD: World | None = None


def _rows(table) -> list[dict]:
    with db.session_scope() as s:
        return [dict(r) for r in s.execute(select(table)).mappings().all()]


def invalidate() -> None:
    global _WORLD
    with _lock:
        _WORLD = None


def load_world(*, force: bool = False) -> World:
    global _WORLD
    if _WORLD is not None and not force:
        return _WORLD

    w = World()
    w.nodes = _rows(nodes)
    w.corridors = _rows(corridors)
    w.items = _rows(items)
    w.inventory = _rows(inventory)
    w.consumption = sorted(_rows(consumption), key=lambda r: (r["node_id"], r["item_id"], r["day"]))
    w.convoys = _rows(convoys)
    w.alerts = sorted(_rows(alerts), key=lambda r: r["ts"], reverse=True)
    w.sensors = _rows(sensor_nodes)

    # Corridors are stored with integer FKs; the graph/resilience/simulation
    # layers all address nodes by code, so resolve once here. The original ids
    # are preserved as from_id/to_id for anything that needs to join back.
    id_to_code = {n["id"]: n["code"] for n in w.nodes}
    for c in w.corridors:
        c["from_id"], c["to_id"] = c["from_node"], c["to_node"]
        c["from_node"] = id_to_code.get(c["from_node"], "")
        c["to_node"] = id_to_code.get(c["to_node"], "")

    with db.session_scope() as s:
        leg_rows = [dict(r) for r in s.execute(select(legs)).mappings().all()]
    by_convoy: dict[int, list[dict]] = defaultdict(list)
    for lg in leg_rows:
        by_convoy[lg["convoy_id"]].append(lg)
    for k in by_convoy:
        by_convoy[k].sort(key=lambda x: x["seq"])
    w.legs = dict(by_convoy)

    w.node_by_code = {n["code"]: n for n in w.nodes}
    w.item_by_code = {it["code"]: it for it in w.items}

    # day-sorted consumption per (node,item)
    idx: dict[tuple, list[dict]] = defaultdict(list)
    for c in w.consumption:
        idx[(c["node_id"], c["item_id"])].append(c)
    node_id_code = {n["id"]: n["code"] for n in w.nodes}
    item_id_code = {i["id"]: i["code"] for i in w.items}
    w._cons_index = {
        (node_id_code[nid], item_id_code[iid]): sorted(rows, key=lambda r: r["day"])
        for (nid, iid), rows in idx.items()
    }
    w.loaded_at = time.time()
    _WORLD = w
    return w


# --------------------------------------------------------------------------- #
# Queries used by the API
# --------------------------------------------------------------------------- #
def get_forecast_cache(node_id: int, item_id: int, horizon: int) -> dict | None:
    with db.session_scope() as s:
        row = s.execute(
            select(forecasts)
            .where(
                forecasts.c.node_id == node_id,
                forecasts.c.item_id == item_id,
                forecasts.c.horizon_d == horizon,
            )
            .order_by(forecasts.c.generated_at.desc())
            .limit(1)
        ).mappings().first()
        return dict(row) if row else None


def save_forecast(node_id: int, item_id: int, horizon: int, payload: dict) -> None:
    with db.session_scope() as s:
        s.execute(insert(forecasts).values(
            node_id=node_id, item_id=item_id, horizon_d=horizon,
            generated_at=now_iso(), model=payload["model"],
            mape=payload["mape"], mase=payload["mase"], mae=payload["mae"],
            pinball=payload.get("pinball", 0.0),
            series=payload["series"], attribution=payload["attribution"],
            metrics=payload["metrics"],
        ))
    bump()


def save_simulation(payload: dict) -> int:
    with db.session_scope() as s:
        res = s.execute(insert(simulations).values(**payload))
        sim_id = int(res.inserted_primary_key[0])
    bump()
    return sim_id


def list_simulations(limit: int = 25) -> list[dict]:
    with db.session_scope() as s:
        rows = s.execute(
            select(simulations).order_by(simulations.c.id.desc()).limit(limit)
        ).mappings().all()
        return [dict(r) for r in rows]


def get_simulation(sim_id: int) -> dict | None:
    with db.session_scope() as s:
        row = s.execute(select(simulations).where(simulations.c.id == sim_id)).mappings().first()
        return dict(row) if row else None


def add_alert(payload: dict) -> None:
    with db.session_scope() as s:
        s.execute(insert(alerts).values(**payload))
    bump()


def acknowledge_alert(alert_id: int, username: str) -> None:
    with db.session_scope() as s:
        s.execute(update(alerts).where(alerts.c.id == alert_id).values(acknowledged=True))
        s.execute(insert(audit_log).values(
            ts=now_iso(), username=username, role="system", action="acknowledge_alert",
            entity="alert", detail={"id": alert_id},
        ))
    bump()


def log_audit(username: str, role: str, action: str, entity: str = "", detail: dict | None = None) -> None:
    with db.session_scope() as s:
        s.execute(insert(audit_log).values(
            ts=now_iso(), username=username, role=role, action=action,
            entity=entity, detail=detail or {},
        ))


def list_audit(limit: int = 50) -> list[dict]:
    with db.session_scope() as s:
        rows = s.execute(
            select(audit_log).order_by(audit_log.c.id.desc()).limit(limit)
        ).mappings().all()
        return [dict(r) for r in rows]


def clear_tables(*tables) -> None:
    with db.session_scope() as s:
        for t in tables:
            s.execute(delete(t))
    invalidate()


def find_user(username: str) -> dict | None:
    with db.session_scope() as s:
        row = s.execute(select(users).where(users.c.username == username)).mappings().first()
        return dict(row) if row else None


def list_users() -> list[dict]:
    return _rows(users)


def record_readings(batch: list[dict]) -> None:
    """Bulk-append telemetry. Called by the in-process sensor bus."""
    if not batch:
        return
    with db.session_scope() as s:
        s.execute(insert(sensor_readings), batch)
