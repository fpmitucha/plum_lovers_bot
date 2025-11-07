# Refactor Roadmap

## 1. Foundation & Alignment
- Capture success criteria with stakeholders: supported runtimes, deployment targets (bare metal, Docker, etc.), feature set (audio transcription, karma, approvals), SLAs, and explicit non-goals.
- Inventory production data and ops constraints: current SQLite files, row counts per table, cron jobs, manual scripts, hosting CPU/RAM limits, and secret storage to design safe migrations and rollouts.
- Decide target platform choices (database engine, task runner, dependency manager, CI provider) and ratify them before code changes.

## 2. Configuration & Dependency Hygiene
- Move to a single dependency source of truth (Poetry or uv-managed `pyproject.toml`) with optional extras (`audio`, `dev`, `test`) and lockfiles; remove the divergent `requirements.txt`.
- Add `.python-version`/`.tool-versions` (if relevant) and `.env.example` documenting every required env var, default, and owner.
- Create a shared bootstrap module (e.g., `bot.bootstrap`) that configures logging, loads `.env`, and registers `src` paths so scripts stop mutating `sys.path`/`cwd`.

## 3. Database & Persistence
- Introduce Alembic (or similar) migrations:
  1. Snapshot current schema as an initial revision via `alembic revision --autogenerate`.
  2. Replace runtime schema mutations (`Base.metadata.create_all`, `Repo.ensure_aux_tables`, `_ensure_karma_column`, start-up roster seeding) with explicit migrations and data-migration scripts.
  3. Retire manual patch scripts (`patch_sqlite_schema.py`, `recreate_*`, `fix_karma_null`) in favor of `alembic upgrade/downgrade`.
- Provide a centralized `SessionManager`/middleware that manages async sessions, retries, and cleanup; handlers should request sessions via dependency injection rather than instantiating them.
- Evaluate moving from SQLite to Postgres for concurrency; if staying on SQLite, enforce WAL mode, per-request connections, and locking strategy.

## 4. Domain & Service Layer Cleanup
- Extract cohesive services (RosterService, ApplicationService, KarmaService) so handlers only orchestrate Telegram I/O while services own business logic.
- Normalize ORM models: ensure `Profile` carries stable columns (language, joined timestamps) via migrations instead of runtime `ALTER TABLE`.
- Introduce DTOs/Pydantic models for handler inputs/outputs, validating data before it touches the database.

## 5. Async Tasks & Audio Pipeline
- Offload CPU/IO-heavy transcription to a worker:
  1. Define `A2TJob` schema and queue (DB table, Redis, or task broker) plus a worker service (Celery, Arq, or FastAPI background runner).
  2. Bot handlers enqueue jobs, send progress messages, and poll job status or receive callbacks/webhooks.
- Wrap audio dependencies (ffmpeg, faster-whisper, vosk) behind feature flags/config so environments without them degrade gracefully.
- Add throttling/caching per user to prevent abuse and control hardware usage.

## 6. External Integrations & Configuration
- Replace HTML scraping of `tg-user.id` with official Telegram methods or encapsulate the client with retries, rate-limiting, structured logging, and unit tests.
- Structure settings via `pydantic-settings` with nested models per feature; initialize lazily to avoid crashing when optional configs are absent.
- Document operational runbooks (refresh commands, health checks) and convert bespoke scripts into a consistent Typer/Click CLI.

## 7. Logging, Metrics & Observability
- Standardize logging (JSON or key-value) with context (request IDs, user IDs) and levels; remove blanket `except Exception: pass`.
- Add error-handling middleware that logs stack traces and optionally notifies maintainers.
- Expose metrics (Prometheus or simple aggregates) for message throughput, DB latency, and transcription success so regressions are visible.

## 8. Testing & CI/CD
- Stand up pytest with `pytest-asyncio`, covering:
  - Unit tests for services/repos using in-memory SQLite or test containers.
  - Handler tests using aiogram factories.
  - Integration tests for migrations, A2T workflow, `/whoami` with mocked external API.
- Add pre-commit hooks (Ruff/Black/mypy) and CI (GitHub Actions) to run linting, tests, and type checks on every PR.
- Provide fixtures for sample data and remove ad-hoc scripts (`test_import.py`, `test_whoami_handler.py`).

## 9. Deployment & Operations
- Containerize the app with a multi-stage Dockerfile and health checks; run as non-root.
- Define process management (Docker Compose, Kubernetes) with separate services for bot, worker, and migrations; ensure startup waits for DB readiness.
- Automate migrations during deploy (`alembic upgrade head`) and document rollback steps plus DB/media backup/restore procedures.

## 10. Gradual Rollout Strategy
- Sequence changes to minimize downtime:
  1. Stabilize config/deps and introduce tests.
  2. Add migrations and remove runtime DDL.
  3. Ship new service layer + audio worker behind feature flags.
  4. Flip features on per environment, monitoring metrics/logs between stages.
- Use feature toggles (.env flags) so new components can be enabled/disabled quickly if regressions appear.
