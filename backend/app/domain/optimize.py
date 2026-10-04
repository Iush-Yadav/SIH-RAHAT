"""Routing, consolidation and reallocation optimisers.

Implemented from first principles on plain numpy/stdlib so the platform has no
compiled solver dependency - a hard constraint for an air-gapped forward node.

  * ``TheatreGraph``    Dijkstra over the corridor network with hard capacity
                        and all-weather filters plus a risk-adjusted edge cost.
  * ``clarke_wright``   classical savings algorithm for the multi-depot VRP with
                        Or-opt inter-route improvement.
  * ``greedy_nearest``  deliberately naive baseline - one shuttle per unit - so
                        the optimiser's benefit is *measured*, not asserted.
  * ``consolidate``     first-fit-decreasing load planning with weight+volume.
  * ``reallocate``      greedy min-cost transportation for surplus -> deficit.

Two modelling decisions that the first cut got wrong and that change every
number downstream:

**Multi-trip.** A forward unit draws on the order of 12 t/day of critical stores
while the heaviest vehicle available carries 12 t. A single-visit VRP therefore
cannot represent the problem at all - it rejects every demand as infeasible.
Each route is a *tour* (depot -> units -> depot) that a vehicle repeats
``ceil(tour_demand / capacity)`` times inside the horizon. Consolidation then
helps twice: fewer return legs, and ``ceil(sum(d)/c) <= sum(ceil(d_i/c))``
because vehicles leave full instead of part-loaded.

**Cross-depot savings.** The textbook form fixes each unit to a depot before
savings are computed. On this theatre (five depots, six forward units) that
produces clusters of one or two, so nothing ever merges and the "optimised"
plan came out byte-identical to the naive baseline. The depot is therefore a
*decision variable*: every candidate merge is evaluated at every depot and the
cheapest wins.
"""

from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field

from .geo import haversine_km

# --------------------------------------------------------------------------- #
# Cost model (documented constants - every rupee on a slide traces back here)
# --------------------------------------------------------------------------- #
ROAD_SPEED_KMPH = {"NH": 42.0, "SH": 34.0, "KUC": 24.0, "ALP": 15.0}
ROAD_HANDLING_H = {"NH": 0.20, "SH": 0.35, "KUC": 0.55, "ALP": 0.85}
VEHICLE_BASE_INR_PER_KM = 58.0
VEHICLE_TONNE_INR_PER_KM = 13.0
FUEL_L_PER_KM_BASE = 0.28
FUEL_L_PER_KM_PER_TONNE = 0.055
EMPTY_RETURN_FUEL_FACTOR = 0.85   # an empty truck still burns 85 % of base rate
CREW_INR_PER_HOUR = 95.0          # driver + helper, loaded and empty alike
ADVERSE_HOURS_FACTOR = 1.35       # snow/landslide: same road, more time
RISK_COST_WEIGHT = 0.60           # converts closure_risk 0..1 into an edge premium
RISK_PRICE_WEIGHT = 0.45          # converts route risk into a cost premium
MAX_TOUR_STOPS = 4
HOURS_PER_DAY = 24.0


@dataclass
class Leg:
    from_node: str
    to_node: str
    corridor_id: int
    corridor_code: str
    distance_km: float
    road_class: str
    hours: float
    risk: float


@dataclass
class Route:
    vehicle: str
    vehicle_type: str
    capacity_t: float
    depot: str
    visits: list[str]
    demand_t: float          # tonnes this tour must move over the horizon
    trips: int               # rotations the vehicle makes
    load_t: float            # mean payload per rotation
    tour_km: float           # distance of one rotation
    distance_km: float       # tour_km * trips
    hours: float
    fuel_l: float
    cost_inr: float
    risk: float
    legs: list[Leg] = field(default_factory=list)
    eta_hours: float = 0.0
    slack_days: float = 0.0
    breached: bool = False

    @property
    def n_visits(self) -> int:
        return len(self.visits)

    @property
    def utilisation_pct(self) -> float:
        return round(self.load_t / self.capacity_t * 100.0, 1) if self.capacity_t else 0.0


@dataclass
class Plan:
    solver: str
    routes: list[Route]
    total_distance_km: float
    total_hours: float
    total_fuel_l: float
    total_cost_inr: float
    total_tonnage_t: float
    total_trips: int
    worst_risk: float
    served: list[str]
    unserved: list[str]
    solve_ms: float
    blocked_routes: list[dict] = field(default_factory=list)

    @property
    def utilisation_pct(self) -> float:
        cap = sum(r.capacity_t * r.trips for r in self.routes)
        return round(self.total_tonnage_t / cap * 100.0, 1) if cap else 0.0

    @property
    def mean_risk(self) -> float:
        if not self.routes:
            return 0.0
        return round(sum(r.risk for r in self.routes) / len(self.routes), 2)


class TheatreGraph:
    """Undirected corridor network with condition-aware pathing."""

    def __init__(
        self,
        corridors: list[dict],
        nodes: dict[str, dict],
        *,
        closed_corridors: set[int] | None = None,
        adverse_weather: bool = False,
        risk_weight: float = RISK_COST_WEIGHT,
    ) -> None:
        self.nodes = nodes
        self.closed = closed_corridors or set()
        self.adverse = adverse_weather
        self.risk_weight = risk_weight
        self.adj: dict[str, list[tuple[str, dict]]] = {c: [] for c in nodes}
        self.corridor_by_id: dict[int, dict] = {}
        for c in corridors:
            self.corridor_by_id[c["id"]] = c
            a, b = c["from_node"], c["to_node"]
            if a not in self.adj or b not in self.adj:
                continue
            self.adj[a].append((b, c))
            self.adj[b].append((a, c))

    def usable(self, c: dict, vehicle_t: float) -> bool:
        if c["id"] in self.closed:
            return False
        if not c["all_weather"] and self.adverse:
            return False
        if vehicle_t and c["capacity_t"] and vehicle_t > c["capacity_t"]:
            return False
        return True

    def path(self, src: str, dst: str, vehicle_t: float = 0.0) -> tuple[list[Leg], float]:
        """Least risk-adjusted distance from src to dst, or ([], inf)."""
        if src == dst:
            return [], 0.0
        dist: dict[str, float] = {src: 0.0}
        prev: dict[str, tuple[str, dict]] = {}
        pq: list[tuple[float, str]] = [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == dst:
                break
            if d > dist.get(u, math.inf) + 1e-9:
                continue
            for v, c in self.adj.get(u, []):
                if not self.usable(c, vehicle_t):
                    continue
                w = c["distance_km"] * (1.0 + self.risk_weight * c["closure_risk"])
                nd = d + w
                if nd < dist.get(v, math.inf) - 1e-9:
                    dist[v] = nd
                    prev[v] = (u, c)
                    heapq.heappush(pq, (nd, v))
        if dst not in prev:
            return [], math.inf

        legs: list[Leg] = []
        cur = dst
        weather = ADVERSE_HOURS_FACTOR if self.adverse else 1.0
        while cur != src:
            u, c = prev[cur]
            speed = ROAD_SPEED_KMPH.get(c["road_class"], 25.0)
            legs.append(Leg(
                from_node=u, to_node=cur, corridor_id=c["id"],
                corridor_code=c["code"], distance_km=c["distance_km"],
                road_class=c["road_class"],
                hours=(c["distance_km"] / speed
                       + ROAD_HANDLING_H.get(c["road_class"], 0.5)) * weather,
                risk=c["closure_risk"],
            ))
            cur = u
        legs.reverse()
        return legs, dist.get(dst, math.inf)

    @staticmethod
    def edge_cost(legs: list[Leg]) -> float:
        """Pure geographic distance - what a naive planner minimises."""
        return sum(l.distance_km for l in legs)


# --------------------------------------------------------------------------- #
# Tour / route costing with shuttle rotations
# --------------------------------------------------------------------------- #
def _tour(graph: TheatreGraph, depot: str, seq: list[str],
          vehicle_t: float) -> tuple[list[Leg], float, float] | None:
    """depot -> seq... -> depot. Returns (legs, km, hours) or None."""
    if not seq:
        return None
    legs: list[Leg] = []
    cur = depot
    for n in seq:
        ls, _ = graph.path(cur, n, vehicle_t)
        if not ls:
            return None
        legs.extend(ls)
        cur = n
    ls, _ = graph.path(cur, depot, vehicle_t)
    if not ls:
        return None
    legs.extend(ls)
    return legs, sum(l.distance_km for l in legs), sum(l.hours for l in legs)


def _route_metrics(graph: TheatreGraph, depot: str, seq: list[str],
                   demand_t: float, capacity_t: float) -> dict | None:
    """Full economics of moving ``demand_t`` on tour ``depot -> seq -> depot``."""
    if demand_t <= 1e-9:
        return None
    t = _tour(graph, depot, seq, capacity_t)
    if t is None:
        return None
    legs, tour_km, tour_hours = t
    if tour_km <= 0:
        return None

    trips = max(1, int(math.ceil(demand_t / max(capacity_t, 1e-6))))
    load = demand_t / trips
    risk = max((l.risk for l in legs), default=0.0)
    return_km = legs[-1].distance_km
    laden_km = max(tour_km - return_km, 0.0)

    km = tour_km * trips
    hours = tour_hours * trips
    fuel = trips * (laden_km * (FUEL_L_PER_KM_BASE + FUEL_L_PER_KM_PER_TONNE * load)
                    + return_km * FUEL_L_PER_KM_BASE * EMPTY_RETURN_FUEL_FACTOR)
    cost = trips * (laden_km * (VEHICLE_BASE_INR_PER_KM + VEHICLE_TONNE_INR_PER_KM * load)
                    + return_km * VEHICLE_BASE_INR_PER_KM)
    # Crew time is charged by the hour whether the wheels are turning or not.
    # Pricing it is what stops the solver from "saving" money by choosing the
    # long way round, and it is why the optimiser also minimises elapsed time.
    cost += trips * CREW_INR_PER_HOUR * tour_hours
    cost *= 1.0 + RISK_PRICE_WEIGHT * risk

    return {
        "legs": legs, "tour_km": tour_km, "tour_hours": tour_hours,
        "trips": trips, "load": load, "risk": risk,
        "km": km, "hours": hours, "fuel": fuel, "cost": cost,
    }


def _best_route(graph: TheatreGraph, depots: list[str], seq: list[str],
                demand_t: float, capacity_t: float) -> tuple[float, str, dict] | None:
    """Cheapest (cost, depot, metrics) for a tour over every candidate depot."""
    best: tuple[float, str, dict] | None = None
    for d in depots:
        m = _route_metrics(graph, d, seq, demand_t, capacity_t)
        if m is None:
            continue
        if best is None or m["cost"] < best[0]:
            best = (m["cost"], d, m)
    return best


def _orientations(a: list[str], b: list[str]) -> list[list[str]]:
    """Every distinct way of concatenating two tours.

    The textbook test ``a[-1] == b[0]`` compares *node codes* and, because a
    unit belongs to exactly one route, two disjoint routes never satisfy it -
    which silently yielded zero candidates and made the "optimised" plan
    identical to the naive baseline. In a VRP any join is legal: reversing a
    whole tour is the same tour, so these four cover all eight endpoint pairings
    up to reversal, and ``_route_metrics`` rejects the ones the graph cannot
    actually connect.
    """
    return [
        a + b,
        a + list(reversed(b)),
        list(reversed(a)) + b,
        list(reversed(a)) + list(reversed(b)),
    ]


def _pick_vehicle(graph: TheatreGraph, depot: str, seq: list[str],
                  demand_t: float, vehicles: list[dict]) -> tuple[dict, dict] | None:
    """Cheapest vehicle for a given tour: bigger means fewer rotations, but a
    half-empty 12 t truck costs more per tonne-kilometre than a full 4.5 t one."""
    best: tuple[float, dict, dict] | None = None
    for v in vehicles:
        m = _route_metrics(graph, depot, seq, demand_t, v["capacity_t"])
        if m is None:
            continue
        if best is None or m["cost"] < best[0]:
            best = (m["cost"], v, m)
    if best is None:
        return None
    return best[1], best[2]


def _make_route(v: dict, depot: str, seq: list[str], demand_t: float,
                m: dict, required_by_days: float) -> Route:
    eta = m["tour_hours"]
    total_h = m["hours"]
    return Route(
        vehicle=v["code"], vehicle_type=v["vehicle_type"],
        capacity_t=v["capacity_t"], depot=depot, visits=list(seq),
        demand_t=round(demand_t, 2), trips=m["trips"],
        load_t=round(m["load"], 2), tour_km=round(m["tour_km"], 1),
        distance_km=round(m["km"], 1), hours=round(m["hours"], 1),
        fuel_l=round(m["fuel"], 1), cost_inr=round(m["cost"], 0),
        risk=round(m["risk"], 2), legs=m["legs"],
        eta_hours=round(eta, 1),
        slack_days=round(required_by_days - total_h / HOURS_PER_DAY, 2),
        breached=total_h / HOURS_PER_DAY > required_by_days,
    )


def _pack(solver: str, routes: list[Route], unserved: list[str],
          demands: dict[str, float], solve_ms: float) -> Plan:
    routes = [r for r in routes if r.visits and r.demand_t > 0]
    served = sorted({v for r in routes for v in r.visits})
    leftover = sorted({n for n, q in demands.items() if q > 0} - set(served))
    return Plan(
        solver=solver,
        routes=routes,
        total_distance_km=round(sum(r.distance_km for r in routes), 1),
        total_hours=round(sum(r.hours for r in routes), 1),
        total_fuel_l=round(sum(r.fuel_l for r in routes), 1),
        total_cost_inr=round(sum(r.cost_inr for r in routes), 0),
        total_tonnage_t=round(sum(r.demand_t for r in routes), 1),
        total_trips=sum(r.trips for r in routes),
        worst_risk=round(max((r.risk for r in routes), default=0.0), 2),
        served=served,
        unserved=sorted(set(unserved) | set(leftover)),
        solve_ms=solve_ms,
    )


# --------------------------------------------------------------------------- #
# Baseline: one shuttle per unit, nearest depot, no consolidation
# --------------------------------------------------------------------------- #
def greedy_nearest(
    graph: TheatreGraph,
    depots: list[str],
    demands: dict[str, float],
    vehicles: list[dict],
    required_by_days: float = 7.0,
) -> Plan:
    """Deliberately naive baseline.

    Stands in for the two habits it is meant to be measured against:

    * **nearest dump as the crow flies** - straight-line distance, ignoring road
      class, gradient, load limits and weather. A depot 45 km away over an
      all-weather track beats one 30 km away over a jeep track, and this never
      learns that;
    * **one shuttle per unit, never consolidated** - every forward unit gets its
      own dedicated rotations, so part-rotations are thrown away.

    Vehicle choice is left optimal on purpose: the point of the comparison is
    planning quality, not a rigged fleet.
    """
    t0 = time.perf_counter()
    routes: list[Route] = []
    unserved: list[str] = []
    fleet_cap = max((v["capacity_t"] for v in vehicles), default=6.0)

    for unit, demand in sorted(demands.items()):
        if demand <= 0:
            continue
        un = graph.nodes.get(unit)
        if un is None:
            unserved.append(unit)
            continue
        best_depot, best_km = None, math.inf
        for d in depots:
            dn = graph.nodes.get(d)
            if dn is None:
                continue
            km = haversine_km(dn["lat"], dn["lon"], un["lat"], un["lon"])
            if km < best_km:
                best_depot, best_km = d, km
        # The crow-flies pick must still actually be drivable; if it is not the
        # naive planner falls back to whoever is closest by road rather than
        # declaring the unit unserved.
        blocked = False
        if best_depot is not None:
            legs, _ = graph.path(best_depot, unit, fleet_cap)
            blocked = not legs
        if best_depot is None or blocked:
            best_depot, best_km = None, math.inf
            for d in depots:
                legs, _ = graph.path(d, unit, fleet_cap)
                if not legs:
                    continue
                km = sum(l.distance_km for l in legs)
                if km < best_km:
                    best_depot, best_km = d, km
        if best_depot is None:
            unserved.append(unit)
            continue
        picked = _pick_vehicle(graph, best_depot, [unit], demand, vehicles)
        if picked is None:
            unserved.append(unit)
            continue
        v, m = picked
        routes.append(_make_route(v, best_depot, [unit], demand, m,
                                  required_by_days))

    return _pack("greedy_nearest (crow-flies depot, one shuttle per unit)",
                 routes, unserved, demands,
                 round((time.perf_counter() - t0) * 1000, 2))


# --------------------------------------------------------------------------- #
# Clarke-Wright savings with Or-opt improvement (depot is a decision variable)
# --------------------------------------------------------------------------- #
def clarke_wright(
    graph: TheatreGraph,
    depots: list[str],
    demands: dict[str, float],
    vehicles: list[dict],
    required_by_days: float = 7.0,
) -> Plan:
    t0 = time.perf_counter()
    pending = {n: q for n, q in demands.items() if q > 0}
    if not pending:
        return _pack("clarke_wright_savings+or_opt", [], [], demands,
                     round((time.perf_counter() - t0) * 1000, 2))

    fleet_cap = max((v["capacity_t"] for v in vehicles), default=6.0)

    # --- seed: every unit is its own tour, at its own cheapest depot -------- #
    seqs: dict[str, list[str]] = {}
    loads: dict[str, float] = {}
    depot_of: dict[str, str] = {}
    owner: dict[str, str] = {}
    unserved: list[str] = []

    for n, q in sorted(pending.items()):
        best = _best_route(graph, depots, [n], q, fleet_cap)
        if best is None:
            unserved.append(n)
            continue
        seqs[n] = [n]
        loads[n] = q
        depot_of[n] = best[1]
        owner[n] = n

    def cost_of(key: str) -> float:
        m = _route_metrics(graph, depot_of[key], seqs[key], loads[key], fleet_cap)
        return m["cost"] if m else math.inf

    singleton_cost = {k: cost_of(k) for k in list(seqs)}

    # --- savings over every pair of units, evaluated at every candidate depot -- #
    keys = list(seqs)
    savings: list[tuple[float, str, str]] = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            ua, ub = keys[i], keys[j]
            if len(seqs[ua]) + len(seqs[ub]) > MAX_TOUR_STOPS:
                continue
            load = loads[ua] + loads[ub]
            best: tuple[float, str, list[str]] | None = None
            for cand in _orientations(seqs[ua], seqs[ub]):
                b = _best_route(graph, depots, cand, load, fleet_cap)
                if b is None:
                    continue
                if best is None or b[0] < best[0]:
                    best = (b[0], b[1], cand)
            if best is None:
                continue
            s = singleton_cost[ua] + singleton_cost[ub] - best[0]
            if s > 1e-6:
                savings.append((s, ua, ub))
    savings.sort(key=lambda t: -t[0])

    # --- merge. The savings value only *orders* the queue; each merge is
    # re-evaluated against the tours as they now stand, because routes have
    # changed since the savings table was built. --------------------------- #
    for _s, ua, ub in savings:
        ra, rb = owner.get(ua), owner.get(ub)
        if ra is None or rb is None or ra == rb:
            continue
        if ra not in seqs or rb not in seqs:
            continue
        if len(seqs[ra]) + len(seqs[rb]) > MAX_TOUR_STOPS:
            continue
        load = loads[ra] + loads[rb]
        best: tuple[float, str, list[str]] | None = None
        for cand in _orientations(seqs[ra], seqs[rb]):
            b = _best_route(graph, depots, cand, load, fleet_cap)
            if b is None:
                continue
            if best is None or b[0] < best[0]:
                best = (b[0], b[1], cand)
        if best is None or best[0] >= cost_of(ra) + cost_of(rb) - 1e-6:
            continue
        seqs[rb] = best[2]
        loads[rb] = load
        depot_of[rb] = best[1]
        for u in best[2]:
            owner[u] = rb
        del seqs[ra], loads[ra], depot_of[ra]

    # --- Or-opt: relocate one unit between tours when it pays ---------------- #
    improved, passes = True, 0
    while improved and passes < 5:
        improved, passes = False, passes + 1
        for ka in list(seqs):
            if ka not in seqs or len(seqs[ka]) <= 1:
                continue
            seq_a = list(seqs[ka])
            for idx, u in enumerate(seq_a):
                rest = seq_a[:idx] + seq_a[idx + 1:]
                if not rest:
                    continue
                q = pending[u]
                new_load_a = loads[ka] - q
                if new_load_a <= 0:
                    continue
                b_rest = _best_route(graph, depots, rest, new_load_a, fleet_cap)
                if b_rest is None:
                    continue
                cost_a = cost_of(ka)
                moved = False
                for kb in list(seqs):
                    if kb == ka or kb not in seqs:
                        continue
                    cost_b = cost_of(kb)
                    if cost_a + cost_b - (b_rest[0]) <= 0:
                        continue
                    for pos in range(len(seqs[kb]) + 1):
                        cand = seqs[kb][:pos] + [u] + seqs[kb][pos:]
                        if len(cand) > MAX_TOUR_STOPS:
                            continue
                        b_cand = _best_route(graph, depots, cand,
                                             loads[kb] + q, fleet_cap)
                        if b_cand is None:
                            continue
                        if b_rest[0] + b_cand[0] < cost_a + cost_b - 1e-6:
                            seqs[ka], loads[ka], depot_of[ka] = rest, new_load_a, b_rest[1]
                            seqs[kb], loads[kb], depot_of[kb] = cand, loads[kb] + q, b_cand[1]
                            for x in rest:
                                owner[x] = ka
                            for x in cand:
                                owner[x] = kb
                            improved = moved = True
                            break
                    if moved:
                        break
                if moved:
                    break
            if improved:
                break

    # --- final depot re-evaluation: costs move when a tour is no longer alone - #
    for k in list(seqs):
        b = _best_route(graph, depots, seqs[k], loads[k], fleet_cap)
        if b is not None:
            depot_of[k] = b[1]

    # --- materialise: give each tour its own vehicle ------------------------- #
    routes: list[Route] = []
    for key, seq in sorted(seqs.items(), key=lambda kv: -loads[kv[0]]):
        demand = loads[key]
        if demand <= 0 or not seq:
            continue
        picked = _pick_vehicle(graph, depot_of[key], seq, demand, vehicles)
        if picked is None:
            unserved.extend(seq)
            continue
        v, m = picked
        routes.append(_make_route(v, depot_of[key], seq, demand, m,
                                  required_by_days))

    return _pack("clarke_wright_savings+or_opt (multi-depot)", routes,
                 unserved, demands, round((time.perf_counter() - t0) * 1000, 2))


def solve_routes(
    graph: TheatreGraph,
    depots: list[str],
    demands: dict[str, float],
    vehicles: list[dict],
    required_by_days: float = 7.0,
) -> tuple[Plan, Plan]:
    """Returns ``(baseline, optimised)`` so the improvement is measurable."""
    t0 = time.perf_counter()
    base = greedy_nearest(graph, depots, demands, vehicles, required_by_days)
    t1 = time.perf_counter()
    opt = clarke_wright(graph, depots, demands, vehicles, required_by_days)
    t2 = time.perf_counter()
    base.solve_ms = round((t1 - t0) * 1000, 2)
    opt.solve_ms = round((t2 - t1) * 1000, 2)
    return base, opt


def replay_plan(plan: Plan, graph: TheatreGraph) -> Plan:
    """Runs an existing plan against a *changed* network.

    This is the "no reaction" arm of MISSION SIM: the standing convoy order was
    written against the healthy network, and after the event closes corridors
    the routes that relied on them cannot run at all. Their freight is simply
    not delivered - the plan is not quietly repaired behind the scenes, which is
    exactly the failure mode the scenario is meant to expose.

    Hours and risk *are* re-priced against the new graph, because the standing
    plan still has to be driven: roads do not get faster because nobody
    re-planned, and the corridor risk premium moves with the weather.
    """
    kept: list[Route] = []
    blocked: list[dict] = []
    for r in plan.routes:
        new_legs: list[Leg] = []
        bad: Leg | None = None
        for l in r.legs:
            c = graph.corridor_by_id.get(l.corridor_id)
            if c is None or not graph.usable(c, r.capacity_t):
                bad = l
                break
            speed = ROAD_SPEED_KMPH.get(l.road_class, 25.0)
            weather = ADVERSE_HOURS_FACTOR if graph.adverse else 1.0
            new_legs.append(Leg(
                from_node=l.from_node, to_node=l.to_node,
                corridor_id=l.corridor_id, corridor_code=l.corridor_code,
                distance_km=l.distance_km, road_class=l.road_class,
                hours=(l.distance_km / speed
                       + ROAD_HANDLING_H.get(l.road_class, 0.5)) * weather,
                risk=c["closure_risk"],
            ))
        if bad is not None:
            blocked.append({
                "vehicle": r.vehicle, "depot": r.depot, "visits": r.visits,
                "distance_km": r.distance_km, "cost_inr": r.cost_inr,
                "demand_t": r.demand_t, "trips": r.trips,
                "blocked_at": bad.corridor_code,
                "blocked_leg": f"{bad.from_node}->{bad.to_node}",
                "reason": ("closed by the event" if bad.corridor_id in graph.closed
                           else "not all-weather; weather restriction applied"),
            })
            continue

        trips = r.trips
        tour_km = sum(l.distance_km for l in new_legs)
        tour_hours = sum(l.hours for l in new_legs)
        return_km = new_legs[-1].distance_km if new_legs else 0.0
        laden = max(tour_km - return_km, 0.0)
        load = r.load_t
        risk = max((l.risk for l in new_legs), default=0.0)
        fuel = trips * (laden * (FUEL_L_PER_KM_BASE + FUEL_L_PER_KM_PER_TONNE * load)
                        + return_km * FUEL_L_PER_KM_BASE * EMPTY_RETURN_FUEL_FACTOR)
        cost = trips * (laden * (VEHICLE_BASE_INR_PER_KM
                                 + VEHICLE_TONNE_INR_PER_KM * load)
                        + return_km * VEHICLE_BASE_INR_PER_KM)
        cost += trips * CREW_INR_PER_HOUR * tour_hours
        cost *= 1.0 + RISK_PRICE_WEIGHT * risk
        kept.append(Route(
            vehicle=r.vehicle, vehicle_type=r.vehicle_type,
            capacity_t=r.capacity_t, depot=r.depot, visits=list(r.visits),
            demand_t=r.demand_t, trips=trips, load_t=load,
            tour_km=round(tour_km, 1), distance_km=round(tour_km * trips, 1),
            hours=round(tour_hours * trips, 1), fuel_l=round(fuel, 1),
            cost_inr=round(cost, 0), risk=round(risk, 2), legs=new_legs,
            eta_hours=round(tour_hours, 1),
            slack_days=r.slack_days, breached=r.breached,
        ))
    out = _pack(plan.solver + " [replayed]", kept, [], {}, plan.solve_ms)
    out.blocked_routes = blocked
    return out


# --------------------------------------------------------------------------- #
# Load consolidation (first-fit-decreasing, weight + volume)
# --------------------------------------------------------------------------- #
def consolidate(lines: list[dict], vehicles: list[dict]) -> dict:
    """Packs ``{code,name,qty_kg,volume_l,category}`` lines into vehicles FFD."""
    ordered = sorted(lines, key=lambda l: (-l["qty_kg"], -l["volume_l"]))
    buckets = [
        {"vehicle": v["code"], "vehicle_type": v["vehicle_type"],
         "capacity_t": v["capacity_t"], "volume_l": v["capacity_t"] * 1000 * 0.55,
         "load_t": 0.0, "vol_l": 0.0, "lines": []}
        for v in vehicles
    ]
    overflow: list[dict] = []
    for ln in ordered:
        placed = False
        for b in buckets:
            if (b["load_t"] + ln["qty_kg"] / 1000.0 <= b["capacity_t"] + 1e-9
                    and b["vol_l"] + ln["volume_l"] <= b["volume_l"] + 1e-9):
                b["load_t"] = round(b["load_t"] + ln["qty_kg"] / 1000.0, 3)
                b["vol_l"] = round(b["vol_l"] + ln["volume_l"], 1)
                b["lines"].append({**ln, "fill_pct": round(
                    (b["load_t"] / b["capacity_t"]) * 100.0, 1)})
                placed = True
                break
        if not placed:
            overflow.append(ln)

    for b in buckets:
        b["util_pct"] = round(b["load_t"] / b["capacity_t"] * 100.0, 1) if b["capacity_t"] else 0.0
        b["vol_pct"] = round(b["vol_l"] / b["volume_l"] * 100.0, 1) if b["volume_l"] else 0.0
        b["unladen_t"] = round(b["capacity_t"] - b["load_t"], 3)
    filled = [b for b in buckets if b["lines"]]
    return {
        "buckets": filled,
        "overflow": overflow,
        "vehicles_used": len(filled),
        "vehicles_available": len(vehicles),
        "mean_util_pct": round(
            sum(b["util_pct"] for b in filled) / len(filled), 1) if filled else 0.0,
        "total_t": round(sum(b["load_t"] for b in filled), 2),
    }


# --------------------------------------------------------------------------- #
# Surplus -> deficit reallocation (greedy min-cost transportation)
# --------------------------------------------------------------------------- #
def reallocate(
    graph: TheatreGraph,
    balances: dict[str, dict[str, float]],
    demands: dict[str, float],
    vehicles: list[dict],
    *,
    max_ship_t: float = 6.0,
    give_up_frac: float = 0.45,
) -> list[dict]:
    """Moves surplus stock sideways to cover a shortfall.

    ``balances[node][item]`` is ``on_hand - floor`` (positive = surplus).
    ``demands[node]`` caps how many tonnes a recipient will accept, so the
    algorithm closes a *gap* rather than rebuilding somebody else's depot.
    """
    donors = sorted(balances)
    movements: list[dict] = []
    max_cap = max((v["capacity_t"] for v in vehicles), default=max_ship_t)
    received: dict[str, float] = {n: 0.0 for n in donors}
    caps = {n: float(demands.get(n, math.inf)) * 1000.0 for n in donors}

    pairs: list[tuple[float, str, str]] = []
    for a in donors:
        for b in donors:
            if a == b:
                continue
            legs, cost = graph.path(a, b, max_cap)
            if math.isinf(cost):
                continue
            pairs.append((cost, a, b))
    pairs.sort()

    for _cost, a, b in pairs:
        headroom = max(0.0, caps.get(b, math.inf) - received.get(b, 0.0))
        if headroom <= 1e-6:
            continue
        for item, bal_a in list(balances.get(a, {}).items()):
            need_b = balances.get(b, {}).get(item, 0.0)
            if bal_a <= 0 or need_b >= 0:
                continue
            qty = min(bal_a * give_up_frac, -need_b,
                      max_ship_t, headroom / 1000.0)
            if qty <= 1e-6:
                continue
            legs, _cost2 = graph.path(a, b, max_cap)
            if not legs:
                continue
            km, hours, _fuel, inr, risk = path_metrics(legs, qty, max_cap)
            movements.append({
                "from": a, "to": b, "item": item, "qty_t": round(qty, 2),
                "distance_km": round(km, 1), "hours": round(hours, 2),
                "cost_inr": round(inr, 0), "risk": round(risk, 2),
                "corridor": legs[0].corridor_code,
                "via": [l.corridor_code for l in legs],
                "eta_hours": round(hours, 2),
            })
            balances[a][item] = round(bal_a - qty, 3)
            balances[b][item] = round(need_b + qty, 3)
            received[b] = received.get(b, 0.0) + qty * 1000.0
            headroom = max(0.0, headroom - qty * 1000.0)
    return movements


def path_metrics(legs: list[Leg], load_t: float, capacity_t: float) -> tuple:
    """Single-trip economics for a short hop: (km, hours, fuel, cost, risk)."""
    km = sum(l.distance_km for l in legs)
    hours = sum(l.hours for l in legs)
    risk = max((l.risk for l in legs), default=0.0)
    return_km = legs[-1].distance_km if legs else 0.0
    laden = max(km - return_km, 0.0)
    fuel = laden * (FUEL_L_PER_KM_BASE + FUEL_L_PER_KM_PER_TONNE * load_t)
    fuel += return_km * FUEL_L_PER_KM_BASE * EMPTY_RETURN_FUEL_FACTOR
    cost = laden * (VEHICLE_BASE_INR_PER_KM + VEHICLE_TONNE_INR_PER_KM * load_t)
    cost += return_km * VEHICLE_BASE_INR_PER_KM
    cost += CREW_INR_PER_HOUR * hours
    cost *= 1.0 + RISK_PRICE_WEIGHT * risk
    return km, hours, fuel, cost, risk
