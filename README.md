# RAHAT — Predictive Forward Supply Chain

Student prototype for SIH26251. Next.js/React frontend and FastAPI backend with a deterministic synthetic dataset, forecasting screens, inventory views, generated telemetry, and a fictional network demonstration.

**This is a demonstration, not a validated operational system.** Locations, connections, sensor readings and outcomes are simulated. The map is an interactive offline Leaflet schematic; it does not contain geographic tiles, live traffic, verified terrain or GPS tracking.

## Run locally

Use Python 3.12+ and Node.js 24 with pnpm 11.19.0.

In one terminal:

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm dev --hostname 127.0.0.1
```

Open [the website](http://127.0.0.1:3000). API documentation: [OpenAPI](http://127.0.0.1:8000/docs). On first boot the API seeds its local database and trains models; wait for **MODEL · ready** before testing forecasting screens.

Demo accounts: `commander`, `logistics`, `quartermaster`, `admin`. Each demo password equals its username. These are public test credentials, unsuitable for a public production service.

## Docker deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for environment variables, persistent data, build instructions, and the limits of the included demonstration deployment.

## Interface

The visual refresh uses an ivory background, dark editorial typography, vermillion and blue accents, responsive navigation, and an original isometric logistics illustration. Design references: [SIH Buddy](https://www.sihbuddy.in/) and [Emons](https://www.emons.de/).

The locally bundled [Leaflet](https://leafletjs.com/examples/crs-simple/crs-simple.html) map uses `CRS.Simple` for fictional coordinates and supports drag/keyboard panning, zoom, fit-to-view, location search, label/connection toggles and selectable details. It runs without external map services. Connection status reflects the synthetic data or selected demonstration scenario, not live road conditions.

## Project structure

- `frontend/src/`: application pages, UI components and API client.
- `frontend/public/`: static assets served by Next.js.
- `backend/app/`: API, authentication, database and demonstration logic.
- `backend/tests/smoke_test.py`: local API/authentication/WebSocket checks.
- `docs/EVALUATION.md`: evaluator review, verification scope and remaining gaps.
- `docs/verification/`: recorded test results.
- `docker-compose.yml`, Dockerfiles and `.env.example`: local demonstration deployment.

## Verification

```sh
cd frontend
pnpm lint
pnpm build
```

With the API running and its seeded demonstration data available, from the repository root:

```sh
backend/.venv/bin/python backend/tests/smoke_test.py
```

The smoke test uses demo accounts and adds login audit records. It does not validate domain algorithms, deployment security, real sensor integration or all interactive workflows. See the evaluation document for the exact tested scope.

## Known limits

Telemetry uses an in-process simulator; external MQTT ingestion is not implemented. SQLite is the included database deployment. PostgreSQL migration and an external message broker require additional integration. There is no offline cache/synchronisation workflow, production account lifecycle, or implemented approval workflow despite the existing role permission name.

An attractive interface and a passing build do not establish field readiness or guarantee a competition result. Keep demonstration claims tied to reproducible evidence.
