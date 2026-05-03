# Contributing to KubeRiva OMS

Thank you for considering a contribution. This guide covers everything you need to get from "I want to help" to a merged pull request.

---

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [Where to Start](#where-to-start)
3. [Local Development Setup](#local-development-setup)
4. [Project Structure](#project-structure)
5. [Making Changes](#making-changes)
6. [Writing Tests](#writing-tests)
7. [Submitting a Pull Request](#submitting-a-pull-request)
8. [Building a Connector](#building-a-connector)
9. [Style Guide](#style-guide)
10. [Getting Help](#getting-help)

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating you agree to uphold it. Report unacceptable behavior via [GitHub's contact form](https://github.com/contact) or by opening a private security advisory in this repository.

---

## Where to Start

- **Good first issues**: [issues labeled `good first issue`](https://github.com/KubeRiva/OMS/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) — each one includes exact files to edit, expected before/after behavior, and a pointer to the relevant section of this guide.
- **Help wanted**: [issues labeled `help wanted`](https://github.com/KubeRiva/OMS/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22) — larger scope, good for experienced contributors.
- **New connector**: Want to add WooCommerce, Magento, or a carrier? Open a [Connector Request](https://github.com/KubeRiva/OMS/issues/new?template=connector_request.yml) first so we can align on the interface.

If you're unsure where to begin, ask in [GitHub Discussions](https://github.com/KubeRiva/OMS/discussions) — we respond within hours.

---

## Local Development Setup

### Prerequisites

- Docker Desktop 4.x (Windows/Mac) or Docker Engine + Compose v2 (Linux)
- Python 3.12+ (for running tests outside Docker)
- Node.js 20+ (for frontend development)
- Git

### 1. Fork and clone

```bash
git clone https://github.com/YOUR_USERNAME/OMS.git
cd OMS
git remote add upstream https://github.com/KubeRiva/OMS.git
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` — the defaults work for local Docker Compose. **Generate new secrets** for the `SECRET_KEY`, `API_KEY`, and `WEBHOOK_SECRET` fields:

```bash
openssl rand -hex 32
```

Set `ANTHROPIC_API_KEY` only if you are testing the `AI_ADAPTIVE` sourcing strategy. The system falls back to `DISTANCE_OPTIMAL` if the key is absent.

### 3. Start all services

```bash
docker compose up --build
```

This starts: FastAPI (`:8001`), React frontend (`:3001`), PostgreSQL, MongoDB, Redis, Elasticsearch, Celery workers, Celery Beat, and Flower (`:5556`).

First startup takes 2-3 minutes while Elasticsearch initializes.

### 4. Seed demo data

```bash
docker compose exec api python scripts/seed.py
```

This creates 8 fulfillment nodes, 5 sourcing rules, 64 inventory items, 3 orders, and 8 products across all 4 databases.

### 5. Verify it works

- Frontend: http://localhost:3001 (login: `admin@example.com` / `admin123`)
- API docs: http://localhost:8001/docs
- Celery Flower: http://localhost:5556

### 6. Run tests

```bash
# From the repo root (outside Docker):
pip install -r requirements.txt
PYTHONPATH=. pytest tests/ -v

# Or inside the API container:
docker compose exec api pytest tests/ -v
```

---

## Project Structure

```
OMS/
├── app/
│   ├── main.py               # FastAPI app factory, lifespan, router registration
│   ├── config.py             # Pydantic Settings — every env var documented here
│   ├── database/             # Async engine factories (Postgres, Mongo, Redis, ES)
│   ├── models/postgres/      # SQLAlchemy ORM models
│   ├── schemas/              # Pydantic v2 request/response schemas
│   ├── routers/              # FastAPI routers (one file per domain)
│   ├── services/             # Business logic (sourcing engine, connectors, webhooks)
│   │   └── connectors/       # One file per platform connector
│   ├── workers/              # Celery task definitions (one file per queue)
│   ├── middleware/           # Request middleware (environment resolution, plan gating)
│   ├── dependencies/         # FastAPI dependencies (auth, environment context)
│   └── core/                 # Security utilities (JWT, password hashing)
├── frontend/
│   └── src/
│       ├── pages/            # One file per page/route
│       ├── components/       # Shared components (Layout, Modal, Badge, etc.)
│       ├── contexts/         # React contexts (Auth, Environment)
│       └── api/client.ts     # Typed Axios instance
├── scripts/                  # Seed and migration utilities
├── tests/                    # Pytest test suite
├── docker-compose.yml        # All services
└── Dockerfile                # Multi-stage Python 3.12 image
```

---

## Making Changes

### Branch naming

```
feat/short-description       # New features
fix/short-description        # Bug fixes
docs/short-description       # Documentation only
connector/platform-name      # New connector implementations
refactor/short-description   # Refactoring (no behavior change)
```

### Backend changes

- **Adding an endpoint**: add it to the relevant router in `app/routers/`. Add a corresponding Pydantic schema in `app/schemas/`. Register the router in `app/main.py` if it's a new router file.
- **Adding a model**: define it in the appropriate `app/models/postgres/` file. The schema migration runs automatically via `init_db()` on startup (uses `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` — no destructive DDL).
- **Adding a Celery task**: add it to the appropriate `app/workers/` file. Register it in `app/celery_app.py` if it needs a beat schedule. Use `asyncio.run()` wrappers for MongoDB access from sync Celery workers.
- **Adding a service**: add a file in `app/services/`. Keep business logic out of routers.

### Frontend changes

- Pages live in `frontend/src/pages/` — one file per route.
- Shared components go in `frontend/src/components/`.
- Use TanStack Query for all API calls. Use `refetchInterval: 5000` on detail pages that show live state.
- FastAPI 422 errors return `detail` as an array of `{loc, msg, type}` — always handle both string and array formats in error display.
- Use existing CSS utility classes: `btn-primary`, `btn-secondary`, `btn-danger`, `card`, `table-header`, `table-cell`, `input`, `select`, `label`.

### Database migrations

KubeRiva OMS does not use Alembic for runtime migrations. Schema changes use safe DDL only:

```python
# Correct — safe, idempotent
await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS platform_role VARCHAR(20)")

# Never do this in a migration
await conn.execute("DROP TABLE orders")
```

If your change requires a destructive migration, open an issue first to discuss the approach.

---

## Writing Tests

Tests live in `tests/`. We use `pytest` and `pytest-asyncio`.

- Every new router endpoint needs at least one test verifying the happy path and one verifying auth rejection.
- Every new Celery task needs at least one test verifying it runs without error against the test database.
- If your change adds a new sourcing strategy, add it to the strategy enum tests in `tests/test_imports.py`.

Run the full suite before submitting:

```bash
pytest tests/ -v
```

---

## Submitting a Pull Request

1. Make sure `pytest tests/ -v` passes with no errors.
2. Make sure `docker compose up --build` starts cleanly.
3. Fill in the PR template fully — incomplete PRs will be asked for more information.
4. Link the issue your PR addresses using `Closes #123` in the PR description.
5. Keep PRs focused on one concern. A bug fix and an unrelated refactor should be separate PRs.
6. PRs that add a new connector must include: schema registration, `BaseConnector` implementation, at least one test, and documentation in `README.md`'s connector table.

We review PRs within **5 business days**. If your PR hasn't been reviewed in that time, ping us in Discord #contributing.

---

## Building a Connector

KubeRiva's connector system is designed to be extended. To add a new platform connector:

1. Create `app/services/connectors/your_platform.py` implementing `BaseConnector` from `app/services/connectors/base.py`.

   Required methods:
   - `normalize_order(raw: dict) -> dict` — transforms platform order format to KubeRiva's internal schema
   - `push_fulfillment(order_id, tracking_number, carrier) -> bool` — sends shipment confirmation back to the platform
   - `validate_webhook(headers, body) -> bool` — verifies the request is authentic (HMAC, token, etc.)

2. Register it in `app/services/connectors/registry.py`:
   ```python
   ConnectorType.YOUR_PLATFORM: YourPlatformConnector
   ```

3. Add any new connector-specific environment variables to `.env.example` and `app/config.py`.

4. Add a row to the connector table in `README.md`.

5. Write tests in `tests/test_your_platform_connector.py`.

Open a [Connector Request issue](https://github.com/KubeRiva/OMS/issues/new?template=connector_request.yml) before starting work so we can confirm the interface and avoid duplication.

---

## Style Guide

### Python

- Follow PEP 8. Line length: 100 characters.
- Type annotations on all function signatures.
- Async functions for all I/O (database, HTTP, cache). Sync only in Celery task wrappers where `asyncio.run()` is explicitly used.
- No docstrings for internal functions — clear names are preferred. Short one-line comments only when the *why* is non-obvious.
- `from __future__ import annotations` at the top of files that use forward references.

### TypeScript / React

- Functional components only — no class components.
- Props interfaces defined inline above the component.
- `const` arrow functions for handlers; avoid inline arrow functions in JSX.
- Use `useQuery` / `useMutation` from TanStack Query for API calls — no raw `fetch` or `axios` calls in components.

---

## Getting Help

- **GitHub Discussions**: [github.com/KubeRiva/OMS/discussions](https://github.com/KubeRiva/OMS/discussions) — setup help, architecture questions, feature proposals, PR questions
- **GitHub Issues**: for bugs and confirmed feature requests only
