/* Response shapes produced by the RAHAT backend (`/api/v1`).
   Derived directly from `backend/app/api.py` + domain return statements. */

/* ── Auth ──────────────────────────────────────────────────────────── */

export interface RoleEntry {
  label: string;
  can: string[];
}
/** `GET /auth/roles` → keyed by role slug. */
export type Roles = Record<string, RoleEntry>;

export interface User {
  username: string;
  display_name: string;
  role: string;
  role_label: string;
  perms: string[];
}

export interface LoginResponse {
  token: string;
  username: string;
  display_name: string;
  role: string;
  role_label: string;
  perms: string[];
}

/* ── Health / meta ─────────────────────────────────────────────────── */

export interface ModelInfo {
  status: string;
  message?: string;
  rows: number;
  series: number;
  features: number;
  train_ms: number;
  backtest_ms: number;
  error: string;
  leaderboard: LeaderRow[];
  trained_at: number;
}

export interface Health {
  status: string;
  app: string;
  version: string;
  ps: string;
  model: ModelInfo;
  db_version: number;
  telemetry_ticks: number;
}

export interface Meta {
  app: string;
  tagline: string;
  ps_number: string;
  version: string;
  theatre_seed: number;
  history_days: number;
  today: string;
  scenarios: ScenarioStub[];
  features: number;
  counts: Record<string, number>;
  categories: string[];
  themes: string[];
}

/* ── Theatre / map ─────────────────────────────────────────────────── */

export type NodeType = "unit" | "depot" | "railhead" | "airfield";

export interface Node {
  id: number;
  code: string;
  name: string;
  type: NodeType;
  lat: number;
  lon: number;
  x: number;
  y: number;
  elevation_m: number;
  personnel: number;
  district: string;
  access_road: string;
  isolation_km: number;
  capacity_t: number;
  is_critical: boolean;
}

export interface Corridor {
  id: number;
  code: string;
  name: string;
  from: string;
  to: string;
  from_id: number;
  to_id: number;
  distance_km: number;
  grade_pct: number;
  road_class: string;
  all_weather: boolean;
  closure_risk: number;
  capacity_t: number;
  altitude_pass_m: number;
  path: [number, number][];
  mid: [number, number];
}

export interface Bounds {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
}

export interface Theatre {
  anchor: {
    lat: number;
    lon: number;
    km_per_deg_lat: number;
    km_per_deg_lon: number;
  };
  bounds: Bounds;
  nodes: Node[];
  corridors: Corridor[];
  elevation_profile: [number, number][][];
}

/* ── KPIs / alerts ─────────────────────────────────────────────────── */

export interface DosLine {
  node: string;
  item: string;
  name: string;
  on_hand: number;
  min_level: number;
  in_transit: number;
  dos: number;
}

export interface Kpis {
  units_total: number;
  units_at_risk: number;
  unit_risk_list: string[];
  fill_rate_pct: number;
  convoys_active: number;
  convoys_total: number;
  tonnes_in_transit: number;
  cost_per_tonne_km: number;
  network_efficiency_index: number;
  sensor_online_pct: number;
  alerts_open: number;
  alerts_critical: number;
  model_status: string;
  dos: DosLine[];
  unit_days_of_supply: Record<string, number>;
}

export type Severity = "critical" | "warning" | "info";

export interface Alert {
  id: number;
  ts: string;
  severity: Severity;
  type: string;
  message: string;
  action: string;
  acknowledged: boolean;
  node: string | null;
}

/* ── Convoys ───────────────────────────────────────────────────────── */

export interface ManifestLine {
  item_code: string;
  qty: number;
}

export interface Convoy {
  id: number;
  code: string;
  vehicle_type: string;
  capacity_t: number;
  status: "planned" | "loading" | "in_transit" | "delivered" | "held";
  load_t: number;
  distance_km: number;
  fuel_l: number;
  risk_score: number;
  origin: string;
  dest: string;
  origin_name: string;
  dest_name: string;
  manifest: ManifestLine[];
  route: [number, number][];
  plan_id: string;
  kind: string;
  progress_seed: number;
}

/* ── Inventory / IoT ───────────────────────────────────────────────── */

export interface InventoryRow {
  node: string;
  node_type: string;
  item: string;
  name: string;
  category: string;
  critical: boolean;
  on_hand: number;
  reserved: number;
  in_transit: number;
  min_level: number;
  reorder_qty: number;
  daily_rate: number;
  dos_days: number;
  fill_pct: number;
  status: "critical" | "low" | "ok";
}

export interface InventoryResponse {
  items: InventoryRow[];
  count: number;
}

export interface SensorNode {
  node_id: number;
  code?: string;
  name?: string;
  gateway: string;
  protocol?: string;
  battery_pct?: number;
  signal_dbm?: number;
  online?: boolean;
  node_code?: string;
  elevation_m?: number;
  /** live frame */
  node_code_live?: string;
  online_live?: boolean;
  ts?: string;
  weight?: number;
  temp?: number;
  humidity?: number;
  battery?: number;
  signal?: number;
}

export interface SensorsResponse {
  nodes: (SensorNode & { code: string; name: string; online: boolean })[];
  ticks: number;
  clients: number;
  mqtt: string[];
  uptime_s: number;
  online_pct: number;
}

/* ── Forecast ──────────────────────────────────────────────────────── */

export interface LeaderRow {
  model: string;
  mape: number;
  mae: number;
  mase: number;
  pinball: number;
  folds: number;
  is_champion: boolean;
}

export interface SeriesList {
  status: string;
  pairs: { node: string; item: string; label: string }[];
  leaderboard: LeaderRow[];
  train_ms: number;
  backtest_ms: number;
  rows: number;
}

export interface Leaderboard {
  leaderboard: LeaderRow[];
  per_pair: Record<string, Record<string, Omit<LeaderRow, "model" | "is_champion">>>;
  rows: number;
  series: number;
  features: number;
  train_ms: number;
  backtest_ms: number;
  status: string;
  models: string[];
  method: string;
}

export interface Point {
  day: string;
  actual: number | null;
  p50: number | null;
  p10: number | null;
  p90: number | null;
  history: boolean;
}

export interface AttributionEntry {
  feature: string;
  label: string;
  kind: string;
  contribution: number;
  value: number;
  unit: string;
  display: string;
  share_pct?: number;
}

export interface ForecastSummary {
  total_kg: number;
  daily_mean: number;
  peak_kg: number;
  peak_day: string;
  p10_total_kg: number;
  p90_total_kg: number;
  band_width_pct: number;
  naive_total_kg: number;
  history_mean_kg: number;
}

export interface Forecast {
  node_code: string;
  item_code: string;
  item_name: string;
  category: string;
  horizon: number;
  model: string;
  series: Point[];
  summary: ForecastSummary;
  attribution: AttributionEntry[];
  narrative: string;
  metrics: { series: LeaderRow | null; leaderboard: LeaderRow[]; mape: number | null; mase: number | null };
  inputs: {
    tempo_future: string;
    ops_future: number;
    rainfall_mult: number;
    temp_offset: number;
    demand_mult: number;
  };
  trained_at: number;
  train_ms: number;
  backtest_ms: number;
}

/* ── Planner ───────────────────────────────────────────────────────── */

export interface PlanLeg {
  from: string;
  to: string;
  corridor: string;
  km: number;
  road: string;
  hours: number;
  risk: number;
}

export interface PlanRoute {
  vehicle: string;
  vehicle_type: string;
  capacity_t: number;
  depot: string;
  visits: string[];
  load_t: number;
  distance_km: number;
  hours: number;
  fuel_l: number;
  cost_inr: number;
  risk: number;
  eta_hours: number;
  slack_days: number;
  breached: boolean;
  legs: PlanLeg[];
}

export interface PlanSide {
  solver: string;
  solve_ms: number;
  distance_km: number;
  cost_inr: number;
  fuel_l: number;
  hours: number;
  utilisation_pct: number;
  worst_risk: number;
  unserved: string[];
  served: string[];
  routes: PlanRoute[];
}

export interface PlanResponse {
  demands_t: Record<string, number>;
  horizon: number;
  fleet: { code: string; vehicle_type: string; capacity_t: number }[];
  closed: string[];
  adverse: boolean;
  baseline: PlanSide;
  optimised: PlanSide;
  total_ms: number;
  improvement: {
    distance_km: number;
    distance_pct: number;
    cost_inr: number;
    cost_pct: number;
    fuel_l: number;
    utilisation_pct: number;
  };
  cost_model: Record<string, number>;
}

export interface PackingLine {
  code?: string;
  item_code?: string;
  name?: string;
  category?: string;
  qty_kg?: number;
  volume_l?: number;
  destination?: string;
  fill_pct?: number;
}

export interface PackingBucket {
  vehicle: string;
  vehicle_type: string;
  capacity_t: number;
  volume_l: number;
  load_t: number;
  vol_l: number;
  lines: PackingLine[];
  util_pct: number;
  vol_pct: number;
  unladen_t: number;
}

export interface PackingResult {
  buckets: PackingBucket[];
  overflow: Record<string, unknown>[];
  vehicles_used: number;
  vehicles_available: number;
  mean_util_pct: number;
  total_t: number;
  total_kg?: number;
}

export interface Movement {
  from: string;
  to: string;
  item: string;
  qty_t: number;
  distance_km: number;
  hours: number;
  cost_inr: number;
  risk: number;
  corridor: string;
  via: string[];
  eta_hours: number;
}

export interface ReallocateResponse {
  movements: Movement[];
  total_t: number;
  total_cost_inr: number;
  from: string[];
}

/* ── Mission Sim ───────────────────────────────────────────────────── */

export interface ScenarioParams {
  close: string[];
  adverse: boolean;
  risk_boost: number;
  rainfall_mult: number;
  demand_mult?: number;
  capacity_mult?: number;
  delay_hours?: number;
}

export interface ScenarioStub {
  key: string;
  label: string;
  description: string;
  icon: string;
  severity: string;
  talking_point: string;
  params: ScenarioParams;
}

export interface Stockout {
  node: string;
  item: string;
  item_name: string;
  day: number;
  dos_days: number;
  req_kg: number;
  supply_kg: number;
  fill_pct: number;
}

export interface NodeFill {
  node: string;
  worst_dos: number;
  items: { item: string; fill_pct: number; dos_days: number }[];
}

export interface Projection {
  fill_rate_pct: number;
  units_at_risk: string[];
  stockouts: Stockout[];
  nodes: NodeFill[];
}

export interface BlockedRoute {
  vehicle: string;
  depot: string;
  visits: string[];
  distance_km: number;
  cost_inr: number;
  demand_t: number;
  trips: number;
  blocked_at: string;
  blocked_leg: string;
  reason: string;
}

export interface PlanMetrics {
  cost_inr: number;
  distance_km: number;
  fuel_l: number;
  hours: number;
  routes: number;
  trips: number;
  tonnage_t: number;
  delivered_t: number;
  cost_per_tonne_inr: number | null;
  utilisation_pct: number;
  worst_risk: number;
  unserved: string[];
  blocked_routes: BlockedRoute[];
  solve_ms: number;
  solver: string;
}

export interface StrandedNode {
  node: string;
  name: string;
  prestaged_t: number;
  gap_t: number;
  requirement_t: number;
  on_hand_t: number;
  horizon_demand_t: number;
  days_left: number;
  action: string;
}

export interface SimDelta {
  cost_inr: number;
  distance_km: number;
  fill_rate_pct: number;
  delivered_t: number;
  cost_per_tonne_inr: number;
  units_at_risk_before: number;
  units_at_risk_after: number;
  stockouts_before: number;
  stockouts_after: number;
  blocked_routes: number;
}

export interface SimAlert {
  severity: Severity;
  type: string;
  node: string;
  message: string;
  action: string;
}

export interface Sim {
  id?: number;
  scenario: string;
  label: string;
  description: string;
  icon: string;
  severity: string;
  talking_point: string;
  params: ScenarioParams;
  horizon: number;
  generated_at: string;
  solve_ms: number;
  stranded: StrandedNode[];
  prestage: Movement[];
  prestage_t: number;
  before: Projection;
  after: Projection;
  plans: {
    pre_disruption: PlanMetrics;
    no_reaction: PlanMetrics;
    rahat: PlanMetrics;
  };
  delta: SimDelta;
  packing: PackingResult | null;
  briefing_note: string;
  alerts: SimAlert[];
  requirements: Record<string, Record<string, number>>;
}

export interface SimSummary {
  id: number;
  created_at: string;
  scenario: string;
  label: string;
  params: ScenarioParams;
  solve_ms: number;
  solver: string;
  result: {
    delta: SimDelta;
    plans: Sim["plans"];
    stranded: StrandedNode[];
    prestage_t: number;
    horizon: number;
    severity: string;
  };
  username: string;
}

/* ── Resilience ────────────────────────────────────────────────────── */

export interface FragilityCorridor {
  id: number;
  code: string;
  name: string;
  road_class: string;
  all_weather: boolean;
  distance_km: number;
  closure_risk: number;
  capacity_t: number;
  units_lost: string[];
  blast_radius: number;
  detours: { node: string; extra_km: number }[];
  detour_km: number;
  efficiency_drop_pct: number;
  single_point: boolean;
  severity: "critical" | "high" | "medium" | "low";
}

export interface NodeAxes {
  node: string;
  name: string;
  axes: number;
  all_weather_axes: number;
  sole_axis: string | null;
  isolation_km: number;
  vulnerable: boolean;
}

export interface Fragility {
  base_efficiency: number;
  corridors: FragilityCorridor[];
  single_points: FragilityCorridor[];
  nodes: NodeAxes[];
  coverage: Record<string, { km: number; risk: number; reachable: boolean }>;
  compute_ms: number;
}

export interface StressPoint {
  failed: number;
  closed: string[];
  closed_names: string[];
  unreachable: number;
  efficiency_pct: number;
  mean_km: number;
  mean_risk: number;
  label: string;
}

export interface StressCurve {
  base_efficiency: number;
  points: StressPoint[];
  critical_threshold: number | null;
}

/* ── Admin ─────────────────────────────────────────────────────────── */

export interface AuditEntry {
  id: number;
  ts: string;
  username: string;
  role: string;
  action: string;
  entity: string;
  detail: Record<string, unknown> | null;
}

export interface AdminUser {
  id: number;
  username: string;
  display_name: string;
  role: string;
  can_override: boolean;
  created_at: string;
}

export interface SimHistoryRow {
  id: number;
  created_at: string;
  scenario: string;
  label: string;
  solve_ms: number;
  solver: string;
  username: string;
}
