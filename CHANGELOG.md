# Changelog

All notable changes to KubeRiva OMS are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] — 2026-05-02 — Initial Open-Source Release

### Added

#### Core Order Management
- 15-state order lifecycle: `PENDING → CONFIRMED → SOURCING → SOURCED → PICKING → PACKING → READY_TO_SHIP → SHIPPED → OUT_FOR_DELIVERY → DELIVERED` plus `RETURNED`, `CANCELLED`, `REFUNDED`, `BACKORDERED`, `ON_HOLD`
- Full order CRUD via REST API with Pydantic v2 validation
- Multi-line-item orders with per-item fulfillment allocation
- Order cancellation with inventory reservation release
- MongoDB audit trail for every order event

#### Sourcing Engine
- **7 sourcing strategies**: `DISTANCE_OPTIMAL`, `COST_OPTIMAL`, `STORE_NEAREST`, `INVENTORY_RESERVATION`, `LEAST_COST_SPLIT`, `AI_ADAPTIVE`, `AI_HYBRID`
- Rule-based routing with 9 condition operators and priority ordering
- Haversine great-circle distance scoring for node selection
- Inventory reservation with automatic backorder retry (configurable interval and max age)
- A/B traffic splitting for strategy experiments (traffic_split_pct)

#### AI-Native Architecture
- `AI_ADAPTIVE` strategy — Claude Haiku scores each fulfillment node per order using delivery rate, cost score, backorder rate, and return rate; falls back to `DISTANCE_OPTIMAL` if samples < 10, score < 0.4, or API error
- `AI_HYBRID` strategy — blends rule-based and AI scoring with configurable weights
- AI learning workers: `label_sourcing_outcomes` (hourly), `discover_patterns` (nightly 02:00), `update_node_performance` (every 4h), `evaluate_ai_experiments` (daily 03:00)
- Pattern discovery with cluster key format `channel|region|amount_bucket|fulfillment_type`; thresholds: MIN_CLUSTER_SAMPLES=50, MIN_IMPROVEMENT_PCT=10%
- AIProposal lifecycle: `PENDING → APPROVED → APPLIED` (or `REJECTED / ROLLED_BACK`); human gate required; sourcing rules created with `is_active=False`
- Architect UI: Proposals, Patterns, Experiments, Performance dashboards

#### Multi-Tenant Architecture
- Control-plane PostgreSQL (`oms_db`) for organizations, environments, users
- Per-tenant data-plane PostgreSQL provisioned automatically on environment creation
- `EnvironmentMiddleware` resolves `X-OMS-Environment` header; Redis TTL 60s cache
- Three-tier platform role system: `PLATFORM_OWNER > SUPERADMIN > USER`
- Organization and environment CRUD via REST API

#### Inventory Management
- Multi-node inventory tracking (warehouse, store, dark store, dropship, virtual)
- Inventory adjustments with typed reasons: `RECEIVED`, `SOLD`, `RETURNED`, `DAMAGED`, `CYCLE_COUNT`, `TRANSFER_IN`, `TRANSFER_OUT`, `RESERVED`, `RESERVATION_RELEASED`, `CORRECTION`
- Inventory transfer between nodes
- Availability checks and low-stock alerts

#### Connector System
- **Shopify**: bidirectional — webhook inbound (HMAC-SHA256 validated) + fulfillment push
- **Amazon SP-API**: polling-based order sync + fulfillment push; Celery beat task every 15 min
- Connector framework: pluggable `BaseConnector` with `ConnectorRegistry`
- Planned: WooCommerce, Magento, BigCommerce, FedEx, UPS, DHL

#### Infrastructure
- FastAPI 0.111 + Python 3.12 + Pydantic v2 async-first backend
- PostgreSQL 16 (asyncpg) + MongoDB 7.0 (Motor) + Redis 7.2 (aioredis) + Elasticsearch 8.12
- Celery 5.4 with 7 queues: `sourcing`, `fulfillment`, `carrier`, `notifications`, `webhooks`, `connectors`, `learning`
- Celery Flower monitoring UI
- Prometheus metrics via `prometheus-fastapi-instrumentator`
- Structured JSON logging
- Docker Compose orchestration (9 services including optional ngrok tunnel)
- Multi-stage Dockerfiles for both API and frontend
- React 18 + TypeScript + Vite + TailwindCSS + TanStack Query v5 frontend
- Elasticsearch full-text search for orders and products
- HMAC-SHA256 signed outbound webhooks with exponential backoff retry

#### Developer Experience
- Seed script for all 4 databases (`scripts/seed.py`) with realistic demo data
- 41 E2E / UAT test cases (`e2ecases.md`) covering AUTH, ORDER, INVENTORY, ANALYTICS, SEARCH, AI, RBAC, SECURITY
- `tests/test_imports.py` — import validation + service instantiation tests
- Comprehensive `.env.example` with inline documentation for every variable

---

## Roadmap

See [GitHub Projects](https://github.com/KubeRiva/OMS/projects) for the public roadmap.

**v0.2 (planned)**
- WooCommerce connector
- Magento connector
- Kubernetes Helm chart
- OpenAPI SDK generation (Python, TypeScript, Go)
- GitHub Actions matrix tests (PostgreSQL 15/16, Python 3.11/3.12)

**v0.3 (planned)**
- FedEx, UPS, DHL carrier label generation
- Real-time order tracking webhooks
- Slack and email notification templates
- Rate shopping across carriers

**v1.0 (planned)**
- KubeRiva Cloud (managed hosting)
- Enterprise SSO (SAML, OIDC)
- SOC 2 Type II readiness documentation
