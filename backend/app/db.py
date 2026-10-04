"""Persistence layer.

Deliberately dialect-agnostic: SQLAlchemy Core with TEXT ISO-8601 keys and no
spatial extensions, so the *identical* schema runs on an edge node's embedded
SQLite and on a core node's PostgreSQL. All geometry (lat/lon) is stored as
plain floats and all spatial maths (haversine, projections, catchments) is done
in Python - which is what makes the whole platform air-gap friendly.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

NAMING = {"ix": "ix_%(table_name)s_%(column_0_name)s", "uq": "uq_%(table_name)s_%(column_0_name)s"}
metadata = MetaData(naming_convention=NAMING)

# --------------------------------------------------------------------------- #
# Identity, audit, RBAC
# --------------------------------------------------------------------------- #
users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(64), unique=True, nullable=False, index=True),
    Column("display_name", String(120), nullable=False),
    Column("role", String(32), nullable=False),  # commander | logistics_officer | quartermaster | admin
    Column("password_hash", String(128), nullable=False),
    Column("can_override", Boolean, default=False),
    Column("created_at", String(30), nullable=False),
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("ts", String(30), nullable=False, index=True),
    Column("username", String(64), nullable=False),
    Column("role", String(32), nullable=False),
    Column("action", String(64), nullable=False),
    Column("entity", String(64), default=""),
    Column("detail", JSON, default=dict),
)

# --------------------------------------------------------------------------- #
# Theatre graph
# --------------------------------------------------------------------------- #
nodes = Table(
    "nodes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", String(16), unique=True, nullable=False, index=True),
    Column("name", String(120), nullable=False),
    # unit | depot | railhead | airfield
    Column("type", String(20), nullable=False, index=True),
    Column("lat", Float, nullable=False),
    Column("lon", Float, nullable=False),
    Column("elevation_m", Integer, default=0),
    Column("personnel", Integer, default=0),
    Column("district", String(60), default=""),
    Column("access_road", String(40), default=""),
    # kilometres to the nearest all-weather road: the isolation metric
    Column("isolation_km", Float, default=0.0),
    Column("capacity_t", Float, default=0.0),      # nodes only
    Column("tempo", String(16), default="nominal"),  # low | nominal | high
    Column("is_critical", Boolean, default=False),
)

corridors = Table(
    "corridors",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", String(16), unique=True, nullable=False, index=True),
    Column("name", String(120), nullable=False),
    Column("from_node", Integer, nullable=False, index=True),
    Column("to_node", Integer, nullable=False, index=True),
    Column("distance_km", Float, nullable=False),
    Column("grade_pct", Float, default=0.0),
    Column("capacity_t", Float, default=0.0),        # max single-vehicle payload class
    Column("road_class", String(24), default=""),    # NH | SH | KUC | ALP
    Column("all_weather", Boolean, default=True),
    Column("closure_risk", Float, default=0.0),      # 0..1 baseline monsoon/flood risk
    Column("altitude_pass_m", Integer, default=0),
    # Control points the UI uses to draw the polyline through terrain.
    Column("path", JSON, default=list),
)

# --------------------------------------------------------------------------- #
# Stores
# --------------------------------------------------------------------------- #
items = Table(
    "items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", String(16), unique=True, nullable=False, index=True),
    Column("name", String(80), nullable=False),
    Column("category", String(24), nullable=False, index=True),  # ration|pol|ammo|maintenance|medical|water|sundry
    Column("unit", String(12), default="kg"),
    Column("weight_kg", Float, default=1.0),
    Column("volume_l", Float, default=1.0),
    Column("shelf_life_days", Integer, default=180),
    Column("pack_size", Float, default=1.0),
    Column("unit_cost", Float, default=100.0),
    Column("is_critical", Boolean, default=False),
)

inventory = Table(
    "inventory",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("node_id", Integer, nullable=False, index=True),
    Column("item_id", Integer, nullable=False, index=True),
    Column("on_hand", Float, default=0.0),
    Column("reserved", Float, default=0.0),
    Column("in_transit", Float, default=0.0),
    Column("min_level", Float, default=0.0),
    Column("reorder_qty", Float, default=0.0),
    Column("updated_at", String(30), nullable=False),
    Column("uq_node_item", String(40), unique=True),
)

# Daily consumption actuals (hypertable-equivalent; timeseries facts).
consumption = Table(
    "consumption",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("node_id", Integer, nullable=False, index=True),
    Column("item_id", Integer, nullable=False, index=True),
    Column("day", String(10), nullable=False, index=True),
    Column("qty", Float, nullable=False),
    Column("tempo", String(16), default="nominal"),
    Column("rainfall_mm", Float, default=0.0),
    Column("temp_c", Float, default=0.0),
    Column("ops_flag", Integer, default=0),
)

# Cached forecast runs (persisted so the demo is instant and auditable).
forecasts = Table(
    "forecasts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("node_id", Integer, nullable=False, index=True),
    Column("item_id", Integer, nullable=False, index=True),
    Column("horizon_d", Integer, nullable=False),
    Column("generated_at", String(30), nullable=False),
    Column("model", String(40), nullable=False),
    Column("mape", Float, default=0.0),
    Column("mase", Float, default=0.0),
    Column("mae", Float, default=0.0),
    Column("pinball", Float, default=0.0),
    Column("series", JSON, default=list),   # [{day,p10,p50,p90,actual}]
    Column("attribution", JSON, default=list),
    Column("metrics", JSON, default=list),  # model leaderboard for this pair
)

# --------------------------------------------------------------------------- #
# Movement
# --------------------------------------------------------------------------- #
convoys = Table(
    "convoys",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", String(16), unique=True, nullable=False, index=True),
    Column("vehicle_type", String(40), default=""),
    Column("capacity_t", Float, nullable=False),
    Column("status", String(24), default="planned"),  # planned|loading|in_transit|delivered|held
    Column("origin_node", Integer, nullable=False),
    Column("dest_node", Integer, nullable=False),
    Column("load_t", Float, default=0.0),
    Column("distance_km", Float, default=0.0),
    Column("fuel_l", Float, default=0.0),
    Column("depart_ts", String(30), default=""),
    Column("eta_ts", String(30), default=""),
    Column("risk_score", Float, default=0.0),
    Column("plan_id", String(40), index=True),
    Column("kind", String(24), default="planned"),  # planned | reallocation | prestage
    Column("manifest", JSON, default=list),
)

legs = Table(
    "legs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("convoy_id", Integer, nullable=False, index=True),
    Column("seq", Integer, nullable=False),
    Column("from_node", Integer, nullable=False),
    Column("to_node", Integer, nullable=False),
    Column("corridor_id", Integer, nullable=False),
    Column("distance_km", Float, default=0.0),
    Column("eta_ts", String(30), default=""),
    Column("risk", Float, default=0.0),
    Column("status", String(24), default="planned"),
)

alerts = Table(
    "alerts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("ts", String(30), nullable=False, index=True),
    Column("severity", String(16), nullable=False),  # critical|warning|info
    Column("type", String(40), nullable=False),
    Column("node_id", Integer, nullable=True),
    Column("corridor_id", Integer, nullable=True),
    Column("message", String(400), nullable=False),
    Column("action", String(64), default=""),
    Column("acknowledged", Boolean, default=False),
    Column("sim_id", Integer, nullable=True),
)

simulations = Table(
    "simulations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("created_at", String(30), nullable=False, index=True),
    Column("scenario", String(64), nullable=False),
    Column("label", String(160), default=""),
    Column("params", JSON, default=dict),
    Column("solve_ms", Float, default=0.0),
    Column("solver", String(40), default=""),
    Column("result", JSON, default=dict),
    Column("username", String(64), default=""),
)

sensor_readings = Table(
    "sensor_readings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("node_id", Integer, nullable=False, index=True),
    Column("ts", String(30), nullable=False, index=True),
    Column("kind", String(24), nullable=False),   # weight|temp|humidity|rfid|battery
    Column("value", Float, nullable=False),
    Column("unit", String(12), default=""),
    Column("online", Boolean, default=True),
    Column("topic", String(120), default=""),
)

sensor_nodes = Table(
    "sensor_nodes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("node_id", Integer, unique=True, nullable=False),
    Column("gateway", String(40), default=""),
    Column("protocol", String(16), default="MQTT"),
    Column("battery_pct", Float, default=100.0),
    Column("signal_dbm", Float, default=-70.0),
    Column("online", Boolean, default=True),
    Column("last_seen", String(30), default=""),
    Column("readings_24h", Integer, default=0),
)


# --------------------------------------------------------------------------- #
# Engine / session management
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _engine() -> Engine:
    url = settings.database_url
    eng = create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )
    if url.startswith("sqlite"):
        # WAL keeps the demo responsive while the telemetry writer runs.
        @event.listens_for(eng, "connect")
        def _set_sqlite_pragma(dbapi_connection, _record):  # noqa: ANN001
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    return eng


def engine() -> Engine:
    return _engine()


def init_db() -> None:
    metadata.create_all(engine())


def reset_db() -> None:
    metadata.drop_all(engine())


SessionFactory = sessionmaker(bind=_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
