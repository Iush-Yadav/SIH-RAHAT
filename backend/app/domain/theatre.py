"""Synthetic theatre generator.

No operational data was accessible or used for this build, so RAHAT ships a
*calibrated synthetic theatre*: a deterministic generator (fixed seed) shaped by
open public inputs - a stylised north-rising elevation field in the spirit of
SRTM, an OSM-like corridor graph with class/all-weather attributes, an
IMD-like monsoon rainfall curve, and per-person consumption norms in the range
of published ration scales.

Everything is reproducible: same seed => byte-identical theatre, so the numbers
you put on a slide today still match when you rehearse on stage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from .geo import bezier_path, haversine_km

TODAY = date(2026, 10, 3)

# --------------------------------------------------------------------------- #
# Stylised DEM (elevation in metres)
# --------------------------------------------------------------------------- #
def elevation_at(lat: float, lon: float) -> int:
    dlat, dlon = lat - 34.0, lon - 77.0
    base = 1250 + 1750 * (lat - 34.0)                       # rises northward
    ridge = 1050 * math.exp(-(((lat - 35.30) ** 2) / 0.035))  # northern wall
    waves = (
        340 * math.sin(3.1 * dlon + 1.7)
        + 250 * math.cos(2.4 * dlat - 0.9)
        + 165 * math.sin(5.3 * dlon + 2.4 * dlat)
    )
    valley = -420 * math.exp(-(((dlon - 0.30) ** 2) / 0.012))  # main river valley
    return int(max(480, min(5750, base + ridge + waves + valley)))


# --------------------------------------------------------------------------- #
# Item master (14 stores, 7 categories)
# --------------------------------------------------------------------------- #
ITEMS: list[dict] = [
    dict(code="RAT-COM", name="Composite Ration (10-day pack)", category="ration",
         kg_pp_day=1.62, shelf=180, pack=12.5, cost=430.0, critical=True),
    dict(code="RAT-VEG", name="Fresh Vegetables", category="ration",
         kg_pp_day=0.34, shelf=7, pack=5.0, cost=85.0, critical=False),
    dict(code="POL-DIE", name="Diesel", category="pol",
         kg_pp_day=6.40, shelf=365, pack=200.0, cost=92.0, critical=True),
    dict(code="POL-PET", name="Petrol", category="pol",
         kg_pp_day=1.75, shelf=365, pack=200.0, cost=105.0, critical=False),
    dict(code="AMM-556", name="5.56 mm Ammunition Stock", category="ammo",
         kg_pp_day=0.24, shelf=1825, pack=25.0, cost=1180.0, critical=True),
    dict(code="AMM-MED", name="Mortar Ammunition", category="ammo",
         kg_pp_day=1.38, shelf=1825, pack=45.0, cost=3400.0, critical=True),
    dict(code="MED-TRA", name="Trauma Medical Kit", category="medical",
         kg_pp_day=0.11, shelf=365, pack=3.2, cost=2650.0, critical=True),
    dict(code="MED-ANT", name="Antibiotic & Antimalarial Course", category="medical",
         kg_pp_day=0.05, shelf=540, pack=0.4, cost=640.0, critical=False),
    dict(code="WAT-POT", name="Potable Water", category="water",
         kg_pp_day=9.10, shelf=30, pack=20.0, cost=48.0, critical=True),
    dict(code="WAT-BCN", name="Water Purification Chemicals", category="water",
         kg_pp_day=0.08, shelf=720, pack=1.0, cost=780.0, critical=False),
    dict(code="MNT-SPR", name="Vehicle Spares & Tyres", category="maintenance",
         kg_pp_day=1.06, shelf=900, pack=18.0, cost=5200.0, critical=False),
    dict(code="MNT-GEN", name="Generator & Plant Spares", category="maintenance",
         kg_pp_day=0.38, shelf=900, pack=9.0, cost=7300.0, critical=False),
    dict(code="SUN-CLC", name="Clothing & Cold Weather Kit", category="sundry",
         kg_pp_day=0.21, shelf=1095, pack=4.0, cost=1900.0, critical=False),
    dict(code="SUN-LPG", name="LPG (Cooking & Heating)", category="sundry",
         kg_pp_day=0.58, shelf=720, pack=19.0, cost=310.0, critical=False),
]

# --------------------------------------------------------------------------- #
# Theatre layout - rear sustainment base, forward dumps, dispersed forward units
# --------------------------------------------------------------------------- #
NODES: list[dict] = [
    dict(code="RH-01", name="Railhead USTI", type="railhead", lat=34.055, lon=77.115,
         personnel=140, district="Kargil Sector", access_road="NH-1", critical=True),
    dict(code="DP-A", name="Base Depot ALPHA", type="depot", lat=34.175, lon=77.360,
         personnel=260, district="Kargil Sector", access_road="NH-1", capacity_t=1800.0,
         critical=True),
    dict(code="AF-01", name="Airfield SIA", type="airfield", lat=34.105, lon=77.640,
         personnel=180, district="Kargil Sector", access_road="NH-1", capacity_t=420.0,
         critical=True),
    dict(code="DP-CT", name="Transit Camp CHARLIE", type="depot", lat=34.565, lon=77.225,
         personnel=120, district="Zanskar Approach", access_road="SH-2", capacity_t=640.0),
    dict(code="DP-B", name="Forward Dump BRAVO", type="depot", lat=34.640, lon=77.815,
         personnel=150, district="Hanle Sector", access_road="SH-4", capacity_t=760.0),
    dict(code="U-12", name="Unit JULIET", type="unit", lat=34.945, lon=77.045,
         personnel=520, district="Zanskar Approach", access_road="KUC-7"),
    dict(code="U-63", name="Unit ROMEO", type="unit", lat=35.065, lon=76.995,
         personnel=465, district="Zanskar Approach", access_road="KUC-7"),
    dict(code="U-21", name="Unit KILO", type="unit", lat=35.330, lon=77.395,
         personnel=610, district="Northern Ridge", access_road="KUC-11", critical=True),
    dict(code="U-47", name="Unit OSCAR", type="unit", lat=35.245, lon=77.955,
         personnel=575, district="Hanle Sector", access_road="SH-4"),
    dict(code="U-34", name="Unit MIKE", type="unit", lat=35.095, lon=78.215,
         personnel=495, district="Hanle Sector", access_road="SH-4"),
    dict(code="U-56", name="Unit PAPA", type="unit", lat=34.795, lon=78.360,
         personnel=430, district="Changtang Flank", access_road="KUC-3"),
]

# (from, to, road class, all-weather, closure risk, capacity t, max grade %, bend km)
CORRIDORS: list[tuple] = [
    ("RH-01", "DP-A", "NH", True, 0.05, 45.0, 2.1, 0.6),
    ("DP-A", "AF-01", "NH", True, 0.06, 45.0, 2.4, -0.7),
    ("DP-A", "DP-CT", "SH", True, 0.18, 32.0, 4.8, 1.3),
    ("RH-01", "DP-CT", "SH", True, 0.22, 32.0, 5.2, -1.1),
    ("DP-A", "DP-B", "SH", True, 0.24, 32.0, 5.9, 2.4),   # long alternate
    ("AF-01", "DP-B", "SH", True, 0.26, 30.0, 5.1, -1.8),
    ("DP-CT", "DP-B", "SH", True, 0.31, 30.0, 6.4, 1.9),
    ("DP-CT", "U-12", "KUC", True, 0.34, 24.0, 7.2, 1.4),
    ("DP-B", "U-12", "KUC", True, 0.42, 24.0, 8.6, -2.2),  # alternate into U-12
    ("DP-CT", "U-63", "KUC", True, 0.45, 22.0, 8.1, 1.7),
    ("U-12", "U-63", "KUC", True, 0.40, 22.0, 7.6, -1.2),
    ("U-63", "U-21", "SH", True, 0.44, 26.0, 9.4, 2.6),    # THE chokepoint
    ("U-47", "U-21", "ALP", False, 0.66, 14.0, 12.8, -3.1),  # weather-dependent alt
    ("DP-B", "U-47", "KUC", True, 0.36, 24.0, 7.8, 1.5),
    ("U-21", "U-47", "KUC", True, 0.47, 24.0, 9.9, 2.1),
    ("U-47", "U-34", "KUC", True, 0.33, 24.0, 6.9, -1.6),
    ("DP-B", "U-34", "KUC", True, 0.35, 24.0, 6.2, 1.8),
    ("U-34", "U-56", "KUC", True, 0.30, 24.0, 5.4, -1.4),
    ("DP-B", "U-56", "KUC", True, 0.38, 24.0, 6.7, 2.3),
    ("U-56", "U-12", "ALP", False, 0.61, 16.0, 11.5, -2.8),  # long flank alternate
]

NODE_CODE = {n["code"]: i for i, n in enumerate(NODES, start=1)}


# --------------------------------------------------------------------------- #
# Daily driver series
# --------------------------------------------------------------------------- #
def weather_series(seed: int, days: int, nodes: list[dict]) -> dict[str, np.ndarray]:
    """Per-node daily rainfall (mm) and mean temperature (C).

    Shape follows an IMD-like monsoon: heavy Jun-Sep, retreating through Oct,
    with a node-level spatial multiplier (wettest in the north-west) and an
    elevation lapse rate for temperature.
    """
    rng = np.random.default_rng(seed)
    end = TODAY
    daylist = [end - timedelta(days=days - 1 - i) for i in range(days)]
    doy = np.array([d.timetuple().tm_yday for d in daylist])

    # Monsoon envelope: peaks ~ day 195 (mid-July), retreats through Oct.
    envelope = 9.5 * np.exp(-(((doy - 196.0) ** 2) / (2 * 46.0 ** 2)))
    envelope = envelope + 1.4 * np.exp(-(((doy - 40.0) ** 2) / (2 * 30.0 ** 2)))  # western disturbance

    rainfall: dict[str, np.ndarray] = {}
    temperature: dict[str, np.ndarray] = {}
    for n in nodes:
        spatial = 0.72 + 0.05 * (n["lat"] - 34.0) + 0.30 * ((n["lon"] - 77.0) < 0)
        # Gamma-ish bursts: cloudburst days are rare but large.
        burst = rng.gamma(shape=0.55, scale=1.9, size=days)
        wet = envelope * spatial * burst
        dry = rng.random(days) < 0.31
        rainfall[n["code"]] = np.where(dry, wet * 0.18, wet).round(2)

        lapse = -6.1 * (elevation_at(n["lat"], n["lon"]) - 1500.0) / 1000.0
        seasonal = -7.4 * np.cos(2 * np.pi * (doy - 15.0) / 365.0)
        temperature[n["code"]] = (
            6.5 + seasonal + lapse + rng.normal(0, 2.0, days)
        ).round(1)

    return {
        "days": np.array([d.isoformat() for d in daylist]),
        "rainfall": rainfall,
        "temperature": temperature,
    }


def tempo_schedule(seed: int, days: int) -> tuple[np.ndarray, np.ndarray]:
    """Returns (tempo_label, ops_flag) per day - nominal rhythm punctuated by
    two field exercises, which is what gives the ML model real variance to learn."""
    rng = np.random.default_rng(seed + 991)
    labels = np.array(["nominal"] * days, dtype=object)
    flags = np.zeros(days, dtype=int)

    # Exercise windows at 22-31% and 63-70% of the window.
    for start_f, length in ((0.22, 10), (0.63, 8)):
        s = int(days * start_f)
        e = min(days, s + length)
        labels[s:e] = "high"
        flags[s:e] = 1
    # A quiet stand-down block for class separation.
    q0, q1 = int(days * 0.44), int(days * 0.50)
    labels[q0:q1] = "low"

    # Node-level variation: forward units run hotter than rear depots.
    return labels, flags


TEMPO_FACTOR = {"low": 0.84, "nominal": 1.0, "high": 1.42}


@dataclass
class TheatreBundle:
    nodes: list[dict] = field(default_factory=list)
    corridors: list[dict] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    inventory: list[dict] = field(default_factory=list)
    consumption: list[dict] = field(default_factory=list)
    weather_days: list[str] = field(default_factory=list)
    weather: dict = field(default_factory=dict)
    convoys: list[dict] = field(default_factory=list)
    sensors: list[dict] = field(default_factory=list)
    alerts: list[dict] = field(default_factory=list)


def build_theatre(seed: int = 20261005, history_days: int = 112) -> TheatreBundle:
    rng = np.random.default_rng(seed)
    b = TheatreBundle()

    # ---- nodes ------------------------------------------------------------ #
    for code, n in enumerate(NODES, start=1):
        elev = elevation_at(n["lat"], n["lon"])
        # Isolation: distance to the nearest NH/SH all-weather road, which for
        # these nodes is approximated by distance to the nearest rear/mid node.
        rear = [x for x in NODES if x["type"] in ("depot", "railhead", "airfield")]
        iso = min(haversine_km(n["lat"], n["lon"], r["lat"], r["lon"]) for r in rear)
        b.nodes.append(
            dict(
                code=n["code"], name=n["name"], type=n["type"], lat=n["lat"],
                lon=n["lon"], elevation_m=elev, personnel=n["personnel"],
                district=n["district"], access_road=n["access_road"],
                isolation_km=round(iso, 1), capacity_t=n.get("capacity_t", 0.0),
                tempo="nominal", is_critical=bool(n.get("critical", False)),
            )
        )

    # ---- corridors -------------------------------------------------------- #
    idx = {n["code"]: n for n in b.nodes}
    for i, (a, c, rc, aw, risk, cap, grade, bend) in enumerate(CORRIDORS, start=1):
        na, nc = idx[a], idx[c]
        straight = haversine_km(na["lat"], na["lon"], nc["lat"], nc["lon"])
        # Roads are never straight: a road-class factor plus grade penalties.
        factor = {"NH": 1.12, "SH": 1.18, "KUC": 1.30, "ALP": 1.42}[rc]
        dist = round(straight * factor * (1 + grade / 220.0), 2)
        alt = int(max(na["elevation_m"], nc["elevation_m"]) + grade * 11 + 380)
        b.corridors.append(
            dict(
                code=f"C-{i:02d}", name=f"{na['code']} - {nc['code']} ({rc})",
                from_node=na["code"], to_node=nc["code"], distance_km=dist,
                grade_pct=grade, capacity_t=cap, road_class=rc,
                all_weather=bool(aw), closure_risk=float(risk),
                altitude_pass_m=alt,
                path=bezier_path(na["lat"], na["lon"], nc["lat"], nc["lon"], bend_km=bend),
            )
        )

    # ---- items ------------------------------------------------------------ #
    for it in ITEMS:
        b.items.append(
            dict(
                code=it["code"], name=it["name"], category=it["category"],
                unit="kg", weight_kg=1.0,
                volume_l=round(max(0.4, it["kg_pp_day"] * 1.15), 2),
                shelf_life_days=it["shelf"], pack_size=it["pack"],
                unit_cost=it["cost"], is_critical=it["critical"],
            )
        )

    # ---- weather + tempo --------------------------------------------------- #
    w = weather_series(seed, history_days, b.nodes)
    tempo, ops = tempo_schedule(seed, history_days)
    b.weather_days = list(w["days"])
    b.weather = w

    # ---- consumption ------------------------------------------------------- #
    node_tempo_factor = {
        n["code"]: (1.06 if n["type"] == "unit" else 0.97) for n in b.nodes
    }
    for n in b.nodes:
        rain = w["rainfall"][n["code"]]
        temp = w["temperature"][n["code"]]
        for it in ITEMS:
            base = it["kg_pp_day"] * n["personnel"] * node_tempo_factor[n["code"]]
            qty = np.empty(history_days, dtype=float)
            for d in range(history_days):
                tf = TEMPO_FACTOR[tempo[d]]
                # Exercise days: ammo/maintenance spike, stores are drawn down.
                if ops[d]:
                    if it["category"] == "ammo":
                        tf *= 4.1
                    elif it["category"] == "maintenance":
                        tf *= 2.0
                    elif it["category"] == "ration":
                        tf *= 1.18
                elif tempo[d] == "low":
                    if it["category"] == "ammo":
                        tf *= 0.25

                wf = 1.0
                if it["code"] == "WAT-POT":
                    wf += 0.011 * rain[d]
                elif it["code"] == "MED-ANT":
                    wf += 0.019 * rain[d]
                elif it["code"] == "MED-TRA":
                    wf += 0.014 * rain[d]
                elif it["code"] in ("POL-DIE", "SUN-LPG"):
                    wf += max(0.0, (4.0 - temp[d])) * 0.031   # heating load
                    wf += 0.004 * rain[d]
                elif it["code"] == "RAT-VEG":
                    wf -= min(0.18, 0.004 * rain[d])

                dow = 1.0 + (0.035 if (d + 3) % 7 in (5, 6) else 0.0)
                noise = rng.normal(1.0, 0.055)
                # Mild upward drift in ration/stores as the deployment matures.
                drift = 1.0 + 0.0007 * d
                v = base * tf * wf * dow * drift * max(0.55, noise)
                qty[d] = max(0.0, round(v, 3))

                b.consumption.append(
                    dict(
                        node_code=n["code"], item_code=it["code"],
                        day=w["days"][d], qty=float(qty[d]),
                        tempo=tempo[d], rainfall_mm=float(rain[d]),
                        temp_c=float(temp[d]), ops_flag=int(ops[d]),
                    )
                )

    # ---- inventory --------------------------------------------------------- #
    day0 = w["days"][-14]
    for n in b.nodes:
        for it in ITEMS:
            hist = [
                c["qty"] for c in b.consumption
                if c["node_code"] == n["code"] and c["item_code"] == it["code"]
            ]
            avg = float(np.mean(hist[-21:]))
            min_level = avg * (7.5 if it["critical"] else 10.5)
            # Deliberate spread: a small minority of critical lines sit below
            # reorder point so the War Room has real alerts to show on first
            # load, while the theatre as a whole is *stressed, not failing* -
            # roughly one item in eight below min level and two to three forward
            # units carrying a shortfall. That leaves the simulation somewhere
            # to go: a board that starts entirely red cannot demonstrate
            # improvement.
            health = float(rng.uniform(1.05, 2.15))
            if it["critical"] and rng.random() < 0.12:
                health = float(rng.uniform(0.42, 0.85))
            on_hand = round(min_level * health, 1)
            b.inventory.append(
                dict(
                    node_code=n["code"], item_code=it["code"],
                    on_hand=on_hand,
                    reserved=round(on_hand * float(rng.uniform(0.0, 0.09)), 1),
                    in_transit=round(avg * float(rng.uniform(0.0, 5.5)), 1)
                    if on_hand / max(avg, 1e-6) < 9 else 0.0,
                    min_level=round(min_level, 1),
                    reorder_qty=round(avg * 9.0, 1),
                )
            )

    # ---- planned / in-transit convoys ------------------------------------- #
    fleet = [
        ("CNV-101", "Scorpio-LE (4.5 t)", 4.5, "DP-A", "U-12", 3.9, "in_transit"),
        ("CNV-102", "Tata-LS (9.0 t)", 9.0, "DP-B", "U-47", 7.6, "in_transit"),
        ("CNV-103", "Kraz (12.0 t)", 12.0, "DP-CT", "U-63", 10.4, "loading"),
        ("CNV-104", "Scorpio-LE (4.5 t)", 4.5, "DP-A", "DP-CT", 4.1, "planned"),
        ("CNV-105", "Tata-LS (9.0 t)", 9.0, "AF-01", "DP-B", 8.2, "planned"),
        ("CNV-106", "ATV (2.4 t)", 2.4, "DP-B", "U-21", 2.2, "held"),
        ("CNV-107", "Kraz (12.0 t)", 12.0, "DP-A", "U-56", 11.1, "planned"),
        ("CNV-108", "Tata-LS (9.0 t)", 9.0, "DP-B", "U-34", 6.8, "in_transit"),
    ]
    corr_by_pair = {
        tuple(sorted((c["from_node"], c["to_node"]))): c for c in b.corridors
    }
    for i, (code, vtype, cap, o, d, load, status) in enumerate(fleet):
        pair = tuple(sorted((o, d)))
        c = corr_by_pair.get(pair)
        if c is None:
            # fall back to shortest path-less direct distance for UX continuity
            na, nb = idx[o], idx[d]
            dist = haversine_km(na["lat"], na["lon"], nb["lat"], nb["lon"]) * 1.3
        else:
            dist = c["distance_km"]
        fuel = round(dist * (0.24 + 0.05 * cap), 1)
        risk = round(0.18 + 0.5 * (c["closure_risk"] if c else 0.3), 2)
        manifest_items = rng.choice(len(ITEMS), size=4, replace=False)
        manifest = [
            dict(item_code=ITEMS[k]["code"],
                 qty=round(load * float(rng.uniform(0.12, 0.36)), 1))
            for k in manifest_items
        ]
        b.convoys.append(
            dict(
                code=code, vehicle_type=vtype, capacity_t=cap, status=status,
                origin_node=o, dest_node=d, load_t=load,
                distance_km=round(dist, 1), fuel_l=fuel,
                depart_ts="", eta_ts="", risk_score=risk,
                plan_id="BASELINE", kind="planned", manifest=manifest,
            )
        )

    # ---- sensor gateways --------------------------------------------------- #
    for n in b.nodes:
        b.sensors.append(
            dict(
                node_code=n["code"], gateway=f"gw-{n['code'].lower()}",
                protocol="MQTT",
                battery_pct=round(float(rng.uniform(41, 99)), 1),
                signal_dbm=round(float(rng.uniform(-96, -54)), 0),
                online=bool(rng.random() > 0.06),
            )
        )

    # ---- seed alerts ------------------------------------------------------- #
    for s in [x for x in b.sensors if not x["online"]][:3]:
        b.alerts.append(
            dict(severity="warning", type="sensor_offline",
                 node_code=s["node_code"],
                 message=f"Sensor gateway {s['gateway']} offline - telemetry stale",
                 action="Assign technician")
        )
    for s in [x for x in b.sensors if x["online"] and x["battery_pct"] < 52.0][:3]:
        b.alerts.append(
            dict(severity="info", type="sensor_battery",
                 node_code=s["node_code"],
                 message=(f"Gateway {s['gateway']} battery at "
                          f"{s['battery_pct']:.0f}% - replace cell on next rotation"),
                 action="Schedule replacement")
        )
    # Two tiers rather than one: stock below the reorder trigger is actionable,
    # stock slipping under 62 % of min level is already an emergency. A single
    # threshold makes the alert board either all-red or empty.
    for inv in b.inventory:
        if inv["on_hand"] >= inv["min_level"] * 0.85:
            continue
        item = next(x for x in b.items if x["code"] == inv["item_code"])
        critical = inv["on_hand"] < inv["min_level"] * 0.62
        b.alerts.append(
            dict(
                severity="critical" if critical and item["is_critical"]
                else ("warning" if item["is_critical"] else "info"),
                type="stockout_risk", node_code=inv["node_code"],
                message=(f"{inv['node_code']} {item['name']} below critical "
                         f"reorder threshold ({inv['on_hand']:.0f} / "
                         f"{inv['min_level']:.0f} kg)"
                         if critical else
                         f"{inv['node_code']} {item['name']} approaching reorder "
                         f"({inv['on_hand']:.0f} of {inv['min_level']:.0f} kg)"),
                action="Raise resupply" if critical else "Monitor",
            )
        )
    b.alerts.append(
        dict(severity="warning", type="corridor_risk", node_code="U-21",
             message="Corridor C-12 (U-63 - U-21, SH) closure risk elevated to 0.44 "
                     "under forecast rainfall; U-21 has no second all-weather axis",
             action="Run scenario")
    )
    order = {"critical": 0, "warning": 1, "info": 2}
    b.alerts.sort(key=lambda a: order.get(a["severity"], 3))

    return b
