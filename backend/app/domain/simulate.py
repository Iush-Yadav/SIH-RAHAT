"""MISSION SIM - the counterfactual decision engine.

Pipeline for any scenario:

    scenario params
        -> re-forecast every critical item at every forward unit   (batched GBM)
        -> detect units the disruption will strand                (graph reachability)
        -> pre-stage surplus *before* the closure                 (reallocation on the open graph)
        -> re-solve the network                                   (Clarke-Wright VRP)
        -> project stockout dates with and without the plan       (deterministic drawdown)
        -> emit metrics delta + a one-paragraph briefing note

The engine deliberately reports three states side by side - pre-disruption
reference, unreacted status quo, and the RAHAT plan - so the value of reacting
is measured rather than asserted.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from .. import repository as repo
from ..config import settings
from ..domain.optimize import (
    TheatreGraph,
    consolidate,
    reallocate,
    replay_plan,
    solve_routes,
)
from ..services import forecast_service as fs

TODAY = date(2026, 10, 3)
DEFAULT_HORIZON = 14


# --------------------------------------------------------------------------- #
# Scenario catalogue
# --------------------------------------------------------------------------- #
@dataclass
class Scenario:
    key: str
    label: str
    description: str
    icon: str
    severity: str  # low | medium | high
    params: dict = field(default_factory=dict)
    talking_point: str = ""


SCENARIOS: list[Scenario] = [
    Scenario(
        key="baseline",
        label="No disruption",
        description="Reference state: monsoon receding, all corridors open, "
                    "nominal operational tempo, fleet at full strength.",
        icon="sunny", severity="low",
        params={},
        talking_point="The calm state the dashboard shows before anything breaks.",
    ),
    Scenario(
        key="cloudburst",
        label="Cloudburst & flash flood",
        description="Cloudburst over the northern ridge washes out the SH axis into "
                    "the forward sector. Both remaining approaches degrade; the "
                    "fair-weather track closes. Rainfall triples for the window.",
        icon="rain", severity="high",
        params=dict(close=["C-12", "C-15"], adverse=True, rainfall_mult=3.0,
                    risk_boost=0.18, tempo="high"),
        talking_point="U-21 loses every all-weather axis at once - the only survivable "
                      "answer is to move stores before the road goes.",
    ),
    Scenario(
        key="tempo_surge",
        label="Forward tempo surge",
        description="Field exercise upgraded to full operational tempo for the next "
                    "fortnight. Ammunition and POL draw rises sharply across all "
                    "forward units while corridors stay open.",
        icon="bolt", severity="medium",
        params=dict(tempo="high", ops=1, demand_mult=1.18, rainfall_mult=1.2),
        talking_point="Pure demand shock - no road is closed, so the whole burden falls "
                      "on forecasting and load consolidation.",
    ),
    Scenario(
        key="bridge_washout",
        label="Bridge washout on the rear axis",
        description="The bridge carrying the FORWARD DUMP BRAVO - UNIT OSCAR KUC link "
                    "is washed out. Two forward units lose their only direct feed from "
                    "the eastern dump and every flow has to divert.",
        icon="bridge", severity="high",
        params=dict(close=["C-14"], adverse=False, risk_boost=0.14,
                    rainfall_mult=2.0),
        talking_point="One structure failing far behind the line cuts two forward units "
                      "at once - classic single point of failure, and RAHAT re-routes "
                      "them through the CHARLIE axis instead of dropping the freight.",
    ),
    Scenario(
        key="convoy_attrition",
        label="Convoy attrition / fleet shortfall",
        description="Forty per cent of the transport fleet is unavailable - vehicles "
                    "held for maintenance and two columns interdicted. Same demand, "
                    "half the lift.",
        icon="truck", severity="high",
        params=dict(capacity_mult=0.6, demand_mult=1.05, tempo="high"),
        talking_point="Capacity, not distance, becomes the binding constraint - this is "
                      "where load consolidation earns its keep.",
    ),
    Scenario(
        key="resupply_delay",
        label="Resupply convoy delayed 7 days",
        description="The next inward induction from the railhead slips by a week. "
                    "In-transit receipts arrive late while consumption continues.",
        icon="clock", severity="medium",
        params=dict(delay_days=7, rainfall_mult=1.5),
        talking_point="A timing shock only - the engine has to move stock sideways "
                      "between units rather than wait for the rear.",
    ),
    Scenario(
        key="winter_pass",
        label="Early winter pass closure",
        description="Premature snowfall on the high approaches. Fair-weather tracks close, "
                    "gradients worsen, heating demand climbs and every remaining leg runs "
                    "slower.",
        icon="snow", severity="high",
        params=dict(adverse=True, temp_offset=-9.0, rainfall_mult=1.4,
                    risk_boost=0.12, demand_mult=1.06),
        talking_point="Weather shifts demand and supply at the same time - diesel and LPG "
                      "rise while the network shrinks.",
    ),
]

SCENARIO_BY_KEY = {s.key: s for s in SCENARIOS}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _vehicle_fleet(w: repo.World, capacity_mult: float = 1.0) -> list[dict]:
    fleet = [
        {"code": c["code"], "vehicle_type": c["vehicle_type"],
         "capacity_t": c["capacity_t"]}
        for c in w.convoys
    ]
    if not fleet:
        fleet = [
            {"code": "CNV-1", "vehicle_type": "Tata-LS", "capacity_t": 9.0},
            {"code": "CNV-2", "vehicle_type": "Kraz", "capacity_t": 12.0},
        ]
    keep = max(1, int(math.ceil(len(fleet) * max(0.2, min(1.0, capacity_mult)))))
    return fleet[:keep]


def _critical_items(w: repo.World) -> list[dict]:
    return [i for i in w.items if i["is_critical"]]


def _units(w: repo.World) -> list[dict]:
    return [n for n in w.nodes if n["type"] == "unit"]


def _depots(w: repo.World) -> list[dict]:
    return [n for n in w.nodes if n["type"] in ("depot", "railhead", "airfield")]


def _on_hand(w: repo.World, node_id: int, item_id: int) -> dict | None:
    for inv in w.inventory:
        if inv["node_id"] == node_id and inv["item_id"] == item_id:
            return inv
    return None


def _stockout_day(stock_kg: float, rate_kg_day: float, recv_kg_day: float,
                  horizon: int) -> float:
    """First day on-hand + receipts fail to cover consumption."""
    net = rate_kg_day - recv_kg_day
    if net <= 1e-9:
        return math.inf
    return stock_kg / net


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def evaluate(
    scenario_key: str,
    *,
    overrides: dict | None = None,
    horizon: int = DEFAULT_HORIZON,
    username: str = "system",
) -> dict:
    t0 = time.perf_counter()
    preset = SCENARIO_BY_KEY.get(scenario_key)
    if preset is None and scenario_key != "custom":
        raise KeyError(f"unknown scenario {scenario_key}")
    params = dict(preset.params) if preset else {}
    if scenario_key == "custom":
        params = dict(overrides or {})
        label = (overrides or {}).get("label", "Custom scenario")
        description = (overrides or {}).get("description", "Operator-defined scenario.")
        icon, severity = "sliders", "medium"
        talking = "You defined this one - the engine treats it identically to a preset."
    else:
        if overrides:
            params.update({k: v for k, v in overrides.items() if k not in ("label", "description")})
        label, description = preset.label, preset.description
        icon, severity, talking = preset.icon, preset.severity, preset.talking_point

    horizon = max(3, min(horizon, 45))
    w = repo.load_world()

    close_codes = set(params.get("close", []))
    adverse = bool(params.get("adverse", False))
    risk_boost = float(params.get("risk_boost", 0.0))
    tempo = params.get("tempo", "nominal")
    ops = int(params.get("ops", 0))
    rainfall_mult = float(params.get("rainfall_mult", 1.0))
    temp_offset = float(params.get("temp_offset", 0.0))
    demand_mult = float(params.get("demand_mult", 1.0))
    capacity_mult = float(params.get("capacity_mult", 1.0))
    delay_days = int(params.get("delay_days", 0))

    closed_ids = {c["id"] for c in w.corridors if c["code"] in close_codes}

    def make_graph(*, scenario: bool) -> TheatreGraph:
        corridors = [dict(c) for c in w.corridors]
        if scenario and risk_boost:
            for c in corridors:
                c["closure_risk"] = min(1.0, c["closure_risk"] + risk_boost)
        return TheatreGraph(
            corridors, w.node_by_code,
            closed_corridors=closed_ids if scenario else set(),
            adverse_weather=adverse if scenario else False,
        )

    g_open = make_graph(scenario=False)
    g_scn = make_graph(scenario=True)

    units = _units(w)
    depots = _depots(w)
    crit = _critical_items(w)
    fleet = _vehicle_fleet(w, capacity_mult)
    depot_codes = [d["code"] for d in depots]

    # ---- 1. re-forecast every critical series at every forward unit -------- #
    queries = [(u["code"], it["code"]) for u in units for it in crit]
    fc = fs.forecast_batch(
        queries, horizon=horizon, tempo_future=tempo, ops_future=ops,
        rainfall_mult=rainfall_mult, temp_offset=temp_offset,
        demand_mult=demand_mult,
    )

    requirements: dict[str, dict[str, float]] = {}   # unit -> item -> kg over horizon
    rates: dict[str, dict[str, float]] = {}          # unit -> item -> kg/day
    for u in units:
        requirements[u["code"]] = {}
        rates[u["code"]] = {}
        for it in crit:
            r = fc.get(f"{u['code']}|{it['code']}")
            if not r:
                continue
            requirements[u["code"]][it["code"]] = r["total"]
            rates[u["code"]][it["code"]] = r["mean_daily"]

    demand_t = {u: sum(v.values()) / 1000.0 for u, v in requirements.items()}

    # ---- 2. reachability & stock on hand ---------------------------------- #
    node_by_code = w.node_by_code
    stranded: list[str] = []
    for u in units:
        reachable = any(
            not math.isinf(g_scn.path(d["code"], u["code"],
                                       max(v["capacity_t"] for v in fleet))[1])
            for d in depots
        )
        if not reachable:
            stranded.append(u["code"])

    # ---- 3. pre-stage surplus BEFORE the closure -------------------------- #
    # ``cap_kg`` is the *gap*: what a stranded unit would be short over the
    # horizon, not its gross requirement. Capping on the gap is what stops the
    # pre-stage from rebuilding an entire depot inside a forward unit - the
    # first cut shipped 191 t into a unit that only needed 108 t.
    balances: dict[str, dict[str, float]] = {}
    gap_kg: dict[str, float] = {}
    for n in w.nodes:
        for it in crit:
            inv = _on_hand(w, n["id"], it["id"])
            if inv is None:
                continue
            # Depots may dip deeper than forward units: they hold the buffer.
            floor = inv["min_level"] * (0.5 if n["type"] != "unit" else 1.0)
            balances.setdefault(n["code"], {})[it["code"]] = round(
                inv["on_hand"] - floor, 1)

    for code in stranded:
        node = next(n for n in w.nodes if n["code"] == code)
        req = sum(requirements.get(code, {}).values())
        held = 0.0
        for it in crit:
            inv = _on_hand(w, node["id"], it["id"])
            if inv:
                held += inv["on_hand"] + inv["in_transit"]
        gap_kg[code] = max(0.0, req - held)

    prestage: list[dict] = []
    if stranded and gap_kg:
        # Must run on the OPEN graph: the whole point is acting before closure.
        deficits = {c: kg / 1000.0 for c, kg in gap_kg.items()}
        prestage = reallocate(
            g_open, balances, deficits, fleet, max_ship_t=6.0, give_up_frac=0.55
        )
        prestage = [m for m in prestage if m["to"] in stranded]

    prestage_by_unit: dict[str, float] = {}
    prestage_item_kg: dict[str, dict[str, float]] = {}
    for m in prestage:
        prestage_by_unit[m["to"]] = prestage_by_unit.get(m["to"], 0.0) + m["qty_t"]
        per_item = prestage_item_kg.setdefault(m["to"], {})
        per_item[m["item"]] = per_item.get(m["item"], 0.0) + m["qty_t"] * 1000.0

    # ---- 4. re-solve the network ------------------------------------------ #
    # Three arms, and the middle one is the important one:
    #
    #   pre_disruption - the standing convoy order as the formation actually
    #                    wrote it (nearest dump, one shuttle per unit), solved
    #                    against the healthy network.
    #   no_reaction    - that same order executed *after* the cut. Nothing is
    #                    re-planned, so any route whose legs are now unusable
    #                    simply does not run and its freight does not arrive.
    #   rahat          - the order re-solved on the damaged network, optimised.
    #
    # The algorithmic ablation (naive vs optimised on one network) lives on the
    # Planner page; here the question is purely "anticipate and re-plan, or not".
    standing_plan, optimised_healthy = solve_routes(
        g_open, depot_codes, demand_t, fleet, required_by_days=float(horizon)
    )
    ideal_plan = standing_plan
    base_plan = replay_plan(standing_plan, g_scn)
    _, rahat_plan = solve_routes(
        g_scn, depot_codes, demand_t, fleet, required_by_days=float(horizon)
    )

    # ---- 5. per-unit, per-item receipts ------------------------------------ #
    def receipts(plan) -> dict[str, dict[str, float]]:
        """Distribute each route's payload to its visits, then across items."""
        out: dict[str, dict[str, float]] = {u["code"]: {} for u in units}
        for r in plan.routes:
            if not r.visits:
                continue
            share_units = [v for v in r.visits if v in requirements]
            if not share_units:
                continue
            unit_req = {v: sum(requirements.get(v, {}).values()) for v in share_units}
            tot_req = sum(unit_req.values()) or 1.0
            # ``demand_t`` is the tour's total payload across every rotation;
            # ``load_t`` is only the mean payload of a single rotation.
            for v in share_units:
                tonnage = r.demand_t * (unit_req[v] / tot_req)
                item_req = requirements.get(v, {})
                item_tot = sum(item_req.values()) or 1.0
                for code, kg in item_req.items():
                    out[v][code] = out[v].get(code, 0.0) + tonnage * 1000.0 * (kg / item_tot)
        return out

    rcpt_base = receipts(base_plan)
    rcpt_rahat = receipts(rahat_plan)

    # In-transit receipts (delay scenarios push them beyond the window).
    in_transit: dict[str, dict[str, float]] = {u["code"]: {} for u in units}
    for u in units:
        for it in crit:
            inv = _on_hand(w, u["id"], it["id"])
            if inv:
                in_transit[u["code"]][it["code"]] = (
                    0.0 if delay_days >= horizon else inv["in_transit"]
                )

    def project(rcpt, *, extra_prestage: dict[str, dict[str, float]] | None = None) -> dict:
        rows, at_risk, stockouts, filled_req, total_req = [], [], [], 0.0, 0.0
        for u in units:
            uc = u["code"]
            unit_rows = []
            worst = math.inf
            for it in crit:
                key = it["code"]
                req = requirements.get(uc, {}).get(key, 0.0)
                if req <= 0:
                    continue
                inv = _on_hand(w, u["id"], it["id"])
                stock = (inv["on_hand"] if inv else 0.0)
                stock += in_transit[uc].get(key, 0.0)
                stock += (extra_prestage or {}).get(uc, {}).get(key, 0.0)
                recv = rcpt.get(uc, {}).get(key, 0.0) / horizon
                rate = rates.get(uc, {}).get(key, 0.0)
                supply = stock + rcpt.get(uc, {}).get(key, 0.0)
                fill = min(1.0, supply / req) if req > 0 else 1.0
                dos = _stockout_day(stock, rate, recv, horizon)
                worst = min(worst, dos)
                filled_req += req * fill
                total_req += req
                if dos < horizon:
                    stockouts.append({
                        "node": uc, "item": key, "item_name": it["name"],
                        "day": round(dos, 1), "dos_days": round(dos, 1),
                        "req_kg": round(req, 0), "supply_kg": round(supply, 0),
                        "fill_pct": round(fill * 100, 1),
                    })
                unit_rows.append({
                    "item": key, "fill_pct": round(fill * 100, 1),
                    "dos_days": round(dos, 1) if math.isfinite(dos) else 999,
                })
            rows.append({"node": uc, "worst_dos": round(worst, 1) if math.isfinite(worst) else 999,
                         "items": unit_rows})
            if worst < horizon:
                at_risk.append(uc)
        return {
            "fill_rate_pct": round(filled_req / total_req * 100.0, 1) if total_req else 0.0,
            "units_at_risk": sorted(set(at_risk)),
            "stockouts": sorted(stockouts, key=lambda r: r["day"]),
            "nodes": rows,
        }

    before = project(rcpt_base)
    after = project(rcpt_rahat, extra_prestage=prestage_item_kg)

    # ---- 6. consolidation quality of the final plan ------------------------ #
    lines = []
    for u in units:
        for it in crit:
            kg = rcpt_rahat.get(u["code"], {}).get(it["code"], 0.0)
            if kg > 1:
                lines.append({"code": it["code"], "name": it["name"],
                              "category": it["category"], "qty_kg": round(kg, 1),
                              "volume_l": round(kg / 1000.0 * 1000 * 0.62, 1)})
    packing = consolidate(lines, fleet) if lines else None

    # ---- 7. metrics -------------------------------------------------------- #
    def plan_metrics(p) -> dict:
        delivered = p.total_tonnage_t
        return {
            "cost_inr": p.total_cost_inr,
            "distance_km": p.total_distance_km,
            "fuel_l": p.total_fuel_l,
            "hours": round(p.total_hours, 1),
            "routes": len(p.routes),
            "trips": p.total_trips,
            "tonnage_t": p.total_tonnage_t,
            "delivered_t": delivered,
            "cost_per_tonne_inr": (round(p.total_cost_inr / delivered)
                                   if delivered else None),
            "utilisation_pct": p.utilisation_pct,
            "worst_risk": p.worst_risk,
            "unserved": p.unserved,
            "blocked_routes": p.blocked_routes,
            "solve_ms": p.solve_ms,
            "solver": p.solver,
        }

    m_ideal, m_base, m_rahat = plan_metrics(ideal_plan), plan_metrics(base_plan), plan_metrics(rahat_plan)

    cost_delta = int(m_rahat["cost_inr"] - m_base["cost_inr"])
    dist_delta = round(m_rahat["distance_km"] - m_base["distance_km"], 1)
    fill_delta = round(after["fill_rate_pct"] - before["fill_rate_pct"], 1)

    stranded_block = []
    for code in stranded:
        req_kg = sum(requirements.get(code, {}).values())
        stocked = 0.0
        inv_by_node = {n["code"]: n for n in w.nodes}
        for it in crit:
            inv = _on_hand(w, inv_by_node[code]["id"], it["id"])
            if inv:
                stocked += inv["on_hand"]
        demand_kg = sum(rates.get(code, {}).values()) * horizon
        stranded_block.append({
            "node": code,
            "name": inv_by_node[code]["name"],
            "prestaged_t": round(prestage_by_unit.get(code, 0.0), 1),
            "gap_t": round(gap_kg.get(code, 0.0) / 1000.0, 1),
            "requirement_t": round(req_kg / 1000.0, 1),
            "on_hand_t": round(stocked / 1000.0, 1),
            "horizon_demand_t": round(demand_kg / 1000.0, 1),
            "days_left": round(stocked / max(sum(rates.get(code, {}).values()), 1e-6), 1),
            "action": "Pre-stage now - every remaining axis closes in this scenario.",
        })

    # ---- 8. briefing note --------------------------------------------------- #
    note = _briefing_note(
        label, horizon, before, after, m_base, m_rahat, prestage, stranded_block,
        cost_delta, fill_delta,
    )

    alerts = _scenario_alerts(stranded_block, before, after)

    return {
        "scenario": scenario_key,
        "label": label,
        "description": description,
        "icon": icon,
        "severity": severity,
        "talking_point": talking,
        "params": params,
        "horizon": horizon,
        "generated_at": repo.now_iso(),
        "solve_ms": round((time.perf_counter() - t0) * 1000, 1),
        "stranded": stranded_block,
        "prestage": prestage,
        "prestage_t": round(sum(m["qty_t"] for m in prestage), 1),
        "before": before,
        "after": after,
        "plans": {
            "pre_disruption": m_ideal,
            "no_reaction": m_base,
            "rahat": m_rahat,
        },
        "delta": {
            "cost_inr": cost_delta,
            "distance_km": dist_delta,
            "fill_rate_pct": fill_delta,
            "delivered_t": round(m_rahat["tonnage_t"] - m_base["tonnage_t"], 1),
            "cost_per_tonne_inr": (
                (m_rahat["cost_per_tonne_inr"] or 0) - (m_base["cost_per_tonne_inr"] or 0)
            ),
            "units_at_risk_before": len(before["units_at_risk"]),
            "units_at_risk_after": len(after["units_at_risk"]),
            "stockouts_before": len(before["stockouts"]),
            "stockouts_after": len(after["stockouts"]),
            "blocked_routes": len(m_base["blocked_routes"]),
        },
        "packing": packing,
        "briefing_note": note,
        "alerts": alerts,
        "requirements": {k: {ik: round(iv, 0) for ik, iv in v.items()}
                         for k, v in requirements.items()},
    }


# --------------------------------------------------------------------------- #
# Narrative
# --------------------------------------------------------------------------- #
def _briefing_note(label, horizon, before, after, m_base, m_rahat, prestage,
                   stranded, cost_delta, fill_delta) -> str:
    lines = [f"{label.upper()} - {horizon}-DAY LOGISTICS ASSESSMENT", ""]

    if stranded:
        lines.append("IMMEDIATE ACTION REQUIRED")
        for s in stranded:
            lines.append(
                f"  {s['node']} ({s['name']}) will lose every supply axis. "
                f"Days of stock on hand: {s['days_left']}. Pre-stage "
                f"{s['gap_t']:.1f} t before closure to cover the {horizon}-day gap "
                f"({s['horizon_demand_t']:.1f} t required, {s['on_hand_t']:.1f} t "
                f"held). RAHAT has sourced {s['prestaged_t']:.1f} t of surplus "
                f"from formations that can spare it."
            )
        lines.append("")

    lines.append("ASSESSMENT")
    lines.append(
        f"  Without intervention, {len(before['units_at_risk'])} of "
        f"{len(before['nodes'])} forward units fall below minimum service level "
        f"within {horizon} days and {len(before['stockouts'])} critical "
        f"item-unit combinations stock out. Achievable fill rate: "
        f"{before['fill_rate_pct']}%."
    )
    lines.append(
        f"  With the RAHAT plan executed, units at risk fall to "
        f"{len(after['units_at_risk'])} and critical stockouts to "
        f"{len(after['stockouts'])}. Fill rate improves "
        f"{fill_delta:+.1f} points to {after['fill_rate_pct']}%."
    )
    lines.append("")

    lines.append("RECOMMENDED PRE-CLOSURE MOVEMENT")
    if prestage:
        # Group by axis: a raw movement list runs to pages once every donor is
        # considered, and a briefing note has to be readable at a desk.
        shown = sorted(prestage, key=lambda m: -m["qty_t"])[:6]
        for m in shown:
            lines.append(
                f"  {m['from']} -> {m['to']}: {m['qty_t']} t of {m['item']} "
                f"via {m['corridor']}, {m['distance_km']} km, {m['eta_hours']} h, "
                f"Rs {m['cost_inr']:,.0f}."
            )
        if len(prestage) > len(shown):
            rest = prestage[len(shown):]
            lines.append(
                f"  ... and {len(rest)} further moves totalling "
                f"{sum(r['qty_t'] for r in rest):.1f} t, "
                f"Rs {sum(r['cost_inr'] for r in rest):,.0f} (full list in the "
                f"movement table)."
            )
        lines.append(
            f"  Total pre-stage {sum(m['qty_t'] for m in prestage):.1f} t over "
            f"{len({(m['from'], m['to']) for m in prestage})} axes, "
            f"Rs {sum(m['cost_inr'] for m in prestage):,.0f}."
        )
    else:
        lines.append("  No pre-closure movement required; network remains connected.")
    lines.append("")

    lines.append("MOVEMENT PLAN: NO REACTION vs RAHAT")
    lines.append(
        f"  Freight delivered {m_base['tonnage_t']} t -> {m_rahat['tonnage_t']} t "
        f"({m_rahat['tonnage_t'] - m_base['tonnage_t']:+.1f} t)"
        + (f"; {len(m_base['blocked_routes'])} route(s) in the standing plan cannot run"
           if m_base["blocked_routes"] else "")
    )
    lines.append(f"  Distance        {m_base['distance_km']} km -> {m_rahat['distance_km']} km ({m_rahat['distance_km'] - m_base['distance_km']:+.0f} km)")
    lines.append(f"  Cost            Rs {m_base['cost_inr']:,.0f} -> Rs {m_rahat['cost_inr']:,.0f} ({cost_delta:+,.0f})")
    cpt_b, cpt_r = m_base.get("cost_per_tonne_inr"), m_rahat.get("cost_per_tonne_inr")
    if cpt_b and cpt_r:
        lines.append(f"  Unit cost       Rs {cpt_b:,.0f}/t -> Rs {cpt_r:,.0f}/t ({cpt_r - cpt_b:+,.0f})")
    lines.append(f"  Lift utilisation {m_base['utilisation_pct']}% -> {m_rahat['utilisation_pct']}%")
    lines.append(f"  Crew hours      {m_base['hours']} h -> {m_rahat['hours']} h ({m_rahat['hours'] - m_base['hours']:+.0f} h)")
    lines.append(f"  Worst leg risk  {m_base['worst_risk']} -> {m_rahat['worst_risk']}")
    lines.append("")
    lines.append(
        "Decision: " + ("Execute pre-stage movement immediately, then run the "
                        "re-solved convoy plan." if stranded or fill_delta >= 0
                        else "Run the re-solved convoy plan; pre-stage not required.")
    )
    return "\n".join(lines)


def _scenario_alerts(stranded, before, after) -> list[dict]:
    out: list[dict] = []
    for s in stranded:
        out.append(dict(severity="critical", type="node_isolated", node=s["node"],
                        message=(f"{s['node']} isolated in this scenario - "
                                 f"{s['days_left']} days of stock remaining"),
                        action="Pre-stage"))
    for so in before["stockouts"][:6]:
        out.append(dict(severity="warning", type="forecast_stockout", node=so["node"],
                        message=(f"{so['node']} {so['item']} projects stockout on "
                                 f"day {so['day']} without intervention"),
                        action="Re-solve"))
    return out
