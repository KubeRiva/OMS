# Changelog

All notable changes to KubeRiva OMS are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] — 2026-05-09

### Added

- **Multi-Brand Support** — Brand entity with `B2C_ONLY` / `B2B_ONLY` / `HYBRID` tenant modes; `brand_id` foreign key on orders, sourcing rules, connectors, and customer accounts; brand filter applied across all UI list pages.
- **B2B Commerce** — Full business-to-business order workflow: `CustomerAccount` model with pricing tiers (STANDARD / BRONZE / SILVER / GOLD / PLATINUM), approval threshold gate, `PENDING_APPROVAL` order status, credit enforcement, NET-terms invoicing, and a dedicated B2B analytics dashboard.
- **Distribution Groups** — Named pools of fulfillment nodes that sourcing rules can target; member priority computed as `target_priority × 100 + member_priority`; fully brand-scopable.
- **API Key Authentication** — Machine-to-machine access via `X-API-Key: kr_...` header; keys stored as SHA-256 hashes; one-time plaintext reveal on creation; configurable scopes (`orders:read`, `orders:write`, `inventory:read`, etc.).
- **Brand-Scoped User Access** — `UserBrandRole` assignments restrict a user's visible orders and inventory to a single brand; roles: VIEWER / OPERATOR / ADMIN; IDOR protection enforced on all order and inventory list endpoints.
- **SLA Monitoring** — Per-lifecycle-step `sla_hours` configuration; `check_sla_breaches` Celery task runs every 15 minutes; breaches emit `order.sla_breach` audit events and increment a daily Redis counter; `GET /monitoring/sla-summary` returns today's breach count.
- **Lifecycle Engine Enhancements** — `pipeline_type` dimension (`ORDER` / `RETURN`) added to lifecycle scoping; `order_type` axis (`B2C` / `B2B`); `brand_id` scoping; specificity scoring formula: `brand_id(+8) + order_type(+4) + channel(+2) + fulfillment_type(+1)`.
- **Platform Owner Role** — Three-tier platform role system: `PLATFORM_OWNER` > `SUPERADMIN` > `USER`; `PATCH /admin/users/{id}/platform-role` endpoint; Platform Console UI (organizations, environments, user role management) visible to Platform Owners only.
- **Node CRUD UI** — Create, edit, and delete fulfillment nodes directly from the Nodes page; form surfaces all node properties including capability flags and capacity; API validation errors mapped inline to form fields.
- **End-to-End Test Suite** — 66 server-side tests across 14 groups covering the full order lifecycle; automatic resource cleanup in `finally` blocks; results streamed via `POST /ops/run-e2e-tests` and persisted to `e2ecases.md`.

### Changed

- Sourcing engine cluster key format extended to include `brand_slug` prefix: `brand_slug|channel|region|amount_bucket|fulfillment_type` (unbranded orders use `"default"`).
- JWT token payload now includes `platform_role` field; `is_superadmin` derived from role for backward compatibility.
- Connector `normalize_order()` automatically stamps `brand_id` on inbound orders when the connector has a brand configured.
- `GET /distribution-groups/` accepts `brand_id` filter; sourcing rules accept `sourcing_targets` referencing group IDs.

### Fixed

- Shopify App Bridge v4 TypeScript build errors resolved by replacing deprecated `app-bridge-react` imports with direct `window.shopify.idToken()` session token retrieval.
- Shopify OAuth validates the shop hostname with a strict regex before any API key check, preventing open-redirect on malformed `shop` parameters.
- Shopify billing plans endpoint returns an array (not an object map) with correct field names matching the Billing API schema.

---

## [0.1.0] — 2026-03-23

### Added

- **Core OMS** — FastAPI + SQLAlchemy async backend with PostgreSQL, MongoDB, Redis, and Elasticsearch.
- **Order management** — Full order lifecycle state machine (15 statuses); multi-line-item orders; split fulfillment allocations.
- **Inventory management** — Per-node, per-SKU stock with soft reservations; adjustment audit log; bulk availability check; inter-node transfer.
- **Fulfillment nodes** — CRUD for distribution centers, retail stores, dark stores, and pickup points with capability flags.
- **Sourcing rules engine** — 7 strategies (DISTANCE_OPTIMAL, COST_OPTIMAL, STORE_NEAREST, INVENTORY_RESERVATION, LEAST_COST_SPLIT, AI_ADAPTIVE, AI_HYBRID); priority-ordered rule evaluation with condition DSL.
- **AI-native architecture** — KubeAI-powered node scoring; pattern discovery; A/B experiment framework; human-gated AI proposals.
- **Webhook system** — HMAC-SHA256 signed outbound webhooks with exponential-backoff retry.
- **Connector system** — Pluggable integration framework; Shopify bidirectional and Amazon SP-API polling connectors live.
- **Celery workers** — 7 named queues: sourcing, fulfillment, carrier, notifications, webhooks, connectors, learning.
- **Full-text search** — Elasticsearch-backed order and product search.
- **Analytics** — Dashboard KPIs, daily order volume, inventory health summary.
- **React frontend** — TypeScript + Vite + TailwindCSS; pages for orders, inventory, nodes, sourcing rules, connectors, analytics, and AI architect console.
- **Docker Compose** — One-command local stack (8 services).

[0.2.0]: https://github.com/KubeRiva/OMS/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/KubeRiva/OMS/releases/tag/v0.1.0
