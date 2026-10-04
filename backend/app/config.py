"""RAHAT configuration.

Everything is driven by environment variables so the same image runs in:
  * local dev (SQLite, embedded telemetry)
  * Docker Compose (SQLite volume by default, PostgreSQL via DATABASE_URL)
  * air-gapped edge node (embedded SQLite, no egress)
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    app_name: str = "RAHAT"
    app_tagline: str = "Predictive Forward Supply Chain"
    ps_number: str = "SIH26251"
    version: str = "1.0.0"

    # Sync data layer so the same repository code runs on an edge node
    # (embedded SQLite) and on the core node (PostgreSQL).
    database_url: str = f"sqlite:///{BASE_DIR / 'rahat.db'}"

    # Deterministic theatre generation. Same seed => same theatre, so every
    # number in your PPT and demo run-sheet is reproducible.
    theatre_seed: int = 20261005

    # Simulated clock: the generator and backtests run against a fixed window
    # so historical actuals always exist.
    history_days: int = 112
    forecast_default_horizon: int = 30

    # Telemetry bus (MQTT-compatible topic semantics, in-process by default).
    telemetry_interval_s: float = 1.0
    mqtt_url: str | None = None  # e.g. "mqtt://localhost:1883" when EMQX is up

    # Auth: HS256 JWT. Override jwt_secret in any shared deployment.
    jwt_secret: str = "rahat-dev-secret-change-me"
    jwt_ttl_s: int = 60 * 60 * 12

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Solver + forecasting tuning
    solver_max_runtime_s: float = 6.0
    service_level: float = 0.95
    random_seed: int = 7


settings = Settings()
