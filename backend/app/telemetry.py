"""In-process telemetry bus.

Emits MQTT-style topic messages from the simulated sensor gateways and fans them
out to WebSocket clients. The message shape, topic naming and retain semantics
mirror a real broker, so swapping the in-process bus for EMQX in a deployed
installation is a drop-in change (``RAHAT_MQTT_URL`` is read but unused here -
see ``docs/ARCHITECTURE.md``).
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field

from . import repository as repo
from .config import settings

TOPIC_FMT = "rahat/{gateway}/{kind}"


@dataclass
class TelemetryHub:
    clients: set = field(default_factory=set)
    latest: dict[int, dict] = field(default_factory=dict)
    topic_log: deque = field(default_factory=lambda: deque(maxlen=60))
    series: dict[int, dict] = field(default_factory=dict)
    ticks: int = 0
    started_at: float = 0.0
    persist_every_n: int = 30
    _buffer: list = field(default_factory=list)
    _task: asyncio.Task | None = None

    # ---- subscribe ------------------------------------------------------- #
    async def subscribe(self):
        queue: asyncio.Queue = asyncio.Queue(maxsize=32)
        self.clients.add(queue)
        queue.put_nowait({"type": "snapshot", "nodes": list(self.latest.values()),
                          "ticks": self.ticks})
        try:
            while True:
                yield await queue.get()
        finally:
            self.clients.discard(queue)

    def publish(self, payload: dict) -> None:
        for q in list(self.clients):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    # ---- generation ------------------------------------------------------ #
    def _tick(self) -> dict:
        w = repo.load_world()
        ts = repo.now_iso()
        now = time.time()
        batch: list[dict] = []
        frame: list[dict] = []

        for sn in w.sensors:
            nid = sn["node_id"]
            node = next((n for n in w.nodes if n["id"] == nid), None)
            if node is None:
                continue
            prev = self.latest.get(nid, {})
            jitter = random.Random((settings.theatre_seed + nid * 31 + self.ticks))

            # Weight drifts slowly (stock being drawn down); environment tracks
            # the node's altitude; humidity anti-correlates with temperature.
            weight = prev.get("weight", jitter.uniform(180, 940))
            weight = max(0.0, weight - abs(jitter.gauss(0, 1.4)))
            temp = round(-2.5 - node["elevation_m"] / 620.0 + jitter.gauss(0, 0.7), 1)
            hum = round(max(8.0, min(96.0, 74 - temp * 1.6 + jitter.gauss(0, 3.5))), 1)
            batt = max(4.0, sn.get("battery_pct", 100) - self.ticks * 0.0009)
            online = sn.get("online", True)

            values = {"weight": round(weight, 1), "temp": temp, "humidity": hum,
                      "battery": round(batt, 1), "signal": sn.get("signal_dbm", -70)}
            for kind, val in (("weight", values["weight"]), ("temp", temp),
                              ("humidity", hum)):
                topic = TOPIC_FMT.format(gateway=sn["gateway"], kind=kind)
                batch.append({
                    "node_id": nid, "ts": ts, "kind": kind, "value": float(val),
                    "unit": {"weight": "kg", "temp": "C", "humidity": "%"}[kind],
                    "online": online, "topic": topic,
                })
                if self.ticks % 3 == 0:
                    self.topic_log.append(f"{topic}  {val}")

            entry = {
                "node_id": nid, "code": node["code"], "name": node["name"],
                "gateway": sn["gateway"], "online": online,
                "ts": ts, **values,
            }
            self.latest[nid] = entry
            frame.append(entry)

            s = self.series.setdefault(nid, {"weight": deque(maxlen=90),
                                             "temp": deque(maxlen=90),
                                             "humidity": deque(maxlen=90),
                                             "ts": deque(maxlen=90)})
            s["weight"].append(values["weight"])
            s["temp"].append(temp)
            s["humidity"].append(hum)
            s["ts"].append(ts)

        self.ticks += 1
        self._buffer.extend(batch)
        if self.ticks % self.persist_every_n == 0 and self._buffer:
            rows, self._buffer = self._buffer, []
            try:
                repo.record_readings(rows)
            except Exception:
                # Telemetry must never take the dashboard down.
                self._buffer = rows[-500:]

        return {"type": "frame", "ts": ts, "ticks": self.ticks,
                "nodes": frame, "mqtt": list(self.topic_log)[-8:]}

    async def run(self) -> None:
        self.started_at = time.time()
        while True:
            try:
                frame = await asyncio.to_thread(self._tick)
            except Exception:
                await asyncio.sleep(settings.telemetry_interval_s)
                continue
            self.publish(frame)
            await asyncio.sleep(settings.telemetry_interval_s)

    def start(self) -> None:
        if self._task is None or self._task.done():
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            self._task = loop.create_task(self.run(), name="rahat-telemetry")

    def snapshot(self) -> dict:
        return {
            "ticks": self.ticks,
            "uptime_s": round(time.time() - self.started_at, 1) if self.started_at else 0,
            "clients": len(self.clients),
            "gateways": len(self.latest),
            "nodes": list(self.latest.values()),
            "mqtt": list(self.topic_log)[-8:],
            "series": {nid: {k: list(v) for k, v in s.items()}
                       for nid, s in self.series.items()},
        }


hub = TelemetryHub()
