# Prototype evaluation and verification

Review date: 4 October 2026. This is an independent code/UI review, not an official SIH assessment. The precise official PS26251 brief could not be independently retrieved from the SIH site during review; confirm submission criteria against the official brief before claiming complete coverage.

## Assessment

The project has a coherent visual identity and substantial demonstration screens. It is suitable for presenting a synthetic prototype after the remaining workflows are checked. It is not yet justified to describe it as fully functional, field-ready, or guaranteed to win.

The strongest next improvements are evidence and reliability: a small non-sensitive physical sensor demonstration, an explicit record of data source/freshness, offline read-only state with a visible last-sync timestamp, accessible task flows, and a reproducible evaluation pack. These recommendations concern general software quality; they do not validate military planning outcomes.

## Fixed during this review

- Missing model names in per-series metrics caused the forecast screen to crash.
- Presets without a `close` array caused the simulation screen to crash on rendering.
- WebSocket authentication used the wrong request dependency, causing handshake errors.
- Malformed authentication tokens could produce server errors; invalid tokens are rejected.
- Empty passwords no longer fall back to demo credentials.
- The users endpoint now requires administrator permissions.
- Inventory category options no longer disappear when a filter is applied.
- Session expiry is surfaced, and reconnecting telemetry does not leave fallback polling running.
- Cold-start rendering tolerates a model leaderboard that is not ready yet.
- Typography no longer depends on downloading Google Fonts during the build.
- Replaced the dark frontend with a responsive editorial design and original illustration.
- Integrated open-source Leaflet with a fictional coordinate system and accessible map zoom, search, selection, layer toggles and keyboard/pointer pan for the fictional schematic.
- Deployment ignores exclude local environment files and databases; the frontend image uses minimal standalone output under a non-root account.

## What was checked

- Frontend ESLint and production build.
- Forty local API/authentication/WebSocket smoke assertions; machine-readable results are in `verification/api-results.json`.
- Browser sign-in; dashboard; forecast tables after the crash fix; inventory location/category filters; admin user table; resilience page rendering; seven simulation preset cards; existing briefing preview.
- Mobile layout at 390 × 844 for representative screens, including the map, checked for document overflow.
- New map search, zoom, selection, layer toggles, keyboard pan and reset checked in the browser.
- Docker Compose configuration validation.

## What remains unverified or incomplete

- Planning, simulation and resilience algorithm correctness and every mutation workflow have not been validated by this review. Rendering a screen is not an end-to-end correctness test.
- Report clipboard/download actions were attempted but not confirmed; they need a separate check.
- Docker runtime was not available, so container image execution is unverified.
- External MQTT ingestion is not implemented; sensor frames are generated inside the API.
- There is no production user provisioning, password-change lifecycle or implemented approval workflow. Public demo accounts remain in the source.
- PostgreSQL migration is not supplied. The supported demonstration configuration is SQLite with one API worker.
- Offline map drawing is supported, but the full application still needs its API; there is no offline data cache and conflict-resolution workflow.
- Geographic tiles, live GPS, real terrain, real road conditions and camp tracking are not implemented. The map must remain labelled synthetic.
- Model performance on generated data is not evidence of performance on unseen real-world datasets. p10–p90 is a nominal 80% interval; empirical coverage and calibration need to be reported honestly. Aggregate MASE below 1 does not imply every series or fold beats the baseline.

## Presentation priorities

1. Demonstrate one reliable user journey with input provenance, visible timestamps and recoverable errors.
2. Show measured results and uncertainty with a reproducible dataset/version record; clearly label synthetic evidence.
3. Validate accessibility and usability with people unfamiliar with the application and record task completion times/errors.
4. Demonstrate a non-sensitive physical sensor in a controlled setting and separate its actual readings from simulated frames.
5. Complete the deployment and account-management gaps before claiming production readiness.

The historical pitch and architecture notes in the original workspace predate this review. They are not included in the clean deployment export because some describe planned integrations as finished capabilities.
