# Deployment and manual GitHub upload

## Which folder to upload

The curated export is `github-ready/RAHAT-SIH26251/` in the original working directory. Upload the **contents of that folder** as the repository root. It includes dotfiles such as `.gitignore` and `.env.example`; show hidden files in your file picker or use Git to include them. The supplied ZIP contains the same tree for extraction before upload.

No database, `.env`, Git history, installed dependencies, build output, virtual environment or OS files are included. The original development folder is preserved. Later changes in the original folder are not automatically copied into this snapshot.

## Local Docker demonstration

1. Install Docker and start its engine.
2. Copy `.env.example` to `.env` at the repository root.
3. Replace `JWT_SECRET` with a random value from `openssl rand -hex 32`.
4. Run:

```sh
docker compose up --build -d
docker compose ps
```

Frontend: http://localhost:3000. API: http://localhost:8000/api/v1/health.

Both published ports bind to loopback by default. The web container waits for API health before starting. Model training continues in the background; API health being reachable does not mean its model is ready. The API uses one worker because the simulated telemetry bus and model state are in-process.

Data persists in the `rahat-data` Docker volume. Stop using `docker compose down`; avoid `down -v` unless you intend to delete the demonstration database. First start creates fresh synthetic data, so local test edits are not transferred to a new deployment.

## Environment configuration

| Setting | Consumer | Purpose |
|---|---|---|
| `JWT_SECRET` | API | JWT signing key; keep private |
| `CORS_ORIGINS` | API | JSON array of allowed frontend origins |
| `THEATRE_SEED` | API | Seed for the initially generated demonstration dataset |
| `NEXT_PUBLIC_API_URL` | Frontend build | Browser-accessible API URL including `/api/v1` |
| `DATABASE_URL` | API | Compose sets SQLite under `/data` |

The root `.env` is read by Docker Compose. Local Python development reads `backend/.env` or exported shell variables. Local Next.js development reads `frontend/.env.local`; its example is supplied. Never put private values in `NEXT_PUBLIC_*` variables, which are shipped to browsers.

The frontend API URL is embedded at build time. Rebuild the frontend when it changes. `localhost` refers to the browser's machine; it is only appropriate for this local demonstration.

## Hosting on a server

The frontend Docker image uses Next.js standalone output and runs as a non-root user. The backend also runs as a non-root user and needs a writable persistent `/data` volume. This is a two-service application; uploading only the frontend does not deploy the API.

Before exposing a hosted instance, implement a production account lifecycle and replace/remove the seeded public demo accounts, configure a private signing key and exact CORS origins, and put both services behind HTTPS. Public access is deliberately not enabled in the supplied Compose file. Changing the JWT secret alone does not disable the demo passwords. Configure the browser-visible API URL at build time and support WebSocket upgrades in the reverse proxy.

External MQTT ingestion and PostgreSQL support are not wired up in the supplied deployment. Previously advertised optional broker/database profiles were removed to avoid implying an integration that does not exist.

## Validation scope

Compose syntax was validated. The production frontend build and local API checks are recorded in `docs/EVALUATION.md`. Docker images were not executed here because the Docker daemon was not running. Run the Docker procedure above to verify the container environment on your machine.
