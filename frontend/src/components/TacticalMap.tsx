"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type * as Leaflet from "leaflet";
import type { Node, PlanRoute, Theatre } from "@/lib/types";

interface Props {
  theatre: Theatre;
  routes?: PlanRoute[];
  blocked?: string[];
  adverse?: boolean;
  selected?: string | null;
  onSelectCorridor?: (code: string) => void;
  onSelectNode?: (node: Node) => void;
  dimUnhighlighted?: boolean;
  height?: number;
  showLegend?: boolean;
}
const COLORS: Record<Node["type"], string> = { railhead: "#7454a0", depot: "#96620d", airfield: "#277155", unit: "#293c2d" };
const EMPTY_ROUTES: PlanRoute[] = [];
const EMPTY_BLOCKED: string[] = [];
type Engine = { L: typeof Leaflet; map: Leaflet.Map };

/** Leaflet uses a fictional Cartesian grid here, never latitude/longitude or navigation data. */
export default function TacticalMap({ theatre, routes = EMPTY_ROUTES, blocked = EMPTY_BLOCKED, adverse = false, selected = null, onSelectCorridor, onSelectNode, dimUnhighlighted = true, height = 470, showLegend = true }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [engine, setEngine] = useState<Engine | null>(null);
  const [error, setError] = useState(false);
  const [zoom, setZoom] = useState(0);
  const [focus, setFocus] = useState<string | null>(null);
  const [labels, setLabels] = useState(true);
  const [roads, setRoads] = useState(true);
  const [query, setQuery] = useState("");
  const { min_x, min_y, max_x, max_y } = theatre.bounds;
  const bounds = useMemo<Leaflet.LatLngTuple[]>(() => [[min_y - 12, min_x - 12], [max_y + 12, max_x + 12]], [min_x, min_y, max_x, max_y]);
  const active = useMemo(() => new Set(routes.flatMap(r => r.legs.map(l => l.corridor))), [routes]);
  const closed = useMemo(() => new Set(blocked), [blocked]);
  const picked = focus ?? selected;
  const corridor = theatre.corridors.find(c => c.code === picked);
  const node = theatre.nodes.find(n => n.code === picked);
  const status = (code: string) => closed.has(code) ? "Closed in scenario" : active.has(code) ? "Shown in plan" : "Available in demo";

  useEffect(() => {
    let disposed = false;
    let map: Leaflet.Map | undefined;
    let observer: ResizeObserver | undefined;
    import("leaflet").then(L => {
      if (disposed || !container.current) return;
      map = L.map(container.current, { crs: L.CRS.Simple, minZoom: -2, maxZoom: 5, zoomSnap: .25, zoomDelta: .5, zoomControl: false, scrollWheelZoom: false, attributionControl: true, maxBounds: L.latLngBounds(bounds).pad(.75) });
      map.attributionControl.setPrefix('<a href="https://leafletjs.com" target="_blank" rel="noopener noreferrer">Leaflet</a>');
      map.attributionControl.addAttribution("RAHAT · fictional grid");
      L.rectangle(bounds, { color: "#aeba9e", weight: 1, dashArray: "3 7", fillColor: "#e9eddf", fillOpacity: 1, interactive: false }).addTo(map);
      for (let x = Math.ceil(min_x / 10) * 10; x <= max_x; x += 10) L.polyline([[min_y - 12, x], [max_y + 12, x]], { color: "#b6c4a9", weight: .6, opacity: .6, interactive: false }).addTo(map);
      for (let y = Math.ceil(min_y / 10) * 10; y <= max_y; y += 10) L.polyline([[y, min_x - 12], [y, max_x + 12]], { color: "#b6c4a9", weight: .6, opacity: .6, interactive: false }).addTo(map);
      map.fitBounds(bounds, { padding: [16, 16], animate: false });
      setZoom(map.getZoom());
      map.on("zoomend", () => { if (map) setZoom(map.getZoom()); });
      observer = new ResizeObserver(() => map?.invalidateSize({ pan: false }));
      observer.observe(container.current);
      setEngine({ L, map });
    }).catch(() => { if (!disposed) setError(true); });
    return () => { disposed = true; observer?.disconnect(); map?.remove(); };
  }, [bounds, min_x, min_y, max_x, max_y]);

  useEffect(() => {
    if (!engine) return;
    const { L, map } = engine;
    const layers = L.layerGroup().addTo(map);
    const text = (value: string) => { const element = document.createElement("span"); element.textContent = value; return element; };
    if (roads) for (const c of theatre.corridors) {
      const highlighted = active.has(c.code) || picked === c.code;
      const color = closed.has(c.code) ? "#b83c2b" : highlighted ? "#374fbe" : "#6c7e62";
      const points: Leaflet.LatLngTuple[] = c.path.map(p => [p[1], p[0]]);
      L.polyline(points, { color: "#fffef8", weight: highlighted ? 8 : 6, interactive: false }).addTo(layers);
      L.polyline(points, { color, weight: highlighted ? 4 : 2.5, dashArray: closed.has(c.code) ? "7 7" : undefined, opacity: dimUnhighlighted && active.size > 0 && !highlighted && !closed.has(c.code) ? .4 : 1, interactive: false }).addTo(layers);
      const label = `${c.code}: ${closed.has(c.code) ? "Closed in scenario" : active.has(c.code) ? "Shown in plan" : "Available in demo"}`;
      const hit = L.polyline(points, { color, opacity: 0, weight: 16 }).addTo(layers).bindTooltip(text(label), { sticky: true });
      const choose = () => { setFocus(c.code); onSelectCorridor?.(c.code); };
      hit.on("click", choose);
      const element = hit.getElement();
      if (element) {
        element.closest("svg")?.setAttribute("role", "group");
        element.closest("svg")?.setAttribute("aria-label", "Demo connections");
        element.setAttribute("tabindex", "0"); element.setAttribute("role", "button"); element.setAttribute("aria-label", label);
        element.addEventListener("keydown", event => { const e = event as KeyboardEvent; if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); choose(); } });
      }
    }
    for (const n of theatre.nodes) {
      const icon = document.createElement("span");
      icon.className = `atlas-pin${picked === n.code ? " is-selected" : ""}`;
      icon.style.setProperty("--pin-color", COLORS[n.type]);
      icon.textContent = n.type === "airfield" ? "A" : n.type === "railhead" ? "R" : n.type === "depot" ? "D" : "U";
      const marker = L.marker([n.y, n.x], { icon: L.divIcon({ html: icon, className: "atlas-marker", iconSize: [28, 28], iconAnchor: [14, 14] }), title: `Inspect ${n.code}`, alt: `Inspect ${n.code}`, keyboard: true }).addTo(layers);
      marker.getElement()?.setAttribute("aria-label", `Inspect ${n.code}`);
      marker.bindTooltip(text(labels ? n.code : `${n.code} · ${n.name}`), { permanent: labels, direction: "top", offset: [0, -15], className: "atlas-label" });
      marker.on("click", () => { setFocus(n.code); onSelectNode?.(n); });
    }
    return () => { layers.remove(); };
  }, [engine, theatre, active, closed, picked, roads, labels, dimUnhighlighted, onSelectCorridor, onSelectNode]);

  const fit = () => engine?.map.fitBounds(bounds, { padding: [16, 16], animate: false });
  const matches = theatre.nodes.filter(n => `${n.code} ${n.name}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="map-viewer">
    <div className="map-toolbar">
      <div><span className="map-demo-dot" /><strong>Network atlas</strong><span className="map-demo-tag">Leaflet / fictional demo</span></div>
      <div className="map-tools"><button type="button" className="map-tool" onClick={() => engine?.map.zoomOut(.5)} disabled={!engine || zoom <= -2} aria-label="Zoom out">−</button><output aria-label="Map zoom">{Math.round(2 ** zoom * 100)}%</output><button type="button" className="map-tool" onClick={() => engine?.map.zoomIn(.5)} disabled={!engine || zoom >= 5} aria-label="Zoom in">+</button><button type="button" className="map-tool" onClick={fit}>Fit map</button></div>
    </div>
    <div className="map-filter-bar">
      <label className="map-search"><span className="sr-only">Find a demo location</span><input className="input" type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Find a location…" /></label>
      <label><input type="checkbox" checked={labels} onChange={e => setLabels(e.target.checked)} /> Labels</label>
      <label><input type="checkbox" checked={roads} onChange={e => setRoads(e.target.checked)} /> Connections</label>
    </div>
    {query && <div className="map-search-results">{matches.length ? matches.map(n => <button key={n.code} className="btn" onClick={() => { setFocus(n.code); onSelectNode?.(n); engine?.map.setView([n.y, n.x], Math.min(5, zoom + 1), { animate: false }); setQuery(""); }}>{n.code} · {n.name}</button>) : <p role="status">No demo locations match “{query}”.</p>}</div>}
    <div className="map-canvas" style={{ height }}>
      <div ref={container} className="leaflet-atlas" role="region" aria-label="Interactive synthetic network map" tabIndex={0} onKeyDown={e => { if (e.key === "Home") { e.preventDefault(); fit(); } }} />
      {!engine && <p className="map-loading" role={error ? "alert" : "status"}>{error ? "Map could not load. Reload the page to retry." : "Loading Leaflet map…"}</p>}
      <span className="map-compass" aria-hidden="true">↑<small>N</small></span>
      <div className="map-instruction">Drag / pinch · + / − to zoom · Home to reset</div>
      {adverse && <span className="map-weather">Adverse weather · simulated</span>}
    </div>
    {showLegend && <div className="map-legend"><span><i style={{ background: "#6c7e62" }} /> Demo connection</span><span><i style={{ background: "#374fbe" }} /> Shown in plan</span><span><i style={{ background: "#b83c2b" }} /> Scenario closure</span><span className="map-legend-note">Fictional coordinates · No live road or terrain data</span></div>}
    <div className="map-inspector" aria-live="polite">{corridor ? <><div><span className="label">Selected connection</span><strong>{corridor.code} <span>{corridor.from} → {corridor.to}</span></strong><p>{status(corridor.code)} · {corridor.distance_km.toFixed(1)} km in generated dataset</p></div><button className="btn" onClick={() => setFocus(null)}>Clear</button></> : node ? <><div><span className="label">Selected demo location</span><strong>{node.code} <span>{node.name}</span></strong><p>{node.type} · generated coordinates</p></div><button className="btn" onClick={() => setFocus(null)}>Clear</button></> : <p>Select a location or connection to inspect the demonstration data. This fictional map is not for navigation.</p>}</div>
  </div>;
}
