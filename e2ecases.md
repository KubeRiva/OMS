# KubeRiva OMS — Comprehensive End-to-End Test Plan

**System**: KubeRiva OMS (AI-native, multi-brand, multi-tenant Order Management System)
**Version**: feature/shopify-app-store branch
**Author**: QA Engineering / API Tester
**Date**: 2026-05-07
**Base URL**: `http://localhost:3001` (nginx proxy) | API at `/api/` proxied to `localhost:8001`
**Auth**: `POST /api/auth/login` body `{"email":"admin@example.com","password":"admin123"}` returns `{access_token}`. All subsequent requests require `Authorization: Bearer <TOKEN>`.

> **How to read this document**: Steps labelled with an HTTP method use the nginx proxy URL `http://localhost:3001/api/...`. Replace all placeholder values (e.g. `{brand_a_id}`) with the actual UUIDs captured during the Test Data Setup section. All requests to protected endpoints include `Authorization: Bearer <TOKEN>` unless stated otherwise.

---

## Table of Contents

1. [Test Data Setup](#test-data-setup)
2. [Smoke Test Sequence](#smoke-test-sequence)
3. [Data Integrity Checklist](#data-integrity-checklist)
4. [TC-BRAND — Brand Entity CRUD and Configuration](#tc-brand--brand-entity-crud-and-configuration)
5. [TC-B2C — B2C Order Flows](#tc-b2c--b2c-order-flows)
6. [TC-B2B — B2B Order Flows](#tc-b2b--b2b-order-flows)
7. [TC-ISO — Multi-Brand Data Isolation](#tc-iso--multi-brand-data-isolation)
8. [TC-AI — AI-Native Sourcing](#tc-ai--ai-native-sourcing)
9. [TC-INV — Inventory and Node Management](#tc-inv--inventory-and-node-management)
10. [TC-PLAT — Platform and RBAC](#tc-plat--platform-and-rbac)
11. [TC-CONN — Connectors](#tc-conn--connectors)
12. [TC-SRCH — Search and Monitoring](#tc-srch--search-and-monitoring)
13. [TC-AUDIT — Data Integrity and Audit Trail](#tc-audit--data-integrity-and-audit-trail)
14. [Appendix A — HTTP Status Code Reference](#appendix-a--http-status-code-reference)
15. [Appendix B — Enum Quick Reference](#appendix-b--enum-quick-reference)
16. [Appendix C — Test Case Count Summary](#appendix-c--test-case-count-summary)

---

## Test Data Setup

Execute these API calls in order before running any test cases. Capture each returned UUID and store it in a local variable file (e.g. `test_vars.env`) for reuse throughout the suite.

### Step 0 — Authenticate and Obtain Superadmin Token

```
POST /api/auth/login
Content-Type: application/json

{
  "email": "admin@example.com",
  "password": "admin123"
}
```

Expected: `200 OK`. Body: `{"access_token": "<TOKEN>", "token_type": "bearer"}`.
Store `<TOKEN>` as `SUPERADMIN_TOKEN`. All setup steps below use this token.

---

### Step 1 — Create Fulfillment Nodes

**Node A — East Coast Distribution Center (ships to home, no pickup)**

```
POST /api/nodes/
Authorization: Bearer <SUPERADMIN_TOKEN>
Content-Type: application/json

{
  "code": "DC-EAST-001",
  "name": "East Coast Distribution Center",
  "node_type": "DISTRIBUTION_CENTER",
  "address_line1": "100 Logistics Blvd",
  "city": "Newark",
  "state": "NJ",
  "postal_code": "07102",
  "country": "US",
  "latitude": 40.7357,
  "longitude": -74.1724,
  "can_ship": true,
  "can_pickup": false,
  "can_curbside": false,
  "can_same_day": false,
  "daily_order_capacity": 1000
}
```

Store returned `id` as `NODE_EAST_ID`.

**Node B — West Coast Distribution Center**

```
POST /api/nodes/
Authorization: Bearer <SUPERADMIN_TOKEN>
Content-Type: application/json

{
  "code": "DC-WEST-001",
  "name": "West Coast Distribution Center",
  "node_type": "DISTRIBUTION_CENTER",
  "address_line1": "200 Fulfillment Way",
  "city": "Los Angeles",
  "state": "CA",
  "postal_code": "90001",
  "country": "US",
  "latitude": 34.0522,
  "longitude": -118.2437,
  "can_ship": true,
  "can_pickup": false,
  "can_curbside": false,
  "can_same_day": true,
  "daily_order_capacity": 800
}
```

Store returned `id` as `NODE_WEST_ID`.

**Node C — NYC Retail Store (pickup capable)**

```
POST /api/nodes/
Authorization: Bearer <SUPERADMIN_TOKEN>
Content-Type: application/json

{
  "code": "STORE-NYC-001",
  "name": "NYC Flagship Store",
  "node_type": "RETAIL_STORE",
  "address_line1": "500 5th Avenue",
  "city": "New York",
  "state": "NY",
  "postal_code": "10110",
  "country": "US",
  "latitude": 40.7549,
  "longitude": -73.9840,
  "can_ship": false,
  "can_pickup": true,
  "can_curbside": true,
  "can_same_day": false,
  "daily_order_capacity": 100
}
```

Store returned `id` as `NODE_STORE_ID`.

---

### Step 2 — Create Brands

**Brand Alpha — HYBRID tenant mode (supports both B2C and B2B)**

```
POST /api/brands/
Authorization: Bearer <SUPERADMIN_TOKEN>
Content-Type: application/json

{
  "slug": "brand-alpha",
  "name": "Brand Alpha",
  "tenant_mode": "HYBRID",
  "description": "Primary test brand for B2C and B2B flows"
}
```

Store returned `id` as `BRAND_A_ID`.

**Brand Beta — B2C_ONLY tenant mode**

```
POST /api/brands/
Authorization: Bearer <SUPERADMIN_TOKEN>
Content-Type: application/json

{
  "slug": "brand-beta",
  "name": "Brand Beta",
  "tenant_mode": "B2C_ONLY",
  "description": "Secondary test brand for isolation tests"
}
```

Store returned `id` as `BRAND_B_ID`.

---

### Step 3 — Seed Inventory

**SKU-WIDGET-001 at East DC (200 units)**

```
POST /api/inventory/
Authorization: Bearer <SUPERADMIN_TOKEN>
Content-Type: application/json

{
  "node_id": "<NODE_EAST_ID>",
  "sku": "SKU-WIDGET-001",
  "product_name": "Test Widget Blue",
  "quantity_on_hand": 200,
  "reorder_point": 20,
  "reorder_quantity": 100,
  "unit_cost": 15.00
}
```

**SKU-WIDGET-001 at West DC (150 units)**

```
POST /api/inventory/
Authorization: Bearer <SUPERADMIN_TOKEN>
Content-Type: application/json

{
  "node_id": "<NODE_WEST_ID>",
  "sku": "SKU-WIDGET-001",
  "product_name": "Test Widget Blue",
  "quantity_on_hand": 150,
  "reorder_point": 20,
  "reorder_quantity": 100,
  "unit_cost": 15.00
}
```

**SKU-GADGET-002 at East DC (50 units)**

```
POST /api/inventory/
Authorization: Bearer <SUPERADMIN_TOKEN>
Content-Type: application/json

{
  "node_id": "<NODE_EAST_ID>",
  "sku": "SKU-GADGET-002",
  "product_name": "Test Gadget Pro",
  "quantity_on_hand": 50,
  "reorder_point": 10,
  "reorder_quantity": 50,
  "unit_cost": 89.99
}
```

**SKU-RARE-003 at West DC (3 units — deliberately below reorder_point for low-stock tests)**

```
POST /api/inventory/
Authorization: Bearer <SUPERADMIN_TOKEN>
Content-Type: application/json

{
  "node_id": "<NODE_WEST_ID>",
  "sku": "SKU-RARE-003",
  "product_name": "Rare Collector Item",
  "quantity_on_hand": 3,
  "reorder_point": 10,
  "reorder_quantity": 50,
  "unit_cost": 299.00
}
```

---

### Step 4 — Create Sourcing Rules

**Rule 1 — WEB channel uses DISTANCE_OPTIMAL (priority 10 = highest)**

```
POST /api/sourcing-rules/
Authorization: Bearer <SUPERADMIN_TOKEN>
Content-Type: application/json

{
  "name": "Web Orders Distance Optimal",
  "priority": 10,
  "is_active": true,
  "strategy": "DISTANCE_OPTIMAL",
  "conditions": [
    {"field": "channel", "operator": "EQUALS", "value": "WEB"}
  ],
  "max_split_nodes": 2,
  "created_by": "test-setup"
}
```

Store returned `id` as `RULE_WEB_ID`.

**Rule 2 — B2B channel uses COST_OPTIMAL (priority 20)**

```
POST /api/sourcing-rules/
Authorization: Bearer <SUPERADMIN_TOKEN>
Content-Type: application/json

{
  "name": "B2B Orders Cost Optimal",
  "priority": 20,
  "is_active": true,
  "strategy": "COST_OPTIMAL",
  "conditions": [
    {"field": "channel", "operator": "EQUALS", "value": "B2B"}
  ],
  "max_split_nodes": 3,
  "created_by": "test-setup"
}
```

Store returned `id` as `RULE_B2B_ID`.

---

### Step 5 — Create B2B Customer Accounts

**Account 1 — Acme Corp: ACTIVE, credit limit $50K, approval threshold $10K, NET_30, Brand Alpha**

```
POST /api/customers/
Authorization: Bearer <SUPERADMIN_TOKEN>
Content-Type: application/json

{
  "company_name": "Acme Corp",
  "trading_name": "Acme",
  "account_type": "ACTIVE",
  "contact_name": "Jane Buyer",
  "contact_email": "jane@acme.com",
  "contact_phone": "+1-555-0100",
  "credit_limit": "50000.00",
  "payment_terms": "NET_30",
  "pricing_tier": "GOLD",
  "approval_threshold": "10000.00",
  "brand_id": "<BRAND_A_ID>",
  "billing_address1": "100 Corp Lane",
  "billing_city": "Chicago",
  "billing_state": "IL",
  "billing_postal_code": "60601",
  "billing_country": "US"
}
```

Store returned `id` as `ACCOUNT_ACME_ID` and `account_number` as `ACCOUNT_ACME_NUMBER`.

**Account 2 — Startup LLC: PROSPECT, no credit, Brand Alpha**

```
POST /api/customers/
Authorization: Bearer <SUPERADMIN_TOKEN>
Content-Type: application/json

{
  "company_name": "Startup LLC",
  "account_type": "PROSPECT",
  "contact_name": "Bob Prospect",
  "contact_email": "bob@startup.com",
  "credit_limit": "0.00",
  "payment_terms": "PREPAID",
  "pricing_tier": "STANDARD",
  "brand_id": "<BRAND_A_ID>"
}
```

Store returned `id` as `ACCOUNT_STARTUP_ID`.

---

### Step 6 — Create a Shopify Connector

```
POST /api/connectors/
Authorization: Bearer <SUPERADMIN_TOKEN>
Content-Type: application/json

{
  "name": "Shopify Test Store",
  "connector_type": "SHOPIFY",
  "direction": "BIDIRECTIONAL",
  "config": {
    "shop_domain": "test-store.myshopify.com",
    "api_key": "test_api_key_placeholder",
    "api_secret": "test_secret_placeholder",
    "webhook_secret": "test_webhook_secret_32chars_ok"
  }
}
```

Store returned `id` as `CONNECTOR_SHOPIFY_ID`.

---

## Smoke Test Sequence

Run these 5 tests first. If any one fails, stop and fix the environment before proceeding to the full suite.

| # | Test ID | What it confirms |
|---|---------|-----------------|
| 1 | TC-BRAND-001 | API reachable, authentication works, brand creation succeeds |
| 2 | TC-INV-001 | Inventory reads and adjustments function correctly |
| 3 | TC-B2C-001 | Core order creation and basic order lifecycle work end-to-end |
| 4 | TC-PLAT-001 | RBAC enforcement active — unauthenticated requests are rejected |
| 5 | TC-AUDIT-001 | MongoDB audit trail is operational and records order.created events |

---

## Data Integrity Checklist

Verify these invariants after every test run. None of these should ever be violated in a healthy system.

- [ ] **Inventory balance**: For every `inventory_items` row, `quantity_available = quantity_on_hand - quantity_reserved`. No negative values in `quantity_on_hand`, `quantity_reserved`, or `quantity_available`.
- [ ] **Allocation sum equals reserved**: For every `(node_id, sku)` pair, `inventory_items.quantity_reserved` equals the sum of `fulfillment_allocations.quantity_allocated` for allocations in status `ALLOCATED`, `PICKING`, `PACKING`, or `READY_TO_SHIP` at that node for that sku.
- [ ] **No orphan allocations**: Every `fulfillment_allocations.node_id` references an existing `fulfillment_nodes.id`. Every `fulfillment_allocations.order_id` references an existing `orders.id`.
- [ ] **Cancelled orders have no active allocations**: Any order with `status = CANCELLED` must have all its allocations in `CANCELLED` or `RELEASED` status — none in `ALLOCATED`, `PICKING`, `PACKING`, or `READY_TO_SHIP`.
- [ ] **B2B approval gate**: Any order where `total_amount > customer_account.approval_threshold` at time of creation must have `approval_status` in `('PENDING', 'APPROVED', 'REJECTED')` — never `NOT_REQUIRED`.
- [ ] **Credit used never exceeds credit limit**: `customer_accounts.credit_used <= customer_accounts.credit_limit` for all rows at all times.
- [ ] **Brand slug is immutable**: The `brands.slug` value set at creation must equal the slug returned by all subsequent GET calls for that brand record.
- [ ] **Order audit trail completeness**: Every `orders` row must have at least one `order_events` document in MongoDB with `event_type = "order.created"` and matching `order_id`.
- [ ] **Isolated inventory brand_id**: For any brand using `inventory_mode = ISOLATED`, every `inventory_items` row allocated to an order under that brand must carry `brand_id` equal to that brand's UUID.
- [ ] **Account number uniqueness per brand**: The unique constraint `uq_account_number_brand` (on `account_number`, `brand_id`) must not be violated. Two accounts under different brands may share a company_name but never the same account_number within the same brand.
- [ ] **Node code uniqueness**: No two `fulfillment_nodes` rows share the same `code` value.
- [ ] **Sourcing priority ordering**: When multiple active rules match an order, only the rule with the numerically lowest `priority` value applies. Verify `order.sourced` event data includes `matched_rule_id` pointing to the highest-priority rule.
- [ ] **Payment due date alignment**: Orders with `payment_terms = NET_30` have `payment_due_date = confirmed_at + 30 days`. Orders with `payment_terms = PREPAID` have `payment_due_date = NULL`.
- [ ] **Elasticsearch index consistency**: For every order in PostgreSQL with `status != CANCELLED` and `created_at` within the last 30 days, a corresponding document exists in the Elasticsearch `orders` index with the same `id`, `status`, and `customer_email`.

---

## TC-BRAND — Brand Entity CRUD and Configuration

### TC-BRAND-001

**Priority**: P0
**Feature**: Brand CRUD
**Title**: Create a brand with valid slug and verify correct response defaults

**Prerequisites**: Superadmin token obtained from Test Data Setup Step 0.

**Steps**:

1. Send `POST /api/brands/` with body:
   ```json
   {
     "slug": "smoke-brand",
     "name": "Smoke Test Brand",
     "tenant_mode": "HYBRID"
   }
   ```
2. Copy the `id` from step 1 response and send `GET /api/brands/{id}`.

**Expected Result**:
- Step 1: `201 Created`. Body contains `slug = "smoke-brand"`, `name = "Smoke Test Brand"`, `tenant_mode = "HYBRID"`, `is_active = true`, `order_count = 0`, `rule_count = 0`, `account_count = 0`. Fields `created_at` and `updated_at` are present ISO-8601 timestamps.
- Step 2: `200 OK`. All same fields confirmed. No extra fields beyond the `BrandResponse` schema.

**Data Integrity Check**: `SELECT slug, name, tenant_mode, is_active FROM brands WHERE slug = 'smoke-brand'` returns exactly one row with the expected values.

---

### TC-BRAND-002

**Priority**: P1
**Feature**: Brand CRUD — slug collision
**Title**: Creating a brand with a duplicate slug returns 409 Conflict and no row is inserted

**Prerequisites**: Brand with slug `brand-alpha` exists (created in Test Data Setup Step 2).

**Steps**:

1. Send `POST /api/brands/` with body:
   ```json
   {
     "slug": "brand-alpha",
     "name": "Duplicate Brand Attempt",
     "tenant_mode": "B2C_ONLY"
   }
   ```

**Expected Result**: `409 Conflict`. Response `detail` field contains the text `"already exists"` and references the slug `brand-alpha`. The HTTP body is not `201`.

**Data Integrity Check**: `SELECT COUNT(*) FROM brands WHERE slug = 'brand-alpha'` returns exactly `1` — no duplicate row inserted.

---

### TC-BRAND-003

**Priority**: P1
**Feature**: Brand CRUD — slug immutability
**Title**: PATCH brand updates name and description but slug remains unchanged

**Prerequisites**: `BRAND_A_ID` exists with `slug = "brand-alpha"`.

**Steps**:

1. Send `PATCH /api/brands/<BRAND_A_ID>` with body:
   ```json
   {
     "name": "Brand Alpha Renamed",
     "slug": "brand-alpha-changed"
   }
   ```
2. Send `GET /api/brands/<BRAND_A_ID>`.

**Expected Result**:
- Step 1: `200 OK`. Response shows `name = "Brand Alpha Renamed"`.
- Step 2: `slug` is still `"brand-alpha"`. The `BrandUpdate` schema excludes `slug`, so the field is silently ignored even when supplied.

**Data Integrity Check**: `SELECT slug FROM brands WHERE id = '<BRAND_A_ID>'` returns `brand-alpha` (unchanged).

---

### TC-BRAND-004

**Priority**: P1
**Feature**: Brand toggle active/inactive
**Title**: Toggling a brand flips is_active and toggle again restores it

**Prerequisites**: Create a dedicated disposable brand for this test.

**Steps**:

1. Send `POST /api/brands/` with body `{"slug": "tc-brand-004", "name": "Toggle Test Brand", "tenant_mode": "HYBRID"}`. Store returned `id` as `BRAND_004_ID`.
2. Send `POST /api/brands/<BRAND_004_ID>/toggle`.
3. Send `GET /api/brands/<BRAND_004_ID>`.
4. Send `POST /api/brands/<BRAND_004_ID>/toggle` again.
5. Send `GET /api/brands/<BRAND_004_ID>`.

**Expected Result**:
- Step 2: `200 OK`, `is_active = false`.
- Step 3: `is_active = false` confirmed.
- Step 4: `200 OK`, `is_active = true`.
- Step 5: `is_active = true` confirmed.

**Data Integrity Check**: `SELECT is_active, updated_at FROM brands WHERE id = '<BRAND_004_ID>'` — `updated_at` advances each time toggle is called.

---

### TC-BRAND-005

**Priority**: P1
**Feature**: Brand delete guard
**Title**: Deleting a brand that has linked orders, rules, or accounts returns 409 Conflict

**Prerequisites**: `BRAND_A_ID` has at least one order linked (created in TC-B2C-001). At least one sourcing rule and one customer account also reference this brand from Test Data Setup.

**Steps**:

1. Send `DELETE /api/brands/<BRAND_A_ID>`.

**Expected Result**: `409 Conflict`. Response `detail` mentions the count of linked orders, sourcing rules, and/or customer accounts preventing deletion (e.g. `"Cannot delete brand 'brand-alpha': N order(s), M sourcing rule(s), K customer account(s) are linked to it."`). Brand still exists.

**Data Integrity Check**: `SELECT COUNT(*) FROM brands WHERE id = '<BRAND_A_ID>'` returns `1`. No cascade delete occurred.

---

## TC-B2C — B2C Order Flows

### TC-B2C-001

**Priority**: P0
**Feature**: B2C order creation
**Title**: Create a basic B2C WEB SHIP_TO_HOME order and verify initial state, totals, and audit event

**Prerequisites**: `BRAND_A_ID` and `NODE_EAST_ID` exist. `SKU-WIDGET-001` inventory seeded at East DC with at least 10 units available.

**Steps**:

1. Send `POST /api/orders/` with body:
   ```json
   {
     "channel": "WEB",
     "order_type": "RETAIL",
     "fulfillment_type": "SHIP_TO_HOME",
     "customer_email": "alice@example.com",
     "customer_name": "Alice Smith",
     "brand_id": "<BRAND_A_ID>",
     "line_items": [
       {
         "sku": "SKU-WIDGET-001",
         "product_name": "Test Widget Blue",
         "quantity": 2,
         "unit_price": "29.99",
         "tax_amount": "2.40"
       }
     ],
     "shipping_address": {
       "name": "Alice Smith",
       "address1": "123 Main St",
       "city": "Boston",
       "state": "MA",
       "postal_code": "02101",
       "country": "US"
     },
     "shipping_amount": "5.99",
     "currency": "USD"
   }
   ```
   Store returned `id` as `ORDER_B2C_BASIC_ID` and `order_number` as `ORDER_B2C_BASIC_NUMBER`.
2. Send `GET /api/orders/<ORDER_B2C_BASIC_ID>`.
3. Send `GET /api/orders/<ORDER_B2C_BASIC_ID>/events`.

**Expected Result**:
- Step 1: `201 Created`. `status = "CONFIRMED"`. `order_number` matches regex `ORD-\d{8}-[A-Z0-9]{6}`. `approval_status = "NOT_REQUIRED"`. Financial fields: `subtotal = 59.98` ((29.99 * 2) - 0 discount), `tax_amount = 4.80` (2.40 * 2), `shipping_amount = 5.99`, `total_amount = 70.77` (59.98 + 4.80 + 5.99 - 0). `currency = "USD"`. `brand_id` equals `BRAND_A_ID`.
- Step 2: `200 OK`. `line_items` array has 1 entry with `sku = "SKU-WIDGET-001"`, `quantity = 2`.
- Step 3: JSON array. At least one event has `event_type = "order.created"` with `data.order_number`, `data.channel = "WEB"`, `data.total_amount = 70.77`, `data.approval_status = "NOT_REQUIRED"`.

**Data Integrity Check**: PostgreSQL `SELECT subtotal, tax_amount, total_amount FROM orders WHERE id = '<ORDER_B2C_BASIC_ID>'` matches the calculated values. MongoDB `order_events` has one document with `event_type = "order.created"` for this `order_id`.

---

### TC-B2C-002

**Priority**: P1
**Feature**: B2C order — input validation
**Title**: Order creation with an empty line_items array is rejected with 422

**Prerequisites**: Superadmin token.

**Steps**:

1. Send `POST /api/orders/` with body:
   ```json
   {
     "channel": "WEB",
     "order_type": "RETAIL",
     "fulfillment_type": "SHIP_TO_HOME",
     "customer_email": "badorder@example.com",
     "line_items": []
   }
   ```

**Expected Result**: `422 Unprocessable Entity`. The response `detail` field is an array containing at least one object with `loc` referencing `line_items` and a message about minimum length or the custom validator `"Order must have at least one line item"`. No order is created.

**Data Integrity Check**: `SELECT COUNT(*) FROM orders WHERE customer_email = 'badorder@example.com'` returns `0`.

---

### TC-B2C-003

**Priority**: P1
**Feature**: B2C order — status progression
**Title**: Manually advance order status CONFIRMED -> SOURCING -> SOURCED -> PICKING and verify audit events at each step

**Prerequisites**: `ORDER_B2C_BASIC_ID` created in TC-B2C-001 at `status = CONFIRMED`.

**Steps**:

1. Send `PATCH /api/orders/<ORDER_B2C_BASIC_ID>/status` with body `{"status": "SOURCING"}`.
2. Send `PATCH /api/orders/<ORDER_B2C_BASIC_ID>/status` with body `{"status": "SOURCED"}`.
3. Send `PATCH /api/orders/<ORDER_B2C_BASIC_ID>/status` with body `{"status": "PICKING"}`.
4. Send `GET /api/orders/<ORDER_B2C_BASIC_ID>/events`.

**Expected Result**:
- Steps 1-3: Each returns `200 OK` with the updated `status` value in the body.
- Step 4: Array contains events with `event_type` values `order.sourcing`, `order.sourced`, `order.picking` (plus the earlier `order.created`). Each event has `timestamp` (ISO-8601) and `data.old_status`, `data.new_status`.

**Data Integrity Check**: MongoDB `order_events` for this `order_id` now has exactly 4 documents: `order.created`, `order.sourcing`, `order.sourced`, `order.picking`. Order in `orders` table has `status = 'PICKING'`.

---

### TC-B2C-004

**Priority**: P1
**Feature**: B2C order — full lifecycle through to SHIPPED
**Title**: Complete order from PICKING through PACKING, READY_TO_SHIP, to SHIPPED; verify status and audit

**Prerequisites**: `ORDER_B2C_BASIC_ID` at `status = PICKING` from TC-B2C-003.

**Steps**:

1. Send `PATCH /api/orders/<ORDER_B2C_BASIC_ID>/status` with body `{"status": "PACKING"}`.
2. Send `PATCH /api/orders/<ORDER_B2C_BASIC_ID>/status` with body `{"status": "READY_TO_SHIP"}`.
3. Send `PATCH /api/orders/<ORDER_B2C_BASIC_ID>/status` with body `{"status": "SHIPPED", "notes": "Shipped via UPS tracking 1Z999AA10123456784"}`.
4. Send `GET /api/orders/<ORDER_B2C_BASIC_ID>`.

**Expected Result**:
- Steps 1-3: Each returns `200 OK` with updated `status`.
- Step 4: `status = "SHIPPED"`. `notes` field contains the UPS note from step 3.

**Data Integrity Check**: MongoDB `order_events` has `order.shipped` event with `data.old_status = "READY_TO_SHIP"`. `orders.updated_at` is more recent than `orders.confirmed_at`.

---

### TC-B2C-005

**Priority**: P1
**Feature**: B2C order — cancellation guards
**Title**: SHIPPED order cannot be cancelled; CONFIRMED order can be cancelled

**Prerequisites**: `ORDER_B2C_BASIC_ID` at `status = SHIPPED` (after TC-B2C-004). Create a second fresh order via TC-B2C-001 body; store its `id` as `ORDER_TO_CANCEL_ID` (at `CONFIRMED` status).

**Steps**:

1. Send `POST /api/orders/<ORDER_B2C_BASIC_ID>/cancel` with body `{"reason": "Attempted cancel of shipped order", "notify_customer": false}`.
2. Send `POST /api/orders/<ORDER_TO_CANCEL_ID>/cancel` with body `{"reason": "Customer changed mind", "notify_customer": true}`.
3. Send `GET /api/orders/<ORDER_TO_CANCEL_ID>`.

**Expected Result**:
- Step 1: `400 Bad Request`. Detail mentions `SHIPPED` cannot be cancelled.
- Step 2: `200 OK`. Body shows `status = "CANCELLED"`. `notes` contains `"Cancelled: Customer changed mind"`. `cancelled_at` is populated.
- Step 3: Confirmed — `status = "CANCELLED"`, `cancelled_at` is a recent timestamp.

**Data Integrity Check**: MongoDB `order_events` has `order.cancelled` event for `ORDER_TO_CANCEL_ID`. No `order.cancelled` event for `ORDER_B2C_BASIC_ID` (still at SHIPPED).

---

### TC-B2C-006

**Priority**: P1
**Feature**: B2C order — store pickup fulfillment type
**Title**: Create a STORE_PICKUP order with pickup_node_id and verify the node is recorded

**Prerequisites**: `NODE_STORE_ID` exists with `can_pickup = true`. `BRAND_A_ID` exists.

**Steps**:

1. Send `POST /api/orders/` with body:
   ```json
   {
     "channel": "WEB",
     "order_type": "RETAIL",
     "fulfillment_type": "STORE_PICKUP",
     "customer_email": "pickup@example.com",
     "customer_name": "Pick Up Person",
     "brand_id": "<BRAND_A_ID>",
     "pickup_node_id": "<NODE_STORE_ID>",
     "line_items": [
       {
         "sku": "SKU-WIDGET-001",
         "product_name": "Test Widget Blue",
         "quantity": 1,
         "unit_price": "29.99"
       }
     ],
     "shipping_amount": "0.00"
   }
   ```
2. Send `GET /api/orders/{id}` using the id from step 1.

**Expected Result**:
- Step 1: `201 Created`. `fulfillment_type = "STORE_PICKUP"`. `pickup_node_id` equals `NODE_STORE_ID`. `shipping_amount = 0.00`.
- Step 2: `200 OK`. Same fields confirmed. `status = "CONFIRMED"`.

**Data Integrity Check**: `SELECT pickup_node_id FROM orders WHERE id = '<returned_id>'` matches `NODE_STORE_ID`.

---

### TC-B2C-007

**Priority**: P1
**Feature**: B2C order — multi-item order
**Title**: Create order with two different SKUs and verify subtotal and tax aggregation

**Prerequisites**: `SKU-WIDGET-001` and `SKU-GADGET-002` seeded. `BRAND_A_ID` exists.

**Steps**:

1. Send `POST /api/orders/` with body:
   ```json
   {
     "channel": "MOBILE",
     "order_type": "RETAIL",
     "fulfillment_type": "SHIP_TO_HOME",
     "customer_email": "multiitem@example.com",
     "customer_name": "Multi Item Buyer",
     "brand_id": "<BRAND_A_ID>",
     "line_items": [
       {
         "sku": "SKU-WIDGET-001",
         "product_name": "Test Widget Blue",
         "quantity": 3,
         "unit_price": "29.99",
         "discount_amount": "5.00",
         "tax_amount": "2.40"
       },
       {
         "sku": "SKU-GADGET-002",
         "product_name": "Test Gadget Pro",
         "quantity": 1,
         "unit_price": "89.99",
         "tax_amount": "7.20"
       }
     ],
     "shipping_amount": "9.99",
     "discount_amount": "10.00"
   }
   ```

**Expected Result**: `201 Created`. `line_items` array has 2 entries.
- Item 1 subtotal contribution: (29.99 * 3) - 5.00 = 84.97. Item 1 tax: 2.40 * 3 = 7.20.
- Item 2 subtotal contribution: 89.99 * 1 = 89.99. Item 2 tax: 7.20 * 1 = 7.20.
- Order `subtotal = 174.96`. `tax_amount = 14.40`. `shipping_amount = 9.99`. `discount_amount = 10.00`.
- `total_amount = 174.96 + 14.40 + 9.99 - 10.00 = 189.35`.

**Data Integrity Check**: `SELECT subtotal, tax_amount, total_amount FROM orders WHERE customer_email = 'multiitem@example.com' ORDER BY created_at DESC LIMIT 1` confirms the values. `SELECT COUNT(*) FROM order_items WHERE order_id = '<returned_id>'` returns `2`.

---

### TC-B2C-008

**Priority**: P1
**Feature**: B2C order — returns
**Title**: Advance a DELIVERED order to RETURNED status and verify audit event

**Prerequisites**: Create a fresh order and advance it to `DELIVERED` status (follow TC-B2C-001 through TC-B2C-004, then `PATCH status = "DELIVERED"`). Store id as `ORDER_DELIVERED_ID`.

**Steps**:

1. Send `PATCH /api/orders/<ORDER_DELIVERED_ID>/status` with body `{"status": "RETURNED", "notes": "Customer return — defective unit"}`.
2. Send `GET /api/orders/<ORDER_DELIVERED_ID>/events`.

**Expected Result**:
- Step 1: `200 OK`. `status = "RETURNED"`.
- Step 2: Events list includes an event with `event_type = "order.returned"` and `data.old_status = "DELIVERED"`, `data.new_status = "RETURNED"`.

**Data Integrity Check**: `SELECT status FROM orders WHERE id = '<ORDER_DELIVERED_ID>'` returns `RETURNED`. MongoDB `order_events` has `order.returned` document.

---

## TC-B2B — B2B Order Flows

### TC-B2B-001

**Priority**: P0
**Feature**: B2B — customer account creation
**Title**: Create an ACTIVE B2B customer account with credit limit and verify auto-generated account number format

**Prerequisites**: `BRAND_A_ID` exists. Superadmin token.

**Steps**:

1. Send `POST /api/customers/` with body:
   ```json
   {
     "company_name": "Global Widgets Inc",
     "account_type": "ACTIVE",
     "contact_name": "CEO Person",
     "contact_email": "ceo@globalwidgets.com",
     "credit_limit": "25000.00",
     "payment_terms": "NET_60",
     "pricing_tier": "SILVER",
     "approval_threshold": "5000.00",
     "brand_id": "<BRAND_A_ID>"
   }
   ```
2. Send `GET /api/customers/{id}` using the id from step 1.

**Expected Result**:
- Step 1: `201 Created`. `account_number` matches regex `ACC-\d{8}-[A-Z0-9]{8}`. `credit_used = "0.00"`. `is_active = true`. `account_type = "ACTIVE"`. `payment_terms = "NET_60"`.
- Step 2: `200 OK`. All fields confirmed. `brand_id` equals `BRAND_A_ID`.

**Data Integrity Check**: `SELECT account_number, credit_limit, credit_used, payment_terms FROM customer_accounts WHERE company_name = 'Global Widgets Inc'` — `credit_used = 0.00`, `payment_terms = 'NET_60'`.

---

### TC-B2B-002

**Priority**: P0
**Feature**: B2B — approval threshold enforcement
**Title**: B2B order total above approval_threshold sets approval_status = PENDING and does not trigger sourcing

**Prerequisites**: `ACCOUNT_ACME_ID` with `approval_threshold = 10000.00`, `account_type = ACTIVE`, `is_active = true`. `BRAND_A_ID` has `tenant_mode = HYBRID`.

**Steps**:

1. Send `POST /api/orders/` with body:
   ```json
   {
     "channel": "B2B",
     "order_type": "B2B",
     "fulfillment_type": "SHIP_TO_HOME",
     "customer_email": "jane@acme.com",
     "customer_name": "Jane Buyer",
     "customer_account_id": "<ACCOUNT_ACME_ID>",
     "po_number": "PO-2026-001",
     "payment_terms": "NET_30",
     "brand_id": "<BRAND_A_ID>",
     "line_items": [
       {
         "sku": "SKU-GADGET-002",
         "product_name": "Test Gadget Pro",
         "quantity": 120,
         "unit_price": "89.99"
       }
     ],
     "shipping_amount": "50.00"
   }
   ```
   Note: `total_amount = (89.99 * 120) + 50.00 = 10848.80`, which is greater than `approval_threshold = 10000.00`.
   Store returned `id` as `ORDER_B2B_PENDING_ID`.
2. Send `GET /api/orders/<ORDER_B2B_PENDING_ID>`.

**Expected Result**:
- Step 1: `201 Created`. `approval_status = "PENDING"`. `status = "CONFIRMED"`. `po_number = "PO-2026-001"`. `payment_terms = "NET_30"`. `payment_due_date` is approximately `confirmed_at + 30 days`. `total_amount` is approximately `10848.80`.
- Step 2: Confirmed. `fulfillment_allocations` is an empty array (sourcing was not triggered).

**Data Integrity Check**: MongoDB `order_events` has `order.created` with `data.approval_status = "PENDING"`. Check that no `source_order` Celery task was dispatched to the Redis sourcing queue for this `order_id` (inspect Celery logs or Redis queue).

---

### TC-B2B-003

**Priority**: P0
**Feature**: B2B — order approval
**Title**: Superadmin approves a PENDING B2B order; approval is recorded and sourcing task is dispatched

**Prerequisites**: `ORDER_B2B_PENDING_ID` at `approval_status = PENDING` from TC-B2B-002.

**Steps**:

1. Send `POST /api/orders/<ORDER_B2B_PENDING_ID>/approve` with body:
   ```json
   {
     "approved": true,
     "notes": "Approved after credit verification"
   }
   ```
2. Send `GET /api/orders/<ORDER_B2B_PENDING_ID>`.
3. Send `GET /api/orders/<ORDER_B2B_PENDING_ID>/events`.

**Expected Result**:
- Step 1: `200 OK`. `approval_status = "APPROVED"`. `approved_by_id` is set to the superadmin's user UUID. `approved_at` is a recent ISO-8601 timestamp.
- Step 2: `approval_status = "APPROVED"`, `approved_at` populated.
- Step 3: Events array includes `order.created` and `order.approved`. The `order.approved` event has `data.approved_by` set and `data.notes = "Approved after credit verification"`.

**Data Integrity Check**: MongoDB `order_events` has `order.approved` event for this `order_id`. Celery sourcing queue received `source_order` task for this order_id after approval (visible in worker logs or Redis inspect).

---

### TC-B2B-004

**Priority**: P1
**Feature**: B2B — order rejection
**Title**: Superadmin rejects a PENDING B2B order; subsequent approval attempt returns 400

**Prerequisites**: Create a fresh high-value B2B order (same body as TC-B2B-002). Store its `id` as `ORDER_B2B_REJECT_ID`.

**Steps**:

1. Send `POST /api/orders/<ORDER_B2B_REJECT_ID>/approve` with body:
   ```json
   {
     "approved": false,
     "notes": "Rejected: insufficient credit history"
   }
   ```
2. Send `GET /api/orders/<ORDER_B2B_REJECT_ID>`.
3. Send `POST /api/orders/<ORDER_B2B_REJECT_ID>/approve` with body `{"approved": true}`.

**Expected Result**:
- Step 1: `200 OK`. `approval_status = "REJECTED"`.
- Step 2: `approval_status = "REJECTED"`. `notes` contains rejection reason.
- Step 3: `400 Bad Request`. Detail: `"Order approval_status is 'REJECTED', not PENDING"`.

**Data Integrity Check**: MongoDB `order_events` has `order.rejected` event for this `order_id`. No sourcing task was dispatched.

---

### TC-B2B-005

**Priority**: P1
**Feature**: B2B — below-threshold order
**Title**: B2B order total below approval_threshold gets approval_status = NOT_REQUIRED and sourcing starts immediately

**Prerequisites**: `ACCOUNT_ACME_ID` with `approval_threshold = 10000.00`.

**Steps**:

1. Send `POST /api/orders/` with body:
   ```json
   {
     "channel": "B2B",
     "order_type": "B2B",
     "fulfillment_type": "SHIP_TO_HOME",
     "customer_email": "jane@acme.com",
     "customer_name": "Jane Buyer",
     "customer_account_id": "<ACCOUNT_ACME_ID>",
     "po_number": "PO-2026-002",
     "payment_terms": "NET_30",
     "brand_id": "<BRAND_A_ID>",
     "line_items": [
       {
         "sku": "SKU-WIDGET-001",
         "product_name": "Test Widget Blue",
         "quantity": 10,
         "unit_price": "29.99"
       }
     ],
     "shipping_amount": "15.00"
   }
   ```
   Note: `total_amount = (29.99 * 10) + 15.00 = 314.90`, below the `10000.00` threshold.

**Expected Result**: `201 Created`. `approval_status = "NOT_REQUIRED"`. Celery `source_order` task is dispatched immediately (no approval gate required).

**Data Integrity Check**: MongoDB `order_events` has `order.created` with `data.approval_status = "NOT_REQUIRED"`. Celery sourcing queue received the `source_order` task at creation time.

---

### TC-B2B-006

**Priority**: P1
**Feature**: B2B — payment terms and due date
**Title**: NET_60 order has payment_due_date = confirmed_at + 60 days

**Prerequisites**: `ACCOUNT_ACME_ID` exists.

**Steps**:

1. Send `POST /api/orders/` with body:
   ```json
   {
     "channel": "B2B",
     "order_type": "B2B",
     "fulfillment_type": "SHIP_TO_HOME",
     "customer_email": "net60@example.com",
     "customer_account_id": "<ACCOUNT_ACME_ID>",
     "payment_terms": "NET_60",
     "brand_id": "<BRAND_A_ID>",
     "line_items": [
       {"sku": "SKU-WIDGET-001", "product_name": "Widget", "quantity": 1, "unit_price": "29.99"}
     ]
   }
   ```
2. Parse `confirmed_at` and `payment_due_date` from the response body.
3. Compute expected due date: `confirmed_at + 60 days`.

**Expected Result**: `201 Created`. `payment_due_date` equals `confirmed_at + 60 days` within a 5-second tolerance. `payment_terms = "NET_60"`.

**Data Integrity Check**: `SELECT confirmed_at, payment_due_date, payment_terms FROM orders WHERE customer_email = 'net60@example.com' ORDER BY created_at DESC LIMIT 1` — `payment_due_date = confirmed_at + INTERVAL '60 days'` (exact match in PostgreSQL).

---

### TC-B2B-007

**Priority**: P1
**Feature**: B2B — inactive account rejection
**Title**: Linking an order to an inactive customer account returns 404

**Prerequisites**: `ACCOUNT_STARTUP_ID` exists. Deactivate it first for this test.

**Steps**:

1. Send `PATCH /api/customers/<ACCOUNT_STARTUP_ID>` with body `{"is_active": false}`.
2. Send `POST /api/orders/` with body:
   ```json
   {
     "channel": "B2B",
     "order_type": "B2B",
     "fulfillment_type": "SHIP_TO_HOME",
     "customer_email": "bob@startup.com",
     "customer_account_id": "<ACCOUNT_STARTUP_ID>",
     "payment_terms": "PREPAID",
     "brand_id": "<BRAND_A_ID>",
     "line_items": [
       {"sku": "SKU-WIDGET-001", "product_name": "Widget", "quantity": 1, "unit_price": "29.99"}
     ]
   }
   ```

**Expected Result**:
- Step 1: `200 OK`.
- Step 2: `404 Not Found`. Detail: `"Customer account not found or inactive"`. No order created.

**Data Integrity Check**: `SELECT COUNT(*) FROM orders WHERE customer_account_id = '<ACCOUNT_STARTUP_ID>'` does not increase from step 1 to step 2.

---

### TC-B2B-008

**Priority**: P1
**Feature**: B2B — account number uniqueness per brand
**Title**: Same company can have accounts under two different brands; no account_number collision within the same brand

**Prerequisites**: `BRAND_A_ID` and `BRAND_B_ID` exist.

**Steps**:

1. Send `POST /api/customers/` with `company_name = "Shared Corp"`, `account_type = "ACTIVE"`, `brand_id = "<BRAND_A_ID>"`. Store returned `account_number` as `ACC_NUM_1`.
2. Send `POST /api/customers/` with `company_name = "Shared Corp"`, `account_type = "ACTIVE"`, `brand_id = "<BRAND_B_ID>"`. Store returned `account_number` as `ACC_NUM_2`.
3. Send `GET /api/customers/?brand_id=<BRAND_A_ID>&search=Shared+Corp`.
4. Send `GET /api/customers/?brand_id=<BRAND_B_ID>&search=Shared+Corp`.

**Expected Result**:
- Steps 1-2: Both return `201 Created`. `ACC_NUM_1 != ACC_NUM_2` (different account numbers; auto-generated with randomness so collision is astronomically unlikely).
- Step 3: Returns exactly 1 result with `brand_id = BRAND_A_ID`.
- Step 4: Returns exactly 1 result with `brand_id = BRAND_B_ID`.

**Data Integrity Check**: `SELECT account_number, brand_id FROM customer_accounts WHERE company_name = 'Shared Corp'` returns 2 rows with different `brand_id` values. The unique constraint `uq_account_number_brand` ensures no duplicate `(account_number, brand_id)` pair.

---

## TC-ISO — Multi-Brand Data Isolation

### TC-ISO-001

**Priority**: P1
**Feature**: Brand isolation — order list filtering
**Title**: Filtering orders by brand_id returns only that brand's orders; Brand B orders are invisible when filtering by Brand A

**Prerequisites**: At least 1 order exists for Brand A (from TC-B2C-001). Brand B either has no orders or has orders from a separate test.

**Steps**:

1. Send `GET /api/orders/?brand_id=<BRAND_A_ID>&page_size=100`. Note `total` as `N_A`. Verify every `items[*].brand_id` equals `BRAND_A_ID`.
2. Send `GET /api/orders/?brand_id=<BRAND_B_ID>&page_size=100`. Note `total` as `N_B`. Verify every `items[*].brand_id` equals `BRAND_B_ID` (or no items if none exist).
3. Send `GET /api/orders/?page_size=1`. Note `total` as `T`. Verify `T >= N_A + N_B`.

**Expected Result**:
- Step 1: All items belong to Brand A. `N_A >= 1`.
- Step 2: All items belong to Brand B. No Brand A order appears.
- Step 3: Total without filter is at least the sum of both brand counts.

**Data Integrity Check**: `SELECT COUNT(*) FROM orders WHERE brand_id = '<BRAND_B_ID>'` matches `N_B`.

---

### TC-ISO-002

**Priority**: P1
**Feature**: Brand isolation — sourcing rules
**Title**: A sourcing rule scoped to Brand A by condition does not appear in Brand B filtered query

**Prerequisites**: Sourcing rule with `conditions = [{"field": "brand_id", "operator": "EQUALS", "value": "<BRAND_A_ID>"}]` exists (the rule created with this condition in TC-BRAND-001's setup or a new one).

**Steps**:

1. Send `POST /api/sourcing-rules/` with body:
   ```json
   {
     "name": "Brand A Only Rule",
     "priority": 50,
     "is_active": true,
     "strategy": "DISTANCE_OPTIMAL",
     "conditions": [
       {"field": "brand_id", "operator": "EQUALS", "value": "<BRAND_A_ID>"}
     ],
     "created_by": "iso-test"
   }
   ```
   Store returned `id` as `RULE_BRAND_A_ID`.
2. Send `GET /api/sourcing-rules/?brand_id=<BRAND_A_ID>`.
3. Send `GET /api/sourcing-rules/?brand_id=<BRAND_B_ID>`.

**Expected Result**:
- Step 2: The rule `RULE_BRAND_A_ID` appears in the response list (it has a `brand_id` condition matching Brand A).
- Step 3: The rule `RULE_BRAND_A_ID` does not appear in the response list.

**Data Integrity Check**: `SELECT COUNT(*) FROM sourcing_rules WHERE id = '<RULE_BRAND_A_ID>'` returns `1` (rule exists globally; the filtering is at the application layer via the `brand_id` query parameter).

---

### TC-ISO-003

**Priority**: P1
**Feature**: Brand isolation — customer accounts
**Title**: Customer accounts for Brand A do not appear when querying with Brand B filter

**Prerequisites**: `ACCOUNT_ACME_ID` exists under Brand A. At least one account under Brand B (created in TC-B2B-008, "Shared Corp" Brand B account).

**Steps**:

1. Send `GET /api/customers/?brand_id=<BRAND_A_ID>&search=Acme`.
2. Send `GET /api/customers/?brand_id=<BRAND_B_ID>&search=Acme`.

**Expected Result**:
- Step 1: Returns Acme Corp account with `brand_id = BRAND_A_ID`.
- Step 2: Returns empty result set — Acme Corp is not visible under Brand B's filter.

**Data Integrity Check**: `SELECT brand_id FROM customer_accounts WHERE company_name = 'Acme Corp'` returns only `BRAND_A_ID`.

---

### TC-ISO-004

**Priority**: P1
**Feature**: Brand isolation — B2C_ONLY tenant mode rejects B2B order linking
**Title**: Cannot create a B2B order (with customer_account_id) under a B2C_ONLY brand

**Prerequisites**: `BRAND_B_ID` has `tenant_mode = "B2C_ONLY"`. `ACCOUNT_ACME_ID` exists under Brand A.

**Steps**:

1. Send `POST /api/orders/` with body:
   ```json
   {
     "channel": "B2B",
     "order_type": "B2B",
     "fulfillment_type": "SHIP_TO_HOME",
     "customer_email": "jane@acme.com",
     "customer_account_id": "<ACCOUNT_ACME_ID>",
     "brand_id": "<BRAND_B_ID>",
     "payment_terms": "NET_30",
     "line_items": [
       {"sku": "SKU-WIDGET-001", "product_name": "Widget", "quantity": 1, "unit_price": "29.99"}
     ]
   }
   ```

**Expected Result**: `403 Forbidden`. Detail: `"B2B account linking is not enabled for this organization."`. No order is created.

**Data Integrity Check**: `SELECT COUNT(*) FROM orders WHERE brand_id = '<BRAND_B_ID>' AND customer_account_id IS NOT NULL` remains `0`.

---

### TC-ISO-005

**Priority**: P1
**Feature**: Brand isolation — analytics dashboard
**Title**: Analytics dashboard filtered by brand_id reflects only that brand's order counts and revenue

**Prerequisites**: Both brands have at least one order each (from previous test cases).

**Steps**:

1. Send `GET /api/analytics/dashboard?brand_id=<BRAND_A_ID>`. Note `total_orders` as `D_A` and `total_revenue` as `R_A`.
2. Send `GET /api/analytics/dashboard?brand_id=<BRAND_B_ID>`. Note `total_orders` as `D_B`.
3. Send `GET /api/analytics/dashboard` (no brand filter). Note `total_orders` as `D_ALL`.
4. Verify `D_ALL >= D_A + D_B`.

**Expected Result**:
- Step 1: `D_A` matches `SELECT COUNT(*) FROM orders WHERE brand_id = '<BRAND_A_ID>' AND created_at >= NOW() - INTERVAL '30 days'` (the default 30-day window).
- Step 2: `D_B` reflects only Brand B orders.
- Step 4: `D_ALL >= D_A + D_B` (may include orders with no brand set).

**Data Integrity Check**: Cross-reference API response values with direct SQL aggregation per brand.

---

### TC-ISO-006

**Priority**: P1
**Feature**: Brand isolation — ISOLATED inventory mode brand_id tagging
**Title**: Inventory items for an ISOLATED brand carry brand_id; unbranded items have brand_id = NULL

**Prerequisites**: A brand exists (can reuse any existing brand for this test). Inventory seeded with explicit `brand_id` and without `brand_id`.

**Steps**:

1. Create brand: `POST /api/brands/` with `{"slug": "isolated-inv-brand", "name": "Isolated Inventory Brand", "tenant_mode": "HYBRID"}`. Store `id` as `BRAND_ISO_ID`.
2. Create inventory item with `brand_id` set:
   ```json
   POST /api/inventory/
   {
     "node_id": "<NODE_EAST_ID>",
     "sku": "SKU-ISO-PRIVATE",
     "product_name": "Private Isolated SKU",
     "quantity_on_hand": 100,
     "brand_id": "<BRAND_ISO_ID>"
   }
   ```
3. Send `GET /api/inventory/?sku=SKU-ISO-PRIVATE` and inspect the response.
4. Send `GET /api/inventory/?node_id=<NODE_EAST_ID>&sku=SKU-WIDGET-001` and inspect `brand_id` field.

**Expected Result**:
- Step 2: `201 Created`. Response has `brand_id = "<BRAND_ISO_ID>"`.
- Step 3: Item appears with `brand_id` equal to `BRAND_ISO_ID`.
- Step 4: `SKU-WIDGET-001` item has `brand_id = null` (global shared inventory, no brand restriction).

**Data Integrity Check**: `SELECT brand_id FROM inventory_items WHERE sku = 'SKU-ISO-PRIVATE'` returns `BRAND_ISO_ID`. `SELECT brand_id FROM inventory_items WHERE sku = 'SKU-WIDGET-001'` returns `null`.

---

## TC-AI — AI-Native Sourcing

### TC-AI-001

**Priority**: P1
**Feature**: AI sourcing — strategy metadata
**Title**: Sourcing metadata endpoint returns all 7 strategies including AI_ADAPTIVE and AI_HYBRID

**Prerequisites**: None.

**Steps**:

1. Send `GET /api/sourcing-rules/metadata`.

**Expected Result**: `200 OK`. Response JSON `strategies` array contains exactly: `DISTANCE_OPTIMAL`, `COST_OPTIMAL`, `STORE_NEAREST`, `INVENTORY_RESERVATION`, `LEAST_COST_SPLIT`, `AI_ADAPTIVE`, `AI_HYBRID`. The `condition_fields` array includes entries with `field = "brand_id"` and `field = "brand_slug"`. The `operators` array includes `EQUALS`, `IN`, `GREATER_THAN`, etc.

**Data Integrity Check**: No DB check required — static configuration endpoint.

---

### TC-AI-002

**Priority**: P1
**Feature**: AI sourcing — new brand fallback behavior
**Title**: AI_ADAPTIVE rule for a brand with no sourcing pattern history falls back to DISTANCE_OPTIMAL

**Prerequisites**: Create a fresh brand with zero orders and zero sourcing patterns. Nodes with known coordinates exist.

**Steps**:

1. Send `POST /api/brands/` with `{"slug": "ai-fallback-brand", "name": "AI Fallback Brand", "tenant_mode": "HYBRID"}`. Store `id` as `BRAND_AI_ID`.
2. Send `POST /api/sourcing-rules/` with:
   ```json
   {
     "name": "AI Adaptive Fallback Test",
     "priority": 5,
     "is_active": true,
     "strategy": "AI_ADAPTIVE",
     "conditions": [
       {"field": "brand_id", "operator": "EQUALS", "value": "<BRAND_AI_ID>"}
     ],
     "created_by": "ai-fallback-test"
   }
   ```
3. Send `POST /api/orders/` for this brand (WEB channel, SHIP_TO_HOME, `SKU-WIDGET-001`, qty 1, with a Boston shipping address). Store returned `id` as `ORDER_AI_ID`.
4. Send `POST /api/orders/<ORDER_AI_ID>/trigger-worker` with body `{"action": "source"}`.
5. Wait 15 seconds. Send `GET /api/orders/<ORDER_AI_ID>/events`.

**Expected Result**:
- Step 3: `201 Created`.
- Step 4: `200 OK`, `{"action": "source", "queued": true}`.
- Step 5: Events include `order.sourced`. In the sourced event `data`, look for `strategy_used = "DISTANCE_OPTIMAL"` — this confirms the AI_ADAPTIVE strategy fell back gracefully because the new brand has fewer than the minimum 50 sourcing pattern samples (`MIN_CLUSTER_SAMPLES = 50`). `fulfillment_allocations` in the order response is non-empty with a valid node assigned.

**Data Integrity Check**: `order_events` has `order.sourced` event. The MongoDB AI database `sourcing_patterns` collection has zero documents with a `cluster_key` that starts with `ai-fallback-brand|`. `fulfillment_allocations` row exists for this order in PostgreSQL with `status = 'ALLOCATED'`.

---

### TC-AI-003

**Priority**: P2
**Feature**: AI sourcing — architect proposals full lifecycle
**Title**: Seed an AI proposal, approve it, apply it (creates inactive rule), then rollback (deletes rule)

**Prerequisites**: Superadmin token. No prerequisite proposals. Access to run SQL directly or an existing pending proposal from the learning worker.

**Steps**:

1. Insert a test proposal directly via SQL (or retrieve an existing pending one from `GET /api/architect/proposals?status=pending`):
   ```sql
   INSERT INTO ai_proposals (id, proposal_type, title, description, rationale, confidence_score, status, proposal_data, generated_by)
   VALUES (
     gen_random_uuid(),
     'sourcing_rule',
     'TC-AI-003 Test Proposal',
     'Automated test proposal for lifecycle validation',
     'Pattern observed during test run',
     0.87,
     'pending',
     '{"name": "AI Rule from Proposal", "strategy": "COST_OPTIMAL", "priority": 75, "conditions": [], "max_split_nodes": 2, "description": "AI-generated test rule"}'::jsonb,
     'test-suite'
   )
   RETURNING id;
   ```
   Store returned `id` as `PROPOSAL_ID`.
2. Send `GET /api/architect/proposals/<PROPOSAL_ID>`. Confirm `status = "pending"`.
3. Send `POST /api/architect/proposals/<PROPOSAL_ID>/approve`.
4. Send `GET /api/architect/proposals/<PROPOSAL_ID>`. Confirm `status = "approved"`, `approved_by` is the admin's email.
5. Send `POST /api/architect/proposals/<PROPOSAL_ID>/apply`.
6. Send `GET /api/architect/proposals/<PROPOSAL_ID>`. Note `rollback_data.rule_id` as `CREATED_RULE_ID`. Confirm `status = "applied"`, `applied_at` is populated.
7. Send `GET /api/sourcing-rules/<CREATED_RULE_ID>`. Confirm the rule exists with `is_active = false`.
8. Send `POST /api/architect/proposals/<PROPOSAL_ID>/rollback`.
9. Send `GET /api/architect/proposals/<PROPOSAL_ID>`. Confirm `status = "rolled_back"`.
10. Send `GET /api/sourcing-rules/<CREATED_RULE_ID>`. Confirm `404 Not Found`.

**Expected Result**:
- Steps 3, 5, 8: `200 OK`.
- Step 7: `is_active = false` (additive-only safety guarantee — admin must explicitly activate after review).
- Step 9: `status = "rolled_back"`.
- Step 10: `404` — rollback deleted the inserted rule using `DELETE` (no destructive DDL, only row removal).

**Data Integrity Check**: `SELECT status FROM ai_proposals WHERE id = '<PROPOSAL_ID>'` returns `rolled_back`. `SELECT COUNT(*) FROM sourcing_rules WHERE id = '<CREATED_RULE_ID>'` returns `0`.

---

### TC-AI-004

**Priority**: P2
**Feature**: AI sourcing — proposal state machine enforcement
**Title**: Applying a pending (unapproved) proposal returns 409; approving an already-applied proposal returns 409

**Prerequisites**: One proposal in `pending` state (`PROPOSAL_PENDING_ID`) and one in `applied` state (`PROPOSAL_APPLIED_ID` from TC-AI-003 before rollback, or create a second proposal and apply it).

**Steps**:

1. Send `POST /api/architect/proposals/<PROPOSAL_PENDING_ID>/apply`.
2. Send `POST /api/architect/proposals/<PROPOSAL_APPLIED_ID>/approve`.

**Expected Result**:
- Step 1: `409 Conflict`. Detail: `"Proposal must be approved before applying (current: pending)"`.
- Step 2: `409 Conflict`. Detail: `"Proposal is already applied"`.

**Data Integrity Check**: Neither proposal's status changes. `SELECT status FROM ai_proposals WHERE id IN ('<PROPOSAL_PENDING_ID>', '<PROPOSAL_APPLIED_ID>')` returns unchanged values.

---

### TC-AI-005

**Priority**: P2
**Feature**: AI sourcing — experiments (A/B traffic splitting)
**Title**: Create a sourcing experiment, pause it, resume it, and verify state transitions

**Prerequisites**: Superadmin token. `BRAND_A_ID` exists.

**Steps**:

1. Send `POST /api/architect/experiments` with body:
   ```json
   {
     "name": "TC-AI-005 Distance vs Cost A/B",
     "description": "Test DISTANCE_OPTIMAL vs COST_OPTIMAL",
     "strategy_a": "DISTANCE_OPTIMAL",
     "strategy_b": "COST_OPTIMAL",
     "traffic_split_pct": 30,
     "brand_id": "<BRAND_A_ID>"
   }
   ```
   Store returned `id` as `EXPERIMENT_ID`.
2. Send `GET /api/architect/experiments`.
3. Send `POST /api/architect/experiments/<EXPERIMENT_ID>/pause`.
4. Send `GET /api/architect/experiments/<EXPERIMENT_ID>/results`.
5. Send `POST /api/architect/experiments/<EXPERIMENT_ID>/resume`.

**Expected Result**:
- Step 1: `201 Created` (or `200 OK`). Experiment record has `traffic_split_pct = 30`, `strategy_a = "DISTANCE_OPTIMAL"`, `strategy_b = "COST_OPTIMAL"`.
- Step 2: Experiment appears in the list.
- Step 3: Experiment status transitions to a paused/inactive state.
- Step 4: Returns current arm comparison data from MongoDB (may be empty if no orders have run through the experiment yet).
- Step 5: Experiment status returns to running/active.

**Data Integrity Check**: `SELECT status FROM ai_experiments WHERE id = '<EXPERIMENT_ID>'` reflects each state transition. Verify `traffic_split_pct = 30` in the stored record.

---

## TC-INV — Inventory and Node Management

### TC-INV-001

**Priority**: P1
**Feature**: Inventory — adjustment
**Title**: RECEIVED adjustment increases quantity_on_hand and quantity_available correctly

**Prerequisites**: `SKU-WIDGET-001` inventory exists at `NODE_EAST_ID`. Note current `quantity_on_hand` as `Q0`.

**Steps**:

1. Send `GET /api/inventory/?node_id=<NODE_EAST_ID>&sku=SKU-WIDGET-001`. Note `id` as `INV_ITEM_ID` and `quantity_on_hand` as `Q0`.
2. Send `POST /api/inventory/<INV_ITEM_ID>/adjust` with body:
   ```json
   {
     "quantity_change": 50,
     "reason": "RECEIVED",
     "notes": "Purchase order PO-TEST-001 received"
   }
   ```
3. Send `GET /api/inventory/<INV_ITEM_ID>`.

**Expected Result**:
- Step 2: `200 OK`. Response shows `quantity_on_hand = Q0 + 50`. `quantity_available` also increases by 50 (assuming no reservation change).
- Step 3: Same values confirmed.

**Data Integrity Check**: `SELECT quantity_on_hand, quantity_available, quantity_reserved FROM inventory_items WHERE id = '<INV_ITEM_ID>'` — `quantity_on_hand = Q0 + 50`, `quantity_available = quantity_on_hand - quantity_reserved`. An `inventory_adjustments` row exists with `reason = 'RECEIVED'`, `quantity_change = 50`, `reference_note = 'Purchase order PO-TEST-001 received'`.

---

### TC-INV-002

**Priority**: P1
**Feature**: Inventory — low stock filter
**Title**: Items with quantity_available at or below reorder_point appear in the low_stock_only filter

**Prerequisites**: `SKU-RARE-003` seeded with `quantity_on_hand = 3`, `reorder_point = 10` (3 <= 10 means it is below reorder point).

**Steps**:

1. Send `GET /api/inventory/?low_stock_only=true`.
2. Inspect the response list for `SKU-RARE-003`.
3. Send `GET /api/inventory/?low_stock_only=false&sku=SKU-RARE-003`.

**Expected Result**:
- Step 1: Response includes an item with `sku = "SKU-RARE-003"` and `quantity_available = 3`.
- Step 2: Item found in the low-stock list.
- Step 3: Same item appears in the full (non-filtered) list as well.

**Data Integrity Check**: `SELECT sku, quantity_available, reorder_point FROM inventory_items WHERE quantity_available <= reorder_point AND is_active = TRUE` includes `SKU-RARE-003`.

---

### TC-INV-003

**Priority**: P1
**Feature**: Inventory — inter-node transfer
**Title**: Transfer 30 units from East DC to West DC; both nodes' quantities update correctly

**Prerequisites**: `SKU-WIDGET-001` inventory exists at both `NODE_EAST_ID` and `NODE_WEST_ID` with sufficient stock at East DC. Record current quantities.

**Steps**:

1. Send `GET /api/inventory/?node_id=<NODE_EAST_ID>&sku=SKU-WIDGET-001`. Note `quantity_on_hand` as `QE0`.
2. Send `GET /api/inventory/?node_id=<NODE_WEST_ID>&sku=SKU-WIDGET-001`. Note `quantity_on_hand` as `QW0`.
3. Send `POST /api/inventory/transfer` with body:
   ```json
   {
     "from_node_id": "<NODE_EAST_ID>",
     "to_node_id": "<NODE_WEST_ID>",
     "sku": "SKU-WIDGET-001",
     "quantity": 30,
     "notes": "Rebalancing stock east to west"
   }
   ```
4. Send `GET /api/inventory/?node_id=<NODE_EAST_ID>&sku=SKU-WIDGET-001`.
5. Send `GET /api/inventory/?node_id=<NODE_WEST_ID>&sku=SKU-WIDGET-001`.

**Expected Result**:
- Step 3: `200 OK`.
- Step 4: `quantity_on_hand = QE0 - 30`.
- Step 5: `quantity_on_hand = QW0 + 30`.

**Data Integrity Check**: Two `inventory_adjustments` rows created: one at `NODE_EAST_ID` with `reason = 'TRANSFER_OUT'`, `quantity_change = -30`; one at `NODE_WEST_ID` with `reason = 'TRANSFER_IN'`, `quantity_change = 30`. Net total across both nodes for `SKU-WIDGET-001` is unchanged: `(QE0 - 30) + (QW0 + 30) = QE0 + QW0`.

---

### TC-INV-004

**Priority**: P1
**Feature**: Node management — code uniqueness
**Title**: Creating a node with a code that already exists returns 409 Conflict

**Prerequisites**: Node with code `DC-EAST-001` exists from Test Data Setup.

**Steps**:

1. Send `POST /api/nodes/` with body:
   ```json
   {
     "code": "DC-EAST-001",
     "name": "Duplicate East DC",
     "node_type": "DISTRIBUTION_CENTER",
     "address_line1": "999 Duplicate Lane",
     "city": "Newark",
     "state": "NJ",
     "postal_code": "07102",
     "country": "US",
     "latitude": 40.7357,
     "longitude": -74.1724
   }
   ```

**Expected Result**: `409 Conflict`. Detail: `"Node with code 'DC-EAST-001' already exists"`. No new node row is created.

**Data Integrity Check**: `SELECT COUNT(*) FROM fulfillment_nodes WHERE code = 'DC-EAST-001'` returns exactly `1`.

---

## TC-PLAT — Platform and RBAC

### TC-PLAT-001

**Priority**: P0
**Feature**: RBAC — authentication enforcement
**Title**: Unauthenticated requests to protected endpoints return 401; the public webhook endpoint does not

**Prerequisites**: No auth token (simulate by sending requests with no Authorization header, or with `Authorization: Bearer invalid_token`).

**Steps**:

1. Send `GET /api/orders/` — no Authorization header.
2. Send `GET /api/inventory/` — no Authorization header.
3. Send `GET /api/brands/` — no Authorization header.
4. Send `POST /api/connectors/<CONNECTOR_SHOPIFY_ID>/webhook` with `Content-Type: application/json` and body `{}` — no Authorization header.

**Expected Result**:
- Steps 1, 2, 3: `401 Unauthorized`. Auth middleware rejects the request before it reaches the handler.
- Step 4: Not `401`. Response is `200 OK` (if HMAC is accidentally valid), `400`, or `403` based on HMAC validation — but NOT `401`. The webhook endpoint is explicitly public and JWT-exempt.

**Data Integrity Check**: No orders, inventory adjustments, or brands were created or modified.

---

### TC-PLAT-002

**Priority**: P1
**Feature**: RBAC — superadmin-only endpoints
**Title**: Regular (non-superadmin) user is forbidden from brand CRUD, customer accounts, and architect endpoints

**Prerequisites**: Superadmin token available to create the regular user.

**Steps**:

1. Send `POST /api/admin/users` with body:
   ```json
   {
     "email": "regular@example.com",
     "full_name": "Regular Test User",
     "password": "TestPassword123!",
     "is_superadmin": false
   }
   ```
2. Send `POST /api/auth/login` with `{"email": "regular@example.com", "password": "TestPassword123!"}`. Store returned token as `USER_TOKEN`.
3. Send `GET /api/brands/` with `Authorization: Bearer <USER_TOKEN>`.
4. Send `POST /api/customers/` (any valid body) with `Authorization: Bearer <USER_TOKEN>`.
5. Send `GET /api/architect/proposals` with `Authorization: Bearer <USER_TOKEN>`.

**Expected Result**:
- Steps 3, 4, 5: `403 Forbidden`. Regular user does not have superadmin privileges required by `require_superadmin` dependency.

**Data Integrity Check**: No new brands or customer accounts were created by the regular user. `SELECT is_superadmin, platform_role FROM users WHERE email = 'regular@example.com'` shows `is_superadmin = false`, `platform_role = NULL` or `'USER'`.

---

### TC-PLAT-003

**Priority**: P1
**Feature**: Platform — environment header routing
**Title**: X-OMS-Environment header changes which environment's data is returned

**Prerequisites**: At least two environments exist. Default production environment has orders. DEV environment is empty or has different orders. Store DEV environment id as `DEV_ENV_ID`.

**Steps**:

1. Send `GET /api/orders/?page_size=5` — no environment header. Note `total` as `PROD_TOTAL`.
2. Send `GET /api/orders/?page_size=5` with header `X-OMS-Environment: <DEV_ENV_ID>`. Note `total` as `DEV_TOTAL`.

**Expected Result**:
- If DEV environment has no orders: `DEV_TOTAL = 0` and `PROD_TOTAL >= 1`, demonstrating the middleware correctly isolated the data plane DBs.
- If DEV environment has orders: The order numbers returned in step 2 differ from those in step 1, confirming data plane separation.
- In both cases: No `401` or `500` error — the middleware resolves the header gracefully.

**Data Integrity Check**: Inspect the EnvironmentMiddleware Redis cache. The key for `DEV_ENV_ID` resolves to the DEV environment's `db_name`. Orders returned route to `oms_{dev_org_slug}_{dev_env_slug}` database, not `oms_db` (production).

---

### TC-PLAT-004

**Priority**: P1
**Feature**: RBAC — platform role assignment
**Title**: Platform Owner can assign platform roles; Superadmin cannot

**Prerequisites**: A Platform Owner account exists (platform_role = PLATFORM_OWNER). A Superadmin account exists. A target regular user (`USER_TOKEN` from TC-PLAT-002) to be promoted/demoted.

**Steps**:

1. Send `POST /api/auth/login` with Platform Owner credentials. Store token as `OWNER_TOKEN`.
2. Send `PATCH /api/admin/users/<REGULAR_USER_ID>/platform-role` with body `{"platform_role": "SUPERADMIN"}` and `Authorization: Bearer <OWNER_TOKEN>`.
3. Send `GET /api/admin/users` with `Authorization: Bearer <OWNER_TOKEN>`. Find the regular user and verify `platform_role = "SUPERADMIN"`.
4. Send `POST /api/auth/login` with plain superadmin credentials. Store as `SUPERADMIN_TOKEN`.
5. Send `PATCH /api/admin/users/<REGULAR_USER_ID>/platform-role` with body `{"platform_role": "USER"}` and `Authorization: Bearer <SUPERADMIN_TOKEN>`.

**Expected Result**:
- Step 2: `200 OK`. User's `platform_role` updated to `"SUPERADMIN"`.
- Step 3: User appears with `platform_role = "SUPERADMIN"`, `is_superadmin = true`.
- Step 5: `403 Forbidden`. Only Platform Owner can change platform roles — superadmin is blocked.

**Data Integrity Check**: `SELECT platform_role, is_superadmin FROM users WHERE id = '<REGULAR_USER_ID>'` returns `SUPERADMIN` and `true` (not changed by step 5, which was rejected).

---

## TC-CONN — Connectors

### TC-CONN-001

**Priority**: P2
**Feature**: Connector CRUD and toggle
**Title**: Create connector (starts INACTIVE), toggle to ACTIVE, toggle back to INACTIVE, confirm webhook_url format

**Prerequisites**: Superadmin token. `CONNECTOR_SHOPIFY_ID` created in Test Data Setup.

**Steps**:

1. Send `GET /api/connectors/<CONNECTOR_SHOPIFY_ID>`.
2. Send `POST /api/connectors/<CONNECTOR_SHOPIFY_ID>/toggle`.
3. Send `GET /api/connectors/<CONNECTOR_SHOPIFY_ID>`.
4. Send `POST /api/connectors/<CONNECTOR_SHOPIFY_ID>/toggle`.
5. Send `GET /api/connectors/<CONNECTOR_SHOPIFY_ID>`.

**Expected Result**:
- Step 1: `status = "INACTIVE"`. `webhook_url` is non-null and formatted as `<PUBLIC_BASE_URL>/connectors/<CONNECTOR_SHOPIFY_ID>/webhook`.
- Step 2: `200 OK`. `status = "ACTIVE"`.
- Step 3: `status = "ACTIVE"` confirmed. `last_error` is null (cleared on activation).
- Step 4: `200 OK`. `status = "INACTIVE"`.
- Step 5: `status = "INACTIVE"` confirmed.

**Data Integrity Check**: `SELECT status FROM connectors WHERE id = '<CONNECTOR_SHOPIFY_ID>'` reflects each toggle state correctly.

---

### TC-CONN-002

**Priority**: P2
**Feature**: Connector — Shopify HMAC webhook validation
**Title**: Webhook with invalid HMAC is rejected; webhook with valid HMAC is accepted and creates a ConnectorEvent

**Prerequisites**: `CONNECTOR_SHOPIFY_ID` is ACTIVE (toggle from TC-CONN-001). Webhook secret is `test_webhook_secret_32chars_ok` (configured in Test Data Setup).

**Steps**:

1. Send `POST /api/connectors/<CONNECTOR_SHOPIFY_ID>/webhook` with headers:
   - `Content-Type: application/json`
   - `X-Shopify-Hmac-Sha256: dGhpcyBpcyBub3QgdmFsaWQ=` (invalid base64 HMAC)
   And body: `{"id": 1001, "email": "shopify@test.com", "line_items": []}`.
2. Compute valid HMAC: `HMAC-SHA256(key="test_webhook_secret_32chars_ok", message=<exact_request_body_bytes>)` then base64-encode the digest.
   Body to use:
   ```json
   {"id": 1001, "email": "shopify@test.com", "line_items": [{"sku": "SKU-WIDGET-001", "quantity": 1, "price": "29.99"}]}
   ```
   Send `POST /api/connectors/<CONNECTOR_SHOPIFY_ID>/webhook` with headers:
   - `Content-Type: application/json`
   - `X-Shopify-Hmac-Sha256: <valid_computed_signature>`

**Expected Result**:
- Step 1: `401 Unauthorized` or `403 Forbidden`. HMAC mismatch detected and rejected before any processing.
- Step 2: `200 OK`. Webhook accepted. A `ConnectorEvent` record is created in the database.

**Data Integrity Check**: `SELECT COUNT(*) FROM connector_events WHERE connector_id = '<CONNECTOR_SHOPIFY_ID>'` — count increases by exactly `1` after step 2 but does not increase after step 1.

---

### TC-CONN-003

**Priority**: P2
**Feature**: Connector — event log
**Title**: Connector event log is paginated and filterable by direction and status

**Prerequisites**: At least one successful webhook received (`CONNECTOR_SHOPIFY_ID`) from TC-CONN-002, creating an inbound event.

**Steps**:

1. Send `GET /api/connectors/<CONNECTOR_SHOPIFY_ID>/events?limit=10&offset=0`.
2. Send `GET /api/connectors/<CONNECTOR_SHOPIFY_ID>/events?direction=inbound&limit=10`.
3. Send `GET /api/connectors/<CONNECTOR_SHOPIFY_ID>/events?direction=outbound&limit=10`.

**Expected Result**:
- Step 1: `200 OK`. Array of up to 10 event objects, each containing `connector_id`, `direction`, `status`, `created_at`.
- Step 2: All returned events have `direction = "inbound"`.
- Step 3: Returns only `direction = "outbound"` events (may be an empty array `[]` if no fulfillment pushes have been made).

**Data Integrity Check**: `SELECT direction, COUNT(*) FROM connector_events WHERE connector_id = '<CONNECTOR_SHOPIFY_ID>' GROUP BY direction` — inbound count matches step 2's result count; outbound count matches step 3's result count.

---

## TC-SRCH — Search and Monitoring

### TC-SRCH-001

**Priority**: P2
**Feature**: Elasticsearch order search
**Title**: Full-text search for customer name returns matching orders; case-insensitive fuzzy matching works

**Prerequisites**: Order with `customer_name = "Alice Smith"` exists and has been indexed in Elasticsearch (from TC-B2C-001; wait up to 5 seconds after creation for the background Elasticsearch index task to complete).

**Steps**:

1. Send `POST /api/search/orders` with body:
   ```json
   {"query": "Alice Smith", "page": 1, "page_size": 10}
   ```
2. Send `POST /api/search/orders` with body:
   ```json
   {"query": "Alice Smith", "status": "CONFIRMED", "page": 1, "page_size": 10}
   ```
3. Send `POST /api/search/orders` with body:
   ```json
   {"query": "alice smith", "page": 1, "page_size": 10}
   ```

**Expected Result**:
- Step 1: `200 OK`. Response has `total_hits >= 1`, `took_ms` (positive integer), `hits` array. At least one hit has `customer_name = "Alice Smith"`.
- Step 2: Results filtered to `status = "CONFIRMED"` (or `SHIPPED` or whatever Alice's order is in now). All hits match the status filter.
- Step 3: Same Alice Smith result returned (case-insensitive via `fuzziness: AUTO` in the multi_match query).

**Data Integrity Check**: `hits[*].id` from step 1 should all match `SELECT id FROM orders WHERE customer_name ILIKE '%Alice Smith%'` in PostgreSQL (assuming Elasticsearch index is not lagging).

---

### TC-SRCH-002

**Priority**: P2
**Feature**: Monitoring — error event retrieval
**Title**: Monitoring endpoint returns error events, filterable by level and source_service

**Prerequisites**: Superadmin token. MongoDB `error_events` collection exists. If empty in a fresh environment, insert a test document:
```javascript
db.error_events.insertOne({
  timestamp: new Date(),
  level: "ERROR",
  source_service: "sourcing_worker",
  error_type: "TestError",
  message: "Test error for TC-SRCH-002",
  order_id: null,
  fingerprint: "test-fingerprint-001"
});
```

**Steps**:

1. Send `GET /api/monitoring/events?level=ERROR&limit=10`.
2. Send `GET /api/monitoring/events?level=WARNING&source_service=sourcing_worker&limit=10`.
3. Send `GET /api/monitoring/issues?limit=10`.

**Expected Result**:
- Step 1: `200 OK`. Array of events, each with `timestamp`, `level = "ERROR"`, `source_service`. Count `>= 1` if the test document was inserted.
- Step 2: Array filtered to `level = "WARNING"` events from `sourcing_worker` (may be empty if none logged).
- Step 3: Aggregated error issues list. Each entry may have `fingerprint`, `count`, and representative event details.

**Data Integrity Check**: `db.error_events.count_documents({"level": "ERROR"})` in MongoDB should be <= the count returned in step 1 (step 1 is capped at 10 by the limit param).

---

### TC-SRCH-003

**Priority**: P2
**Feature**: Analytics — channel breakdown
**Title**: Analytics channel breakdown aggregates order counts per channel and matches SQL count

**Prerequisites**: Orders exist across multiple channels: WEB (from TC-B2C-001), B2B (from TC-B2B-002), MOBILE (from TC-B2C-007).

**Steps**:

1. Send `GET /api/analytics/channel-breakdown?brand_id=<BRAND_A_ID>`.
2. Also run: `SELECT channel, COUNT(*) FROM orders WHERE brand_id = '<BRAND_A_ID>' AND created_at >= NOW() - INTERVAL '30 days' GROUP BY channel` in PostgreSQL.

**Expected Result**:
- Step 1: `200 OK`. Response is a list of objects each with `channel` (string) and `order_count` (integer). Channels `WEB`, `B2B`, and `MOBILE` appear with `order_count >= 1`. The total across all channels equals the `total_orders` from `GET /api/analytics/dashboard?brand_id=<BRAND_A_ID>` for the same default 30-day window.

**Data Integrity Check**: Each `{channel, order_count}` pair in the API response matches the SQL query output from step 2. Variance is acceptable only if orders were created in the last few seconds (within the query time window boundary).

---

## TC-AUDIT — Data Integrity and Audit Trail

### TC-AUDIT-001

**Priority**: P0
**Feature**: MongoDB audit trail — completeness
**Title**: Every order created through the API has an order.created event in MongoDB

**Prerequisites**: At least 3 orders exist from previous test cases.

**Steps**:

1. Send `GET /api/orders/?page_size=10`. Collect all `id` values from `items`.
2. For each `order_id` in the list: send `GET /api/orders/<order_id>/events`.
3. For each response: verify at least one event object has `event_type = "order.created"`.

**Expected Result**: Every order has a `order.created` event. The event's `data` object contains at minimum: `order_number` (matches the order), `channel`, `total_amount`, `approval_status`.

**Data Integrity Check**:
```javascript
// MongoDB
db.order_events.aggregate([
  {$match: {event_type: "order.created"}},
  {$group: {_id: "$order_id"}},
  {$count: "total"}
])
```
The `total` should equal the number of distinct `order_id` values in the `order_events` collection that have a `created` event. Cross-reference with `SELECT COUNT(*) FROM orders` in PostgreSQL — they should match (allowing a few seconds of eventual consistency lag for background tasks).

---

### TC-AUDIT-002

**Priority**: P1
**Feature**: Audit trail — credit limit change logging
**Title**: Updating a customer account's credit_limit logs an audit event to MongoDB account_events collection

**Prerequisites**: `ACCOUNT_ACME_ID` exists with `credit_limit = 50000.00`. Superadmin token.

**Steps**:

1. Send `PATCH /api/customers/<ACCOUNT_ACME_ID>` with body `{"credit_limit": "75000.00"}`.
2. Wait 1 second. Query MongoDB `account_events` collection for `account_id = "<ACCOUNT_ACME_ID>"` and `event_type = "customer_account.credit_limit_changed"`.
3. Inspect the event document.

**Expected Result**:
- Step 1: `200 OK`. Response shows `credit_limit = "75000.00"`.
- Step 2: At least one event document found.
- Step 3: Event has `data.old_credit_limit = 50000.0`, `data.new_credit_limit = 75000.0`, `user_id` set to the admin's UUID, `timestamp` is recent.

**Data Integrity Check**: `SELECT credit_limit FROM customer_accounts WHERE id = '<ACCOUNT_ACME_ID>'` returns `75000.00`. MongoDB `account_events` has the audit record with correct old/new values.

---

### TC-AUDIT-003

**Priority**: P1
**Feature**: Data integrity — inventory reservation vs. allocation alignment
**Title**: After sourcing completes, inventory quantity_reserved matches the sum of active allocation quantities

**Prerequisites**: An order that has been sourced by the Celery worker and has `fulfillment_allocations` present. Use an order from TC-B2C-003 or TC-AI-002 after sourcing completes.

**Steps**:

1. Send `GET /api/orders/<ORDER_SOURCED_ID>`. Note each entry in `fulfillment_allocations`: `node_id`, `sku`, `quantity_allocated`, `status`.
2. Filter to allocations with `status IN ["ALLOCATED", "PICKING", "PACKING", "READY_TO_SHIP"]`.
3. For each unique `(node_id, sku)` pair in the active allocations: send `GET /api/inventory/?node_id=<node_id>&sku=<sku>`. Record `quantity_reserved` and `quantity_available`.
4. Sum `quantity_allocated` across all active allocations for each `(node_id, sku)` pair.
5. Verify `quantity_reserved >= sum_allocated` and `quantity_available >= 0` for each pair.

**Expected Result**: For each `(node_id, sku)` pair:
- `inventory.quantity_reserved >= sum_of_active_allocations`
- `inventory.quantity_available = inventory.quantity_on_hand - inventory.quantity_reserved >= 0`
- No negative stock levels exist.

**Data Integrity Check** (SQL):
```sql
SELECT
  ii.node_id,
  ii.sku,
  ii.quantity_on_hand,
  ii.quantity_reserved,
  ii.quantity_available,
  COALESCE(SUM(fa.quantity_allocated), 0) AS active_allocations
FROM inventory_items ii
LEFT JOIN fulfillment_allocations fa
  ON fa.node_id = ii.node_id
  AND fa.sku = ii.sku
  AND fa.status NOT IN ('CANCELLED', 'RELEASED')
  AND fa.order_id = '<ORDER_SOURCED_ID>'
GROUP BY ii.id;
```
All rows must satisfy:
- `quantity_available >= 0`
- `quantity_reserved >= active_allocations`
- `quantity_available = quantity_on_hand - quantity_reserved`

---

## Appendix A — HTTP Status Code Reference

| Code | Meaning in KubeRiva OMS |
|------|------------------------|
| 200 | Successful read or update |
| 201 | Successful resource creation |
| 204 | Successful deletion (empty response body) |
| 400 | Business logic violation (e.g. cancel a SHIPPED order, approve a non-PENDING order) |
| 401 | Missing or invalid JWT token (missing `Authorization` header or expired token) |
| 403 | Valid token but insufficient role (e.g. regular user accessing superadmin endpoint; superadmin attempting platform-owner action) |
| 404 | Resource not found (order, brand, node, account, connector, proposal) |
| 409 | Conflict (duplicate slug, duplicate node code, brand has linked children, proposal in wrong state) |
| 422 | Schema validation error (Pydantic model failed — `detail` is an array of `{loc, msg, type}` objects) |
| 429 | Rate limit exceeded (60 requests/minute on order creation) |
| 500 | Internal server error |
| 501 | Feature not yet implemented (e.g. `apply` on non-sourcing_rule proposal type) |

---

## Appendix B — Enum Quick Reference

**OrderStatus** (lifecycle order): `PENDING` | `CONFIRMED` | `SOURCING` | `SOURCED` | `BACKORDERED` | `PICKING` | `PACKING` | `READY_TO_SHIP` | `SHIPPED` | `PARTIALLY_SHIPPED` | `OUT_FOR_DELIVERY` | `PARTIALLY_DELIVERED` | `DELIVERED` | `READY_FOR_PICKUP` | `PICKED_UP` | `CANCELLED` | `RETURNED` | `REFUNDED` | `FAILED`

**OrderChannel**: `WEB` | `MOBILE` | `POS` | `API` | `MARKETPLACE` | `B2B` | `EDI` | `WHOLESALE`

**OrderType**: `RETAIL` | `WHOLESALE` | `B2B` | `INTERNAL`

**FulfillmentType**: `SHIP_TO_HOME` | `STORE_PICKUP` | `SHIP_FROM_STORE` | `CURBSIDE_PICKUP` | `SAME_DAY_DELIVERY` | `FREIGHT` | `DROP_SHIP`

**PaymentTerms**: `PREPAID` | `NET_15` | `NET_30` | `NET_60` | `NET_90` | `COD` | `UPON_RECEIPT`

**ApprovalStatus**: `NOT_REQUIRED` | `PENDING` | `APPROVED` | `REJECTED`

**BrandTenantMode**: `B2C_ONLY` | `B2B_ONLY` | `HYBRID`

**InventoryMode**: `SHARED` | `ISOLATED`

**AccountType**: `PROSPECT` | `ACTIVE` | `INACTIVE` | `ON_HOLD`

**PricingTier**: `STANDARD` | `BRONZE` | `SILVER` | `GOLD` | `PLATINUM`

**SourcingStrategy**: `DISTANCE_OPTIMAL` | `COST_OPTIMAL` | `STORE_NEAREST` | `INVENTORY_RESERVATION` | `LEAST_COST_SPLIT` | `AI_ADAPTIVE` | `AI_HYBRID`

**InventoryAdjustmentReason**: `RECEIVED` | `SOLD` | `RETURNED` | `DAMAGED` | `CYCLE_COUNT` | `TRANSFER_IN` | `TRANSFER_OUT` | `RESERVED` | `RESERVATION_RELEASED` | `CORRECTION`

**NodeType**: `DISTRIBUTION_CENTER` | `RETAIL_STORE` | `DARK_STORE` | `WAREHOUSE` | `PICKUP_POINT`

**NodeStatus**: `ACTIVE` | `INACTIVE` | `MAINTENANCE` | `CLOSED`

**ConnectorType**: `SHOPIFY` | `WOOCOMMERCE` | `AMAZON_SP` | `MAGENTO` | `BIGCOMMERCE` | `FEDEX` | `UPS` | `DHL` | `CUSTOM`

**ProposalStatus**: `pending` | `approved` | `rejected` | `applied` | `rolled_back`

**ProposalType**: `sourcing_rule` | `custom_attribute` | `schema_migration` | `ui_widget` | `config_change` | `sourcing_experiment`

**AI Thresholds** (for interpreting AI behavior):
- `MIN_CLUSTER_SAMPLES = 50` — minimum sourcing outcome samples per cluster_key before AI can use a pattern
- `MIN_AI_SAMPLES = 10` — minimum samples before AI_ADAPTIVE considers using Claude Haiku scoring
- `MIN_IMPROVEMENT_PCT = 10%` — minimum improvement a pattern must show to be proposed
- Cluster key format: `brand_slug|channel|region|amount_bucket|fulfillment_type`

---

## Appendix C — Test Case Count Summary

| Area | Test Case IDs | Count | P0 | P1 | P2 |
|------|--------------|-------|----|----|-----|
| Brand CRUD and Config | TC-BRAND-001 to TC-BRAND-005 | 5 | 1 | 4 | 0 |
| B2C Order Flows | TC-B2C-001 to TC-B2C-008 | 8 | 1 | 7 | 0 |
| B2B Order Flows | TC-B2B-001 to TC-B2B-008 | 8 | 3 | 5 | 0 |
| Multi-Brand Isolation | TC-ISO-001 to TC-ISO-006 | 6 | 0 | 6 | 0 |
| AI-Native Sourcing | TC-AI-001 to TC-AI-005 | 5 | 0 | 2 | 3 |
| Inventory and Nodes | TC-INV-001 to TC-INV-004 | 4 | 0 | 4 | 0 |
| Platform and RBAC | TC-PLAT-001 to TC-PLAT-004 | 4 | 1 | 3 | 0 |
| Connectors | TC-CONN-001 to TC-CONN-003 | 3 | 0 | 0 | 3 |
| Search and Monitoring | TC-SRCH-001 to TC-SRCH-003 | 3 | 0 | 0 | 3 |
| Audit and Data Integrity | TC-AUDIT-001 to TC-AUDIT-003 | 3 | 1 | 2 | 0 |
| **Total** | | **49** | **7** | **33** | **9** |

**Recommended execution order**: Smoke Tests (5) → Brand (5) → B2C (8) → B2B (8) → Isolation (6) → Inventory (4) → Platform (4) → AI (5) → Connectors (3) → Search (3) → Audit (3).

---

## B2B Phases 1-5 Test Cases (added 2026-05-08)

**Scope**: Covers Phase 1 (credit limit enforcement), Phase 2 (pricing tier discounts), Phase 3 (approval workflow), Phase 4 (invoice lifecycle), and Phase 5 (B2B analytics data endpoints).

**Base URL**: `http://localhost:8001` (direct API, no nginx proxy)

**Auth**: `POST /auth/login` body `{"email":"admin@example.com","password":"admin123"}` → capture `access_token`. All requests use `Authorization: Bearer <TOKEN>`.

**Test data setup order**: Create account ACCT-A (credit_limit=1000, STANDARD tier, approval_threshold=5000) → Create account ACCT-B (credit_limit=500, SILVER tier, approval_threshold=200) → Create account ACCT-C (credit_limit=2000, GOLD tier, no approval_threshold) → Create account ACCT-D (credit_limit=2000, PLATINUM tier, approval_threshold=100).

---

### TC-B2B-P1-01: Credit limit enforcement — order creation reserves credit_used

- **Phase**: 1
- **Priority**: P0
- **Precondition**: Customer account ACCT-A exists with `credit_limit=1000.00`, `credit_used=0.00`, `pricing_tier=STANDARD`
- **Action**: `POST /orders/` with `customer_account_id=<ACCT-A-id>`, `order_type=B2B`, one line item `unit_price=400, quantity=1` (total = 400.00)
- **Expected**: HTTP 201; returned order has `order_type=B2B`; subsequent `GET /customers/<ACCT-A-id>` shows `credit_used=400.00`
- **Failure indicator**: `credit_used` unchanged after order creation, or non-201 status

---

### TC-B2B-P1-02: Credit limit enforcement — order creation within remaining headroom

- **Phase**: 1
- **Priority**: P0
- **Precondition**: ACCT-A already has `credit_used=400.00` (from TC-B2B-P1-01), `credit_limit=1000.00`
- **Action**: `POST /orders/` linked to ACCT-A with total = 500.00 (400 + 500 = 900 ≤ 1000 — should succeed)
- **Expected**: HTTP 201; `GET /customers/<ACCT-A-id>` shows `credit_used=900.00`
- **Failure indicator**: 422 returned when credit was available

---

### TC-B2B-P1-03: Credit limit enforcement — order exceeding credit_limit returns 422

- **Phase**: 1
- **Priority**: P0
- **Precondition**: ACCT-A has `credit_used=900.00`, `credit_limit=1000.00` (after TC-B2B-P1-01 + 02)
- **Action**: `POST /orders/` linked to ACCT-A with total = 200.00 (900 + 200 = 1100 > 1000)
- **Expected**: HTTP 422; response body contains `"Credit limit exceeded"`
- **Failure indicator**: Order accepted (201) or wrong error code

---

### TC-B2B-P1-04: Credit limit release on B2B order cancellation

- **Phase**: 1
- **Priority**: P0
- **Precondition**: A B2B order linked to ACCT-A exists with `total_amount=400.00`; ACCT-A `credit_used=400.00` (clean state — use the order from TC-B2B-P1-01 or create fresh)
- **Action**: `POST /orders/<order-id>/cancel` with body `{"reason":"Test cancellation"}`
- **Expected**: HTTP 200; `GET /customers/<ACCT-A-id>` shows `credit_used` decreased by 400.00 (back to 0.00 or previous value minus 400)
- **Failure indicator**: `credit_used` unchanged after cancellation

---

### TC-B2B-P1-05: Credit limit null means unlimited — no 422 on large order

- **Phase**: 1
- **Priority**: P1
- **Precondition**: Create account ACCT-UNLIM with `credit_limit=null` (omit field or send null), `credit_used=0`
- **Action**: `POST /orders/` linked to ACCT-UNLIM with total = 999999.00
- **Expected**: HTTP 201; order created regardless of amount (no credit ceiling enforced)
- **Failure indicator**: 422 returned for unlimited account

---

### TC-B2B-P2-01: STANDARD tier — 0% discount, prices unchanged

- **Phase**: 2
- **Priority**: P1
- **Precondition**: Account ACCT-A with `pricing_tier=STANDARD`
- **Action**: `POST /orders/` linked to ACCT-A with one line item `unit_price=100.00, quantity=2` (gross=200), no item-level discount
- **Expected**: HTTP 201; `total_amount=200.00` (no tier discount); `metadata.pricing_tier_applied=STANDARD`
- **Failure indicator**: total_amount != 200.00, or `pricing_tier_applied` absent from metadata

---

### TC-B2B-P2-02: SILVER tier — 5% discount applied to subtotal

- **Phase**: 2
- **Priority**: P1
- **Precondition**: Account ACCT-B with `pricing_tier=SILVER`, sufficient credit headroom (ensure credit_used=0 before test)
- **Action**: `POST /orders/` linked to ACCT-B with one line item `unit_price=200.00, quantity=1` (gross=200), no item discount, no shipping, no order-level discount
- **Expected**: HTTP 201; `total_amount=190.00` (200 × 0.95 = 190); `metadata.pricing_tier_applied=SILVER`
- **Failure indicator**: total_amount != 190.00

---

### TC-B2B-P2-03: GOLD tier — 10% discount applied to subtotal

- **Phase**: 2
- **Priority**: P1
- **Precondition**: Account ACCT-C with `pricing_tier=GOLD`, `credit_used=0`
- **Action**: `POST /orders/` linked to ACCT-C with one line item `unit_price=300.00, quantity=1` (gross=300), no discounts, no shipping
- **Expected**: HTTP 201; `total_amount=270.00` (300 × 0.90 = 270); `metadata.pricing_tier_applied=GOLD`
- **Failure indicator**: total_amount != 270.00

---

### TC-B2B-P2-04: PLATINUM tier — 15% discount applied to subtotal

- **Phase**: 2
- **Priority**: P1
- **Precondition**: Account ACCT-D with `pricing_tier=PLATINUM`, `approval_threshold=100`, `credit_used=0`
- **Action**: `POST /orders/` linked to ACCT-D with one line item `unit_price=100.00, quantity=1` (gross=100 × 0.85 = 85 — below approval_threshold so approval not triggered)
- **Expected**: HTTP 201; `total_amount=85.00`; `metadata.pricing_tier_applied=PLATINUM`
- **Failure indicator**: total_amount != 85.00 or pricing_tier_applied missing

---

### TC-B2B-P3-01: Orders below approval_threshold get approval_status=NOT_REQUIRED

- **Phase**: 3
- **Priority**: P0
- **Precondition**: Account ACCT-B with `approval_threshold=200.00`, `credit_used=0`
- **Action**: `POST /orders/` linked to ACCT-B with total < 200 (e.g. one line item `unit_price=50, quantity=1`, SILVER discount → 47.50)
- **Expected**: HTTP 201; `approval_status=NOT_REQUIRED`
- **Failure indicator**: approval_status=PENDING for an order below threshold

---

### TC-B2B-P3-02: Orders above approval_threshold get approval_status=PENDING

- **Phase**: 3
- **Priority**: P0
- **Precondition**: Account ACCT-B with `approval_threshold=200.00`, sufficient credit
- **Action**: `POST /orders/` linked to ACCT-B with total > 200 (e.g. `unit_price=300, quantity=1`, SILVER tier → 285.00)
- **Expected**: HTTP 201; `approval_status=PENDING`
- **Failure indicator**: approval_status=NOT_REQUIRED for order above threshold

---

### TC-B2B-P3-03: Approving a PENDING order changes approval_status to APPROVED

- **Phase**: 3
- **Priority**: P0
- **Precondition**: A B2B order exists with `approval_status=PENDING` (from TC-B2B-P3-02 or fresh order above ACCT-B threshold)
- **Action**: `POST /orders/<order-id>/approve` with body `{"approved":true,"notes":"Approved by QA"}`
- **Expected**: HTTP 200; response shows `approval_status=APPROVED`; `approved_at` is non-null
- **Failure indicator**: 400 or approval_status unchanged

---

### TC-B2B-P3-04: Rejecting a PENDING order changes approval_status to REJECTED

- **Phase**: 3
- **Priority**: P1
- **Precondition**: A separate B2B order with `approval_status=PENDING` (create a new one above threshold)
- **Action**: `POST /orders/<order-id>/approve` with body `{"approved":false,"notes":"Rejected by QA"}`
- **Expected**: HTTP 200; response shows `approval_status=REJECTED`
- **Failure indicator**: approval_status not REJECTED

---

### TC-B2B-P3-05: Attempting to approve a non-PENDING order returns 400

- **Phase**: 3
- **Priority**: P1
- **Precondition**: A B2B order with `approval_status=NOT_REQUIRED` or `APPROVED`
- **Action**: `POST /orders/<order-id>/approve` with body `{"approved":true}`
- **Expected**: HTTP 400; response body references the current approval_status
- **Failure indicator**: 200 returned, or order approval_status silently mutated

---

### TC-B2B-P4-01: GET /invoices/ requires authentication

- **Phase**: 4
- **Priority**: P0
- **Precondition**: No token provided
- **Action**: `GET /invoices/` with no `Authorization` header
- **Expected**: HTTP 401
- **Failure indicator**: 200 returned without auth

---

### TC-B2B-P4-02: POST /invoices/from-order/{order_id} auto-creates invoice for B2B order

- **Phase**: 4
- **Priority**: P0
- **Precondition**: A delivered B2B order linked to ACCT-C exists (or any B2B order — the endpoint does not gate on DELIVERED status per router code); order has `customer_account_id` set
- **Action**: `POST /invoices/from-order/<order-id>`
- **Expected**: HTTP 201; response contains `invoice_number` (format INV-YYYYMM-XXXXXX), `status=DRAFT`, `customer_account_id=<ACCT-C-id>`, `total_amount` matches order total
- **Failure indicator**: 400/404 or invoice_number absent

---

### TC-B2B-P4-03: POST /invoices/from-order/{order_id} is idempotent

- **Phase**: 4
- **Priority**: P1
- **Precondition**: An invoice already exists for the order (from TC-B2B-P4-02)
- **Action**: `POST /invoices/from-order/<same-order-id>` (second call)
- **Expected**: HTTP 201; `invoice_number` identical to the first call's result (same invoice returned)
- **Failure indicator**: A new invoice with a different invoice_number created, or error returned

---

### TC-B2B-P4-04: PATCH /invoices/{id}/status — transition DRAFT to SENT

- **Phase**: 4
- **Priority**: P1
- **Precondition**: Invoice from TC-B2B-P4-02 exists with `status=DRAFT`
- **Action**: `PATCH /invoices/<invoice-id>/status` with body `{"status":"SENT"}`
- **Expected**: HTTP 200; response shows `status=SENT`; `paid_date` is null (not paid yet)
- **Failure indicator**: Status not updated, or paid_date set prematurely

---

### TC-B2B-P4-05: PATCH /invoices/{id}/status — transition SENT to PAID releases credit_used

- **Phase**: 4
- **Priority**: P0
- **Precondition**: Invoice from TC-B2B-P4-04 with `status=SENT`; record ACCT-C `credit_used` before this call
- **Action**: `PATCH /invoices/<invoice-id>/status` with body `{"status":"PAID"}`
- **Expected**: HTTP 200; `status=PAID`; `paid_date` set to today's date; `GET /customers/<ACCT-C-id>` shows `credit_used` decreased by invoice `total_amount`
- **Failure indicator**: paid_date null, credit_used unchanged, or wrong status

---

### TC-B2B-P4-06: GET /invoices/account/{account_id} returns only that account's invoices

- **Phase**: 4
- **Priority**: P1
- **Precondition**: At least one invoice exists for ACCT-C; no invoice for ACCT-A (or create invoices for both)
- **Action**: `GET /invoices/account/<ACCT-C-id>`
- **Expected**: HTTP 200; all items in `items[]` have `customer_account_id` equal to ACCT-C id; items from other accounts absent
- **Failure indicator**: Invoices from other accounts included, or empty list despite known invoices

---

### TC-B2B-P5-01: GET /invoices/?page_size=500 returns list structure for analytics

- **Phase**: 5
- **Priority**: P1
- **Precondition**: At least one invoice exists in the system
- **Action**: `GET /invoices/?page_size=500` (note: router caps page_size at 100 — use 100 instead)
- **Action (corrected)**: `GET /invoices/?page_size=100`
- **Expected**: HTTP 200; response has `items`, `total`, `page`, `page_size`, `total_pages` fields; `items` is an array (possibly empty)
- **Failure indicator**: Non-200, missing pagination fields, or items not an array

---

### TC-B2B-P5-02: GET /customers/ returns accounts with credit_limit and credit_used fields

- **Phase**: 5
- **Priority**: P1
- **Precondition**: At least ACCT-A, ACCT-B, ACCT-C exist
- **Action**: `GET /customers/`
- **Expected**: HTTP 200; `items[]` present; each item contains `credit_limit` and `credit_used` numeric fields; `total` > 0
- **Failure indicator**: Fields absent, 401/403, or empty list

---

### TC-B2B-P5-03: GET /orders/?order_type=B2B returns only B2B orders

- **Phase**: 5
- **Priority**: P1
- **Precondition**: At least one B2B order and one RETAIL order exist
- **Action**: `GET /orders/?order_type=B2B&page_size=100`
- **Expected**: HTTP 200; all items in `items[]` have `order_type=B2B`; no RETAIL orders included
- **Failure indicator**: RETAIL orders appear in results, or 422 from invalid filter value

---

## TC-B2C-SPRINT2 — B2C Core Features Sprint

**Date**: 2026-05-09
**Branch**: feature/shopify-app-store
**Base URL**: `http://localhost:8001` (direct API)
**Auth**: `POST /auth/login` body `{"email":"admin@oms.local","password":"admin123"}`
**PaymentStatus enum values**: `PENDING`, `AUTHORIZED`, `CAPTURED`, `FAILED`, `REFUNDED`, `PARTIALLY_REFUNDED`
**ReturnStatus enum values**: `REQUESTED`, `APPROVED`, `REJECTED`, `IN_TRANSIT`, `RECEIVED`, `RESTOCKED`, `COMPLETED`
**ReturnReason enum values**: `DEFECTIVE`, `WRONG_ITEM`, `NOT_AS_DESCRIBED`, `CHANGED_MIND`, `DUPLICATE_ORDER`, `DAMAGED_IN_TRANSIT`, `OTHER`
**RefundMethod enum values**: `ORIGINAL_PAYMENT`, `STORE_CREDIT`, `BANK_TRANSFER`, `CHECK`, `OTHER`

> **Bug found and fixed**: `POST /api/customers/profiles/` returned HTTP 500 due to SQLAlchemy
> `MissingGreenlet` error -- the `CustomerProfileResponse` Pydantic model validator accessed the
> `addresses` lazy relationship outside an async greenlet context. Fix: replaced `db.refresh()`
> with a `selectinload(CustomerProfile.addresses)` query in `create_customer_profile`,
> `update_customer_profile`, `sync_customer_stats`, and `list_customer_profiles`.
> The `get_customer_orders` endpoint had the same issue for Order relationships -- fixed with
> `selectinload` on `line_items`, `fulfillment_allocations`, and `shipments`.
> File: `app/routers/customer_profiles.py`

---

### RMA / Returns Endpoints

#### TC-RET-AUTH-01: GET /api/returns/ without token

- **Priority**: P0
- **Action**: `GET /api/returns/` -- no Authorization header
- **Expected**: HTTP 401
- **Result**: PASS (HTTP 401)

#### TC-RET-AUTH-02: POST /api/returns/ without token

- **Priority**: P0
- **Action**: `POST /api/returns/` -- no Authorization header
- **Expected**: HTTP 401
- **Result**: PASS (HTTP 401)

#### TC-RET-01: Create return request -- happy path

- **Priority**: P1
- **Precondition**: Order `042bf8b7-3390-4d06-bb9d-eb818d0eeea6` (DELIVERED, total=540.00) exists with line item `34860c9e-3743-4926-bd92-c51a831b63a9` (SKU: CBL-HDMI-031)
- **Action**: `POST /api/returns/` with order_id, reason=DEFECTIVE, customer_notes, and one item with restock=true
- **Expected**: HTTP 201; response has `id`, `return_number` matching `RMA-{YYYYMM}-{6hex}`, `status: REQUESTED`, `reason: DEFECTIVE`, one item, `refund: null`
- **Result**: PASS -- returned `RMA-202605-118012`, status REQUESTED, item correctly linked

#### TC-RET-02: Create return for non-existent order

- **Priority**: P1
- **Action**: `POST /api/returns/` with `order_id: 00000000-0000-0000-0000-000000000000`
- **Expected**: HTTP 404
- **Result**: PASS (HTTP 404)

#### TC-RET-03: Create return with empty items array

- **Priority**: P1
- **Action**: `POST /api/returns/` with `items: []`
- **Expected**: HTTP 422; type too_short min_length=1
- **Result**: PASS (HTTP 422)

#### TC-RET-04: Create return with invalid reason enum

- **Priority**: P1
- **Action**: `POST /api/returns/` with `reason: INVALID_REASON`
- **Expected**: HTTP 422; enum validation error
- **Result**: PASS (HTTP 422)

#### TC-RET-05: Get return by ID -- happy path

- **Priority**: P1
- **Action**: `GET /api/returns/{return_id}`
- **Expected**: HTTP 200; status, items, return_number present
- **Result**: PASS

#### TC-RET-06: Get non-existent return

- **Priority**: P1
- **Action**: `GET /api/returns/00000000-0000-0000-0000-000000000000`
- **Expected**: HTTP 404
- **Result**: PASS (HTTP 404)

#### TC-RET-07: List returns -- no filter

- **Priority**: P2
- **Action**: `GET /api/returns/`
- **Expected**: HTTP 200; `{items: [...], total: N}`
- **Result**: PASS -- total: 1

#### TC-RET-08: List returns filtered by order_id

- **Priority**: P2
- **Action**: `GET /api/returns/?order_id={id}`
- **Expected**: HTTP 200; all items belong to that order
- **Result**: PASS -- total: 1

#### TC-RET-09: List returns filtered by status

- **Priority**: P2
- **Action**: `GET /api/returns/?status=REQUESTED`
- **Expected**: HTTP 200; all items have status REQUESTED
- **Result**: PASS

#### TC-RET-10: Update return status to APPROVED

- **Priority**: P1
- **Action**: `PATCH /api/returns/{id}/status` with `{status: APPROVED, staff_notes: ...}`
- **Expected**: HTTP 200; status APPROVED, staff_notes persisted
- **Result**: PASS

#### TC-RET-11: Update return status to IN_TRANSIT with tracking

- **Priority**: P2
- **Action**: `PATCH /api/returns/{id}/status` with status=IN_TRANSIT, tracking number, carrier
- **Expected**: HTTP 200; tracking and carrier persisted
- **Result**: PASS

#### TC-RET-12: Update return status to RECEIVED -- sets received_at

- **Priority**: P1
- **Action**: `PATCH /api/returns/{id}/status` with `{status: RECEIVED}`
- **Expected**: HTTP 200; status=RECEIVED, received_at timestamp populated
- **Result**: PASS

#### TC-RET-14: Update return status to RESTOCKED -- triggers inventory adjustment

- **Priority**: P1
- **Action**: `PATCH /api/returns/{id}/status` with `{status: RESTOCKED}`
- **Expected**: HTTP 200; status=RESTOCKED, restocked_at set; inventory RETURNED adjustment created for items with restock=true
- **Result**: PASS -- restocked_at populated; restock logic executed

#### TC-RET-EDGE-01: Create return without required reason field

- **Priority**: P1
- **Action**: `POST /api/returns/` omitting reason
- **Expected**: HTTP 422
- **Result**: PASS (HTTP 422)

---

### Return Refund Endpoints

#### TC-RET-15: Create refund for return -- happy path

- **Priority**: P1
- **Action**: `POST /api/returns/{return_id}/refund` with method=ORIGINAL_PAYMENT, amount=540.00
- **Expected**: HTTP 201; refund_number matches `REF-{YYYYMM}-{6hex}`, status=PENDING, return_id linked
- **Result**: PASS -- REF-202605-B08863 created

#### TC-RET-16: Duplicate refund blocked

- **Priority**: P1
- **Precondition**: Return already has a refund
- **Action**: `POST /api/returns/{return_id}/refund` again
- **Expected**: HTTP 400; error message about existing refund
- **Result**: PASS (HTTP 400)

#### TC-RET-17: Refund amount exceeds order total

- **Priority**: P1
- **Action**: `POST /api/returns/{return_id}/refund` with amount=99999.00 on order total=270.00
- **Expected**: HTTP 400
- **Result**: PASS (HTTP 400)

#### TC-RET-18: Get refund for return

- **Priority**: P2
- **Action**: `GET /api/returns/{return_id}/refund`
- **Expected**: HTTP 200; refund details
- **Result**: PASS -- REF-202605-B08863, amount=540.00, method=ORIGINAL_PAYMENT

#### TC-RET-19: Get refund for return with no refund

- **Priority**: P2
- **Action**: `GET /api/returns/{return_id}/refund` on return without refund
- **Expected**: HTTP 404
- **Result**: PASS (HTTP 404)

---

### Standalone Order Refunds

#### TC-REF-AUTH-01: POST /api/orders/{id}/refunds without token

- **Priority**: P0
- **Result**: PASS (HTTP 401)

#### TC-REF-01: Create courtesy refund on order -- happy path

- **Priority**: P1
- **Precondition**: Order in PENDING status, total=170.62
- **Action**: `POST /api/orders/{order_id}/refunds` with method=STORE_CREDIT, amount=15.00
- **Expected**: HTTP 201; return_id is null (no associated return), status=PENDING
- **Result**: PASS -- REF-202605-6ECFB7, return_id=null

#### TC-REF-02: Courtesy refund exceeds order total

- **Priority**: P1
- **Action**: amount=99999.00 on order with total=170.62
- **Expected**: HTTP 400
- **Result**: PASS (HTTP 400)

#### TC-REF-03: Refund on non-existent order

- **Priority**: P1
- **Expected**: HTTP 404
- **Result**: PASS (HTTP 404)

#### TC-REF-04: List refunds on order

- **Priority**: P2
- **Action**: `GET /api/orders/{order_id}/refunds`
- **Expected**: HTTP 200; array of refund objects
- **Result**: PASS -- 1 refund returned

#### TC-REF-05: List refunds on order with no refunds

- **Priority**: P2
- **Expected**: HTTP 200; empty array []
- **Result**: PASS

#### TC-REF-EDGE-01: Refund amount=0 rejected by gt=0 validator

- **Priority**: P2
- **Expected**: HTTP 422; type greater_than
- **Result**: PASS (HTTP 422)

#### TC-REF-EDGE-02: Refund with negative amount

- **Priority**: P2
- **Expected**: HTTP 422
- **Result**: PASS (HTTP 422)

---

### Payment Status Lifecycle

#### TC-PAY-AUTH-01: PATCH /orders/{id}/payment-status without token

- **Priority**: P0
- **Result**: PASS (HTTP 401)

#### TC-PAY-01: Update payment status PENDING to CAPTURED

- **Priority**: P1
- **Action**: `PATCH /orders/{order_id}/payment-status` with `{payment_status: CAPTURED, transaction_id: TXN-STRIPE-99999}`
- **Expected**: HTTP 200; payment_status=CAPTURED in response
- **Note**: Valid enum values are PENDING, AUTHORIZED, CAPTURED, FAILED, REFUNDED, PARTIALLY_REFUNDED. `PAID` is NOT a valid value.
- **Result**: PASS

#### TC-PAY-02: Update payment status to PARTIALLY_REFUNDED

- **Priority**: P2
- **Result**: PASS (HTTP 200, payment_status=PARTIALLY_REFUNDED)

#### TC-PAY-03: Update payment status to REFUNDED

- **Priority**: P2
- **Result**: PASS (HTTP 200, payment_status=REFUNDED)

#### TC-PAY-04: Invalid payment status enum

- **Priority**: P1
- **Expected**: HTTP 422; enum validation error with valid values listed
- **Result**: PASS (HTTP 422)

#### TC-PAY-05: Payment status on non-existent order

- **Priority**: P1
- **Action**: Use valid UUID format (not all-zeros) that does not exist in DB
- **Expected**: HTTP 404
- **Result**: PASS (HTTP 404)

#### TC-PAY-EDGE-01: Idempotent payment status update

- **Priority**: P2
- **Action**: Set same status that is already set
- **Expected**: HTTP 200; no error
- **Result**: PASS

---

### Order Edit

#### TC-EDIT-AUTH-01: PATCH /orders/{id} without token

- **Priority**: P0
- **Result**: PASS (HTTP 401)

#### TC-EDIT-01: Edit shipping address on CONFIRMED order

- **Priority**: P1
- **Action**: `PATCH /orders/{order_id}` with customer_name, shipping_address1, shipping_city, etc.
- **Expected**: HTTP 200; fields updated
- **Result**: PASS

#### TC-EDIT-02: Edit notes on PENDING order

- **Priority**: P2
- **Expected**: HTTP 200; notes updated
- **Result**: PASS

#### TC-EDIT-03: Edit DELIVERED order blocked

- **Priority**: P1
- **Expected**: HTTP 422; "Order cannot be edited in DELIVERED status"
- **Result**: PASS

#### TC-EDIT-04: Edit CANCELLED order blocked

- **Priority**: P1
- **Expected**: HTTP 422
- **Result**: PASS

#### TC-EDIT-05: Edit PICKING order -- not blocked

- **Priority**: P1
- **Expected**: HTTP 200; status remains PICKING, notes updated
- **Result**: PASS

#### TC-EDIT-06: Empty PATCH returns current order unchanged

- **Priority**: P2
- **Action**: `PATCH /orders/{order_id}` with `{}`
- **Expected**: HTTP 200
- **Result**: PASS

#### TC-EDIT-07: Extra fields rejected (extra=forbid)

- **Priority**: P1
- **Action**: `PATCH /orders/{order_id}` with `{status: CANCELLED, total_amount: 0.00}`
- **Expected**: HTTP 422; extra_forbidden for each extra field
- **Result**: PASS

#### TC-EDIT-08: Invalid email in patch

- **Priority**: P2
- **Action**: `PATCH /orders/{order_id}` with `{customer_email: not-an-email}`
- **Expected**: HTTP 422; EmailStr validation error
- **Result**: PASS

---

### B2C Customer Profiles

#### TC-CUST-AUTH-01: GET /api/customers/profiles/ without token

- **Priority**: P0
- **Result**: PASS (HTTP 401)

#### TC-CUST-01: Create customer profile -- happy path

- **Priority**: P1
- **Action**: `POST /api/customers/profiles/` with email, first_name, last_name, tags, opt-ins
- **Expected**: HTTP 201; id, email (lowercased), tags, addresses=[] returned
- **Result**: PASS (after BUG-CUST-01 fix)

#### TC-CUST-02: Duplicate email (no brand_id) -- conflict

- **Priority**: P1
- **Expected**: HTTP 409; "A profile with this email already exists for the given brand."
- **Result**: PASS

#### TC-CUST-03: Same email different brand_id -- separate profiles allowed

- **Priority**: P1
- **Action**: Create profile with email+null brand; create again with same email+brand_id; try third with same email+same brand_id
- **Expected**: First two HTTP 201; third HTTP 409
- **Result**: PASS -- unique constraint uq_customer_email_brand works correctly

#### TC-CUST-04: Create profile with invalid email

- **Priority**: P1
- **Expected**: HTTP 422
- **Result**: PASS

#### TC-CUST-05: List profiles

- **Priority**: P2
- **Expected**: HTTP 200; {items, total}
- **Result**: PASS

#### TC-CUST-06: Get profile by ID -- addresses included

- **Priority**: P1
- **Expected**: HTTP 200; addresses array present
- **Result**: PASS

#### TC-CUST-07: Get non-existent profile

- **Priority**: P1
- **Expected**: HTTP 404
- **Result**: PASS

#### TC-CUST-08: Update profile (PATCH)

- **Priority**: P1
- **Action**: Update first_name, sms_opt_in, tags
- **Expected**: HTTP 200; fields updated
- **Result**: PASS

#### TC-CUST-09: Email is immutable -- not in PATCH schema

- **Priority**: P1
- **Action**: PATCH with email field
- **Expected**: Email field silently ignored; GET shows original email unchanged
- **Result**: PASS

#### TC-CUST-10: Add address to profile

- **Priority**: P1
- **Action**: `POST /api/customers/profiles/{id}/addresses` with full address + is_default=true
- **Expected**: HTTP 201; address with is_default=true returned
- **Result**: PASS

#### TC-CUST-11: Get profile shows populated addresses

- **Priority**: P1
- **Expected**: HTTP 200; addresses count=1
- **Result**: PASS

#### TC-CUST-12: Add second non-default address

- **Priority**: P2
- **Expected**: HTTP 201; is_default=false
- **Result**: PASS

#### TC-CUST-13: List addresses for profile

- **Priority**: P2
- **Action**: `GET /api/customers/profiles/{id}/addresses`
- **Expected**: HTTP 200; ordered default-first
- **Result**: PASS -- 2 addresses

#### TC-CUST-14: Promote address to default -- demotes previous

- **Priority**: P1
- **Action**: PATCH address with is_default=true
- **Expected**: Promoted address is_default=true; previous default is_default=false
- **Result**: PASS

#### TC-CUST-15: Add address with missing required fields

- **Priority**: P1
- **Expected**: HTTP 422
- **Result**: PASS

#### TC-CUST-16: Order history -- no matching orders

- **Priority**: P2
- **Expected**: HTTP 200; empty array
- **Result**: PASS (0 orders for test email)

#### TC-CUST-17: Order history -- email matches existing orders

- **Priority**: P1
- **Precondition**: Profile email kirankls@gmail.com has 4 existing orders
- **Expected**: HTTP 200; 4 orders with line_items, fulfillment_allocations, shipments loaded
- **Result**: PASS (after BUG-CUST-02 fix for Order lazy-load)

#### TC-CUST-18: Auth required for profiles

- **Priority**: P0
- **Result**: PASS (HTTP 401)

#### TC-CUST-19: List profiles filtered by email substring

- **Priority**: P2
- **Action**: `GET /api/customers/profiles/?email=alice`
- **Expected**: Only profiles with email containing alice
- **Result**: PASS -- 1 result

#### TC-CUST-20: List profiles filtered by is_active=false

- **Priority**: P2
- **Expected**: HTTP 200; only inactive profiles
- **Result**: PASS

#### TC-CUST-21: Delete address (hard delete)

- **Priority**: P1
- **Action**: `DELETE /api/customers/profiles/{id}/addresses/{addr_id}`
- **Expected**: HTTP 204; address removed from list
- **Result**: PASS (HTTP 204; count went from 2 to 1)

#### TC-CUST-22: Soft delete profile (superadmin required)

- **Priority**: P1
- **Action**: `DELETE /api/customers/profiles/{id}`
- **Expected**: HTTP 204; GET returns profile with is_active=false
- **Result**: PASS

#### TC-CUST-23: List profiles filtered by tags (OR logic)

- **Priority**: P2
- **Action**: `GET /api/customers/profiles/?tags=vip&tags=wholesale`
- **Expected**: Profiles having ANY of the tags
- **Result**: PASS -- 2 results

---

### Test Run Summary -- TC-B2C-SPRINT2

| Category | Total | PASS | FAIL | DEFECT |
|---|---|---|---|---|
| Auth guards (401) | 6 | 6 | 0 | 0 |
| RMA / Returns | 13 | 13 | 0 | 0 |
| Return Refunds | 5 | 5 | 0 | 0 |
| Standalone Refunds | 7 | 7 | 0 | 0 |
| Payment Status | 7 | 7 | 0 | 0 |
| Order Edit | 9 | 9 | 0 | 0 |
| Customer Profiles | 23 | 23 | 0 | 0 |
| **TOTAL** | **70** | **70** | **0** | **0** |

### Bugs Found and Fixed During This Run

| ID | Endpoint | Severity | Description | Fix Applied |
|---|---|---|---|---|
| BUG-CUST-01 | POST /api/customers/profiles/ | P0 Blocker | HTTP 500 MissingGreenlet -- CustomerProfileResponse._normalise accessed addresses lazy relationship outside async greenlet | Added _load_profile() helper with selectinload(CustomerProfile.addresses); updated create_customer_profile, update_customer_profile, sync_customer_stats, and list_customer_profiles |
| BUG-CUST-02 | GET /api/customers/profiles/{id}/orders | P0 Blocker | HTTP 500 MissingGreenlet -- OrderResponse.model_validate triggered lazy load of line_items, fulfillment_allocations, shipments | Added selectinload for all three Order relationships in get_customer_orders query |

### Key Observations

1. **PaymentStatus enum**: Does NOT include PAID. Correct value for a captured payment is CAPTURED. Update API docs / frontend accordingly.
2. **Return status machine**: No enforced state transitions -- any status can be set regardless of current state. Consider adding state transition validation in a future sprint (e.g., RESTOCKED requires RECEIVED first).
3. **Refund amount validation**: amount must be > 0 (gt validator). Zero and negative amounts return HTTP 422.
4. **Email immutability**: email field excluded from CustomerProfileUpdate schema -- PATCH with email field silently ignores it (no error, no change). This is correct behavior per design.
5. **Null brand_id uniqueness**: PostgreSQL treats two NULL brand_id values as distinct for the unique constraint (uq_customer_email_brand) -- multiple profiles can share an email if brand_id is NULL in different rows. This is the intended multi-brand isolation behavior.
6. **Zero UUID (00000000-...)**: FastAPI accepts all-zeros as a valid UUID path param; the handler correctly returns 404 when the record is not found.

---

## TC-SPRINT3 — Distribution Groups, Lifecycles, API Keys, Brand Access, SLA, Nodes, Custom Attributes, Worker Reliability

**Sprint**: feature/shopify-app-store — Sprint 3
**Date**: 2026-05-09
**Base URL**: `http://localhost:8001` (direct API, no nginx proxy)
**Auth**: `POST /auth/login` body `{"email":"admin@example.com","password":"admin123"}` — store `access_token` as `TOKEN`.
**Superadmin header**: `Authorization: Bearer <TOKEN>`

> **Test Data Prerequisites**: Before running these cases, ensure the following baseline data exists from the main Test Data Setup section: `NODE_EAST_ID`, `NODE_WEST_ID`, `NODE_STORE_ID`, `BRAND_A_ID`, `BRAND_B_ID`, `ENV_ID` (default production environment). A regular non-superadmin user must exist — store its `id` as `USER_ID` and its token as `USER_TOKEN`. All UUIDs below in angle brackets must be substituted with real values captured at runtime.

---

### Distribution Group CRUD (TC-DG)

#### TC-DG-01: Create distribution group — happy path

- **Priority**: P0
- **Precondition**: `NODE_EAST_ID` and `NODE_WEST_ID` exist and are ACTIVE.
- **Action**: `POST /distribution-groups/`
  ```json
  {
    "name": "East-West Split",
    "description": "Primary split between east and west DCs",
    "is_active": true,
    "brand_id": null,
    "members": [
      {"node_id": "<NODE_EAST_ID>", "priority": 1},
      {"node_id": "<NODE_WEST_ID>", "priority": 2}
    ]
  }
  ```
- **Expected**: HTTP 201. Response body contains `id` (UUID), `name = "East-West Split"`, `is_active = true`, `brand_id = null`. `members` array has 2 entries sorted by `priority` ascending: first member has `node_id = NODE_EAST_ID` and `priority = 1`, second has `node_id = NODE_WEST_ID` and `priority = 2`. Each member includes `node_name`, `node_code`, and `node_type` fields populated from the node record.
- **Store**: Returned `id` as `DG_SPLIT_ID`.

---

#### TC-DG-02: Create distribution group scoped to a brand

- **Priority**: P1
- **Precondition**: `BRAND_A_ID` exists. `NODE_STORE_ID` exists.
- **Action**: `POST /distribution-groups/`
  ```json
  {
    "name": "Brand A Stores",
    "description": "Stores serving Brand A only",
    "is_active": true,
    "brand_id": "<BRAND_A_ID>",
    "members": [{"node_id": "<NODE_STORE_ID>", "priority": 1}]
  }
  ```
- **Expected**: HTTP 201. `brand_id` in response equals `BRAND_A_ID`. `members` has 1 entry with `node_id = NODE_STORE_ID`.
- **Store**: Returned `id` as `DG_BRAND_A_ID`.

---

#### TC-DG-03: Create distribution group — non-superadmin user is rejected

- **Priority**: P0
- **Precondition**: `USER_TOKEN` belongs to a non-superadmin user.
- **Action**: `POST /distribution-groups/` with `Authorization: Bearer <USER_TOKEN>` and a valid payload (same as TC-DG-01 but different name).
- **Expected**: HTTP 403.

---

#### TC-DG-04: Create distribution group — invalid node_id returns 422

- **Priority**: P1
- **Action**: `POST /distribution-groups/` with `members: [{"node_id": "00000000-0000-0000-0000-000000000000", "priority": 1}]`.
- **Expected**: HTTP 422. `detail` contains "Node … not found".

---

#### TC-DG-05: Get distribution group by ID

- **Priority**: P0
- **Precondition**: `DG_SPLIT_ID` created in TC-DG-01.
- **Action**: `GET /distribution-groups/<DG_SPLIT_ID>`
- **Expected**: HTTP 200. `id = DG_SPLIT_ID`. `members` array length is 2. Members are sorted by `priority` ascending.

---

#### TC-DG-06: Get non-existent distribution group returns 404

- **Priority**: P1
- **Action**: `GET /distribution-groups/00000000-0000-0000-0000-000000000099`
- **Expected**: HTTP 404. `detail = "Distribution group not found"`.

---

#### TC-DG-07: List distribution groups — filter by is_active=true

- **Priority**: P1
- **Precondition**: At least one active DG and one inactive DG exist.
- **Action**: `GET /distribution-groups/?is_active=true`
- **Expected**: HTTP 200. All returned `items` have `is_active = true`. Inactive DGs are not included. Response includes `total` field.

---

#### TC-DG-08: List distribution groups — filter by brand_id

- **Priority**: P1
- **Precondition**: `DG_BRAND_A_ID` (brand = Brand A) and `DG_SPLIT_ID` (brand = null) both exist.
- **Action**: `GET /distribution-groups/?brand_id=<BRAND_A_ID>`
- **Expected**: HTTP 200. Only `DG_BRAND_A_ID` appears in `items`. `DG_SPLIT_ID` is not included.

---

#### TC-DG-09: Update distribution group — rename and deactivate

- **Priority**: P1
- **Precondition**: `DG_SPLIT_ID` exists and `is_active = true`.
- **Action**: `PATCH /distribution-groups/<DG_SPLIT_ID>`
  ```json
  {"name": "East-West Split (Retired)", "is_active": false}
  ```
- **Expected**: HTTP 200. `name = "East-West Split (Retired)"`. `is_active = false`. `members` array still present with same entries.

---

#### TC-DG-10: Delete distribution group — removes record

- **Priority**: P1
- **Precondition**: Create a temporary DG (no members) and store its `id` as `DG_TEMP_ID`.
- **Action**: `DELETE /distribution-groups/<DG_TEMP_ID>`
- **Expected**: HTTP 204. Subsequent `GET /distribution-groups/<DG_TEMP_ID>` returns HTTP 404.

---

#### TC-DG-11: Add member to distribution group

- **Priority**: P0
- **Precondition**: `DG_BRAND_A_ID` has 1 member (`NODE_STORE_ID`). A second active node exists — store as `NODE_STORE2_ID`.
- **Action**: `POST /distribution-groups/<DG_BRAND_A_ID>/members`
  ```json
  {"node_id": "<NODE_STORE2_ID>", "priority": 2}
  ```
- **Expected**: HTTP 200 (returns updated DG). `members` now contains 2 entries. New member has `priority = 2` and `node_id = NODE_STORE2_ID`.

---

#### TC-DG-12: Add duplicate member returns 409

- **Priority**: P1
- **Precondition**: `NODE_STORE_ID` is already a member of `DG_BRAND_A_ID`.
- **Action**: `POST /distribution-groups/<DG_BRAND_A_ID>/members`
  ```json
  {"node_id": "<NODE_STORE_ID>", "priority": 5}
  ```
- **Expected**: HTTP 409. `detail = "Node already in this distribution group"`.

---

#### TC-DG-13: Update member priority — reorder nodes

- **Priority**: P1
- **Precondition**: `DG_BRAND_A_ID` has `NODE_STORE_ID` at `priority = 1` and `NODE_STORE2_ID` at `priority = 2`.
- **Action**: `PATCH /distribution-groups/<DG_BRAND_A_ID>/members/<NODE_STORE_ID>` with `{"node_id": "<NODE_STORE_ID>", "priority": 10}`.
- **Expected**: HTTP 200. The member for `NODE_STORE_ID` now has `priority = 10`. The DG response `members` array is sorted ascending, so `NODE_STORE2_ID` (priority 2) appears before `NODE_STORE_ID` (priority 10).

---

#### TC-DG-14: Remove member from distribution group

- **Priority**: P1
- **Precondition**: `NODE_STORE2_ID` is a member of `DG_BRAND_A_ID`.
- **Action**: `DELETE /distribution-groups/<DG_BRAND_A_ID>/members/<NODE_STORE2_ID>`
- **Expected**: HTTP 200 (returns updated DG). `members` no longer contains an entry for `NODE_STORE2_ID`.

---

#### TC-DG-15: Remove non-existent member returns 404

- **Priority**: P1
- **Precondition**: `NODE_WEST_ID` is NOT a member of `DG_BRAND_A_ID`.
- **Action**: `DELETE /distribution-groups/<DG_BRAND_A_ID>/members/<NODE_WEST_ID>`
- **Expected**: HTTP 404. `detail = "Member not found"`.

---

#### TC-DG-16: Sourcing rule with DISTRIBUTION_GROUP target type

- **Priority**: P0
- **Precondition**: `DG_SPLIT_ID` exists (reactivate if needed via PATCH). `NODE_EAST_ID` and `NODE_WEST_ID` are both ACTIVE with inventory.
- **Action**: `POST /sourcing-rules/`
  ```json
  {
    "name": "DG Target Rule",
    "priority": 5,
    "is_active": true,
    "strategy": "DISTANCE_OPTIMAL",
    "conditions": [],
    "sourcing_targets": [
      {"type": "DISTRIBUTION_GROUP", "id": "<DG_SPLIT_ID>", "priority": 1}
    ],
    "created_by": "qa-engineer"
  }
  ```
- **Expected**: HTTP 201. `sourcing_targets` in response contains 1 entry with `type = "DISTRIBUTION_GROUP"` and `id = DG_SPLIT_ID`.

---

#### TC-DG-17: Sourcing rule with NODE target type

- **Priority**: P1
- **Action**: `POST /sourcing-rules/`
  ```json
  {
    "name": "Direct Node Rule",
    "priority": 10,
    "is_active": true,
    "strategy": "COST_OPTIMAL",
    "conditions": [],
    "sourcing_targets": [
      {"type": "NODE", "id": "<NODE_EAST_ID>", "priority": 1},
      {"type": "NODE", "id": "<NODE_WEST_ID>", "priority": 2}
    ],
    "created_by": "qa-engineer"
  }
  ```
- **Expected**: HTTP 201. `sourcing_targets` contains 2 entries, both with `type = "NODE"`.

---

#### TC-DG-18: Effective priority formula — DG member ordering

- **Priority**: P1
- **Description**: Validates the priority resolution formula: `effective_priority = target_priority * 100 + member_priority`. A DG sourcing target with `target_priority = 1` and a member with `member_priority = 5` should be preferred over a DG target with `target_priority = 2` and `member_priority = 1` (effective: 105 vs 201).
- **Precondition**: Two DGs exist. `DG_ALPHA` has target_priority 1 in a sourcing rule. `DG_BETA` has target_priority 2. `DG_ALPHA`'s member has member priority 5. `DG_BETA`'s member has member priority 1.
- **Action**: Trigger sourcing for an order matching the rule. Inspect `GET /orders/<ORDER_ID>` → `fulfillment_allocations[0].node_id`.
- **Expected**: Allocation is assigned from `DG_ALPHA`'s member node (effective priority 105) rather than `DG_BETA`'s member node (effective priority 201). The lower effective priority value wins.

---

### Lifecycle Pipeline Types (TC-LC)

#### TC-LC-01: Create ORDER lifecycle — happy path

- **Priority**: P0
- **Action**: `POST /lifecycles/`
  ```json
  {
    "name": "Standard Order Pipeline",
    "pipeline_type": "ORDER",
    "fulfillment_types": ["SHIP_TO_HOME"],
    "channels": [],
    "is_active": true,
    "is_default": false,
    "created_by": "qa-engineer",
    "steps": [
      {"status": "CONFIRMED", "label": "Confirmed", "step_order": 0, "allowed_next_statuses": ["SOURCING"], "sla_hours": 1},
      {"status": "SOURCING",  "label": "Sourcing",  "step_order": 1, "allowed_next_statuses": ["SOURCED","BACKORDERED"], "sla_hours": 2}
    ],
    "custom_statuses": []
  }
  ```
- **Expected**: HTTP 201. `pipeline_type = "ORDER"`. `steps` array has 2 entries. `id` is a UUID.
- **Store**: Returned `id` as `LC_ORDER_ID`.

---

#### TC-LC-02: Create RETURN lifecycle

- **Priority**: P0
- **Action**: `POST /lifecycles/`
  ```json
  {
    "name": "Standard Return Pipeline",
    "pipeline_type": "RETURN",
    "fulfillment_types": ["SHIP_TO_HOME"],
    "channels": [],
    "is_active": true,
    "is_default": false,
    "created_by": "qa-engineer",
    "steps": [
      {"status": "REQUESTED", "label": "Return Requested", "step_order": 0, "allowed_next_statuses": ["APPROVED","REJECTED"], "sla_hours": 24},
      {"status": "APPROVED",  "label": "Return Approved",  "step_order": 1, "allowed_next_statuses": ["IN_TRANSIT"], "sla_hours": null}
    ],
    "custom_statuses": []
  }
  ```
- **Expected**: HTTP 201. `pipeline_type = "RETURN"`. `steps[0].status = "REQUESTED"`.
- **Store**: Returned `id` as `LC_RETURN_ID`.

---

#### TC-LC-03: Create lifecycle scoped to order_type B2B

- **Priority**: P1
- **Action**: `POST /lifecycles/`
  ```json
  {
    "name": "B2B Order Lifecycle",
    "pipeline_type": "ORDER",
    "fulfillment_types": ["SHIP_TO_HOME", "FREIGHT"],
    "order_type": "B2B",
    "is_active": true,
    "is_default": false,
    "created_by": "qa-engineer",
    "steps": [{"status": "CONFIRMED", "label": "Confirmed", "step_order": 0, "allowed_next_statuses": ["SOURCING"], "sla_hours": 4}],
    "custom_statuses": []
  }
  ```
- **Expected**: HTTP 201. `order_type = "B2B"`. `fulfillment_types` contains both values.
- **Store**: Returned `id` as `LC_B2B_ID`.

---

#### TC-LC-04: Create lifecycle scoped to a brand

- **Priority**: P1
- **Precondition**: `BRAND_A_ID` exists.
- **Action**: `POST /lifecycles/`
  ```json
  {
    "name": "Brand A Premium Pipeline",
    "pipeline_type": "ORDER",
    "fulfillment_types": ["SHIP_TO_HOME"],
    "brand_id": "<BRAND_A_ID>",
    "is_active": true,
    "is_default": false,
    "created_by": "qa-engineer",
    "steps": [{"status": "CONFIRMED", "label": "Confirmed", "step_order": 0, "allowed_next_statuses": ["SOURCING"], "sla_hours": 1}],
    "custom_statuses": []
  }
  ```
- **Expected**: HTTP 201. `brand_id` in response equals `BRAND_A_ID`.
- **Store**: Returned `id` as `LC_BRAND_A_ID`.

---

#### TC-LC-05: Resolve lifecycle — generic ORDER for SHIP_TO_HOME

- **Priority**: P0
- **Precondition**: `LC_ORDER_ID` is active with `fulfillment_types = ["SHIP_TO_HOME"]` and `pipeline_type = "ORDER"`, `order_type = null`, `brand_id = null`.
- **Action**: `GET /lifecycles/resolve?fulfillment_type=SHIP_TO_HOME&pipeline_type=ORDER`
- **Expected**: HTTP 200. `lifecycle.id` is a valid UUID. `matched_on` field indicates the resolution tier used (e.g. `"fulfillment_type"` or `"default"`).

---

#### TC-LC-06: Resolve lifecycle — brand+order_type wins over generic

- **Priority**: P1
- **Precondition**: Both `LC_ORDER_ID` (no brand, no order_type) and `LC_BRAND_A_ID` (brand = BRAND_A, no order_type) are active. Additionally, a lifecycle `LC_BRAND_A_B2B_ID` exists with `brand_id = BRAND_A_ID`, `order_type = "B2B"`, `pipeline_type = "ORDER"`, `fulfillment_types = ["SHIP_TO_HOME"]`.
- **Action**: `GET /lifecycles/resolve?fulfillment_type=SHIP_TO_HOME&pipeline_type=ORDER&order_type=B2B&brand_id=<BRAND_A_ID>`
- **Expected**: HTTP 200. `lifecycle.id = LC_BRAND_A_B2B_ID`. The most specific match (brand + order_type) is selected over less specific alternatives.

---

#### TC-LC-07: Resolve lifecycle — RETURN pipeline does NOT return ORDER lifecycle

- **Priority**: P0
- **Precondition**: `LC_RETURN_ID` (pipeline_type = RETURN) and `LC_ORDER_ID` (pipeline_type = ORDER) both exist and are active.
- **Action**: `GET /lifecycles/resolve?fulfillment_type=SHIP_TO_HOME&pipeline_type=RETURN`
- **Expected**: HTTP 200. The resolved `lifecycle.pipeline_type = "RETURN"`. The ORDER lifecycle (`LC_ORDER_ID`) is NOT returned.

---

#### TC-LC-08: List lifecycles filtered by pipeline_type=RETURN

- **Priority**: P1
- **Precondition**: Both ORDER and RETURN lifecycles exist.
- **Action**: `GET /lifecycles/?pipeline_type=RETURN`
- **Expected**: HTTP 200. All entries in the array have `pipeline_type = "RETURN"`. No ORDER lifecycles appear.

---

#### TC-LC-09: Update lifecycle — deactivate

- **Priority**: P1
- **Precondition**: `LC_ORDER_ID` exists and `is_active = true`.
- **Action**: `PATCH /lifecycles/<LC_ORDER_ID>` with `{"is_active": false}`.
- **Expected**: HTTP 200. `is_active = false`. Steps are unchanged.

---

#### TC-LC-10: Delete lifecycle

- **Priority**: P2
- **Precondition**: Create a temporary lifecycle and store its `id` as `LC_TEMP_ID`.
- **Action**: `DELETE /lifecycles/<LC_TEMP_ID>`
- **Expected**: HTTP 204. `GET /lifecycles/<LC_TEMP_ID>` returns HTTP 404.

---

### API Keys (TC-APIKEY)

#### TC-APIKEY-01: Create API key — happy path

- **Priority**: P0
- **Action**: `POST /api-keys`
  ```json
  {"name": "CI Integration Key", "scopes": [], "expires_at": null}
  ```
- **Expected**: HTTP 201. Response contains `id` (UUID), `name = "CI Integration Key"`, `key` field starts with `"kr_"`, `key` total length is at least 35 characters (prefix "kr_" + 32-byte urlsafe token base64-encoded to ~43 chars). `prefix` is the first 12 characters of `key`. `scopes = []`. `expires_at = null`.
- **Critical security check**: The raw `key` value appears in this response exactly once and is never returned again on subsequent GETs.
- **Store**: `key` as `API_KEY_1`, `id` as `API_KEY_1_ID`.

---

#### TC-APIKEY-02: Create API key with scopes and expiry

- **Priority**: P1
- **Action**: `POST /api-keys`
  ```json
  {
    "name": "Read-only Analytics Key",
    "scopes": ["orders:read", "analytics:read"],
    "expires_at": "2030-01-01T00:00:00Z"
  }
  ```
- **Expected**: HTTP 201. `scopes = ["orders:read", "analytics:read"]`. `expires_at` is set.
- **Store**: `id` as `API_KEY_SCOPED_ID`.

---

#### TC-APIKEY-03: List API keys — full key never exposed

- **Priority**: P0
- **Precondition**: At least `API_KEY_1` and `API_KEY_SCOPED_ID` exist.
- **Action**: `GET /api-keys`
- **Expected**: HTTP 200. Returns an array. Each entry contains `id`, `name`, `prefix`, `scopes`, `is_active`, `expires_at`, `created_at`, `last_used_at`. Critically: no entry contains a `key` field with the full raw key value. `prefix` is 12 characters only.

---

#### TC-APIKEY-04: Authenticate with X-API-Key header on a protected endpoint

- **Priority**: P0
- **Precondition**: `API_KEY_1` (raw key string) is stored from TC-APIKEY-01.
- **Action**: `GET /orders/` with header `X-API-Key: <API_KEY_1>` and NO `Authorization` header.
- **Expected**: HTTP 200. The request authenticates successfully using the API key.

---

#### TC-APIKEY-05: Invalid API key returns 401

- **Priority**: P0
- **Action**: `GET /orders/` with header `X-API-Key: kr_thisisafakeandnonexistentkey12345678901234`
- **Expected**: HTTP 401.

---

#### TC-APIKEY-06: Revoke API key — subsequent requests rejected

- **Priority**: P0
- **Precondition**: `API_KEY_1` authenticates successfully (confirmed in TC-APIKEY-04). `API_KEY_1_ID` stored.
- **Steps**:
  1. `DELETE /api-keys/<API_KEY_1_ID>` — Expected: HTTP 204.
  2. `GET /api-keys` — Expected: The entry for `API_KEY_1_ID` has `is_active = false`.
  3. `GET /orders/` with header `X-API-Key: <API_KEY_1>` — Expected: HTTP 401.
- **Data integrity**: Row for `API_KEY_1_ID` still exists in `api_keys` table (soft delete, not hard delete). `is_active = false`.

---

#### TC-APIKEY-07: Revoking an already-revoked key is idempotent

- **Priority**: P1
- **Precondition**: `API_KEY_1_ID` is already revoked from TC-APIKEY-06.
- **Action**: `DELETE /api-keys/<API_KEY_1_ID>` again.
- **Expected**: HTTP 204. No error. The key remains revoked.

---

#### TC-APIKEY-08: Revoke non-existent API key returns 404

- **Priority**: P1
- **Action**: `DELETE /api-keys/00000000-0000-0000-0000-000000000000`
- **Expected**: HTTP 404. `detail = "API key not found"`.

---

#### TC-APIKEY-09: Create API key — non-superadmin is rejected

- **Priority**: P0
- **Precondition**: `USER_TOKEN` is a non-superadmin token.
- **Action**: `POST /api-keys` with `Authorization: Bearer <USER_TOKEN>` and valid payload.
- **Expected**: HTTP 403.

---

#### TC-APIKEY-10: Expired API key returns 401

- **Priority**: P1
- **Precondition**: Create a new API key with `expires_at` set to a timestamp 1 second in the past. Store raw key as `EXPIRED_KEY`.
- **Action**: `GET /orders/` with header `X-API-Key: <EXPIRED_KEY>`.
- **Expected**: HTTP 401. The key is structurally valid but expired.

---

#### TC-APIKEY-11: API key name is required — empty name returns 422

- **Priority**: P1
- **Action**: `POST /api-keys` with `{"name": "", "scopes": []}`.
- **Expected**: HTTP 422. Validation error on `name` field (min_length=1).

---

#### TC-APIKEY-12: Concurrent API key creation — both keys are unique

- **Priority**: P2
- **Description**: Race condition validation. Two simultaneous API key creation requests should produce two distinct keys and IDs.
- **Action**: Fire two `POST /api-keys` requests concurrently (e.g. in parallel from two processes or threads).
- **Expected**: Both return HTTP 201. The two `key` values are different. The two `id` values are different. The two `prefix` values are likely different (both being 12-char prefixes of unique 43-char keys).

---

### Brand-Scoped User Access (TC-BA)

#### TC-BA-01: Assign user to brand with OPERATOR role

- **Priority**: P0
- **Precondition**: `USER_ID` is a valid non-superadmin user. `BRAND_A_ID` and `ENV_ID` exist.
- **Action**: `POST /brand-access/`
  ```json
  {
    "user_id": "<USER_ID>",
    "brand_id": "<BRAND_A_ID>",
    "environment_id": "<ENV_ID>",
    "role": "OPERATOR"
  }
  ```
- **Expected**: HTTP 201. Response has `id` (UUID), `user_id`, `brand_id`, `environment_id`, `role = "OPERATOR"`. `created_by_id` is the superadmin's user ID.
- **Store**: Returned `id` as `BA_ASSIGNMENT_ID`.

---

#### TC-BA-02: Assign user with VIEWER role

- **Priority**: P1
- **Precondition**: A second regular user exists — store `id` as `USER2_ID`.
- **Action**: `POST /brand-access/` with `user_id = USER2_ID`, `brand_id = BRAND_A_ID`, `environment_id = ENV_ID`, `role = "VIEWER"`.
- **Expected**: HTTP 201. `role = "VIEWER"`.

---

#### TC-BA-03: Assign user with ADMIN role

- **Priority**: P1
- **Action**: `POST /brand-access/` with a third user (`USER3_ID`), `role = "ADMIN"`.
- **Expected**: HTTP 201. `role = "ADMIN"`.

---

#### TC-BA-04: Duplicate assignment returns 409

- **Priority**: P0
- **Precondition**: `BA_ASSIGNMENT_ID` exists (USER_ID → BRAND_A, ENV_ID, OPERATOR).
- **Action**: `POST /brand-access/` with the same `user_id`, `brand_id`, and `environment_id`.
- **Expected**: HTTP 409. `detail` contains "already has a brand role in this environment".

---

#### TC-BA-05: Invalid role value returns 422

- **Priority**: P1
- **Action**: `POST /brand-access/` with `role = "SUPERUSER"`.
- **Expected**: HTTP 422. Validation error on `role` field.

---

#### TC-BA-06: Non-superadmin cannot call brand-access endpoints

- **Priority**: P0
- **Precondition**: `USER_TOKEN` is a non-superadmin token.
- **Action**: `POST /brand-access/` with `Authorization: Bearer <USER_TOKEN>` and valid payload.
- **Expected**: HTTP 403.

---

#### TC-BA-07: List brand-access — filter by user_id

- **Priority**: P1
- **Precondition**: `USER_ID` has assignments in BRAND_A and (separately) no assignments in BRAND_B.
- **Action**: `GET /brand-access/?user_id=<USER_ID>`
- **Expected**: HTTP 200. All returned entries have `user_id = USER_ID`. No entries for other users.

---

#### TC-BA-08: List brand-access — filter by brand_id

- **Priority**: P1
- **Action**: `GET /brand-access/?brand_id=<BRAND_A_ID>`
- **Expected**: HTTP 200. All returned entries have `brand_id = BRAND_A_ID`.

---

#### TC-BA-09: Remove brand access assignment

- **Priority**: P0
- **Precondition**: `BA_ASSIGNMENT_ID` exists.
- **Action**: `DELETE /brand-access/<BA_ASSIGNMENT_ID>`
- **Expected**: HTTP 204. `GET /brand-access/?user_id=<USER_ID>&brand_id=<BRAND_A_ID>` returns empty list for that combination.

---

#### TC-BA-10: Remove non-existent assignment returns 404

- **Priority**: P1
- **Action**: `DELETE /brand-access/00000000-0000-0000-0000-000000000000`
- **Expected**: HTTP 404. `detail = "Brand access assignment not found"`.

---

#### TC-BA-11: Assign to non-existent user returns 404

- **Priority**: P1
- **Action**: `POST /brand-access/` with `user_id = "00000000-0000-0000-0000-000000000000"`.
- **Expected**: HTTP 404. `detail = "User not found"`.

---

#### TC-BA-12: Assign to non-existent brand returns 404

- **Priority**: P1
- **Action**: `POST /brand-access/` with valid `user_id`, `brand_id = "00000000-0000-0000-0000-000000000000"`.
- **Expected**: HTTP 404. `detail = "Brand not found"`.

---

#### TC-BA-13: Assign to non-existent environment returns 404

- **Priority**: P1
- **Action**: `POST /brand-access/` with valid `user_id`, valid `brand_id`, `environment_id = "00000000-0000-0000-0000-000000000000"`.
- **Expected**: HTTP 404. `detail = "Environment not found"`.

---

#### TC-BA-14: Brand-scoped access isolation — user sees only their brand's orders (UAT)

- **Priority**: P0
- **Description**: Business-level validation that brand scoping enforces data isolation.
- **Precondition**: `USER_ID` has been assigned OPERATOR role on `BRAND_A_ID` only (not BRAND_B). Two orders exist: `ORDER_BRAND_A_ID` (brand = BRAND_A) and `ORDER_BRAND_B_ID` (brand = BRAND_B).
- **Steps**:
  1. Authenticate as `USER_ID` (obtain `USER_TOKEN`).
  2. `GET /orders/?brand_id=<BRAND_A_ID>` with `USER_TOKEN` — Expected: HTTP 200. `ORDER_BRAND_A_ID` is in results.
  3. `GET /orders/<ORDER_BRAND_B_ID>` with `USER_TOKEN` — Expected: HTTP 403 or empty result set (brand-scoped user cannot access Brand B data).
- **Expected**: Brand-scoped users are strictly limited to data within their assigned brand. Superadmin sees all orders regardless of brand scope.

---

#### TC-BA-15: Concurrent assignment race condition — only one succeeds

- **Priority**: P2
- **Description**: Two simultaneous POST requests assigning the same user/brand/environment combination should result in exactly one 201 and one 409.
- **Action**: Fire two `POST /brand-access/` requests concurrently with identical `user_id`, `brand_id`, and `environment_id`.
- **Expected**: Exactly one request returns HTTP 201 and one returns HTTP 409 (or both 201 only if the second arrived after the first committed — in which case the unique constraint still prevents duplicates). No data corruption or duplicate rows.

---

### SLA Breach Detection (TC-SLA)

#### TC-SLA-01: GET /monitoring/sla-summary returns expected shape

- **Priority**: P0
- **Precondition**: Superadmin token. Redis is reachable.
- **Action**: `GET /monitoring/sla-summary`
- **Expected**: HTTP 200. Response body is `{"date": "<YYYY-MM-DD>", "environment_id": "<string>", "sla_breaches_today": <integer>}`. `date` matches today's UTC date. `sla_breaches_today` is a non-negative integer.

---

#### TC-SLA-02: SLA summary returns 200 even when Redis is unreachable

- **Priority**: P0
- **Description**: The endpoint must degrade gracefully — a Redis failure must not surface a 500 to callers.
- **Precondition**: Simulate Redis unavailability by temporarily pointing `REDIS_URL` to an unreachable host, or by flushing the key and blocking Redis port (test environment only).
- **Action**: `GET /monitoring/sla-summary`
- **Expected**: HTTP 200. `sla_breaches_today = 0`. No 500 error. The warning is logged server-side but not exposed in the API response.

---

#### TC-SLA-03: SLA summary Redis key pattern matches implementation

- **Priority**: P1
- **Description**: Validates the exact Redis key format used by the SLA check worker so monitoring and worker are in sync.
- **Precondition**: Redis is reachable. Superadmin token.
- **Steps**:
  1. `GET /monitoring/sla-summary` — note `environment_id` value (e.g. `"default"`) and `date` (e.g. `"2026-05-09"`).
  2. Using a Redis client: `SET sla_breaches:<environment_id>:<date> 7 EX 86400`.
  3. `GET /monitoring/sla-summary` again.
- **Expected**: Step 3 response: `sla_breaches_today = 7`. Confirms that the key pattern `sla_breaches:{env_label}:{YYYY-MM-DD}` used by the endpoint matches exactly what the worker writes.

---

#### TC-SLA-04: SLA summary requires superadmin authentication

- **Priority**: P1
- **Action**: `GET /monitoring/sla-summary` without any Authorization header.
- **Expected**: HTTP 401.

---

### Node CRUD (TC-NODE)

#### TC-NODE-01: Create node — all required fields

- **Priority**: P0
- **Action**: `POST /nodes/`
  ```json
  {
    "code": "QA-NODE-001",
    "name": "QA Test Distribution Center",
    "node_type": "DISTRIBUTION_CENTER",
    "status": "ACTIVE",
    "address_line1": "1 QA Street",
    "city": "Test City",
    "state": "TX",
    "postal_code": "75001",
    "country": "US",
    "can_ship": true,
    "can_pickup": false,
    "can_curbside": false,
    "can_same_day": false,
    "daily_order_capacity": 500
  }
  ```
- **Expected**: HTTP 201. `id` is a UUID. `code = "QA-NODE-001"`. `status = "ACTIVE"`. `node_type = "DISTRIBUTION_CENTER"`. `can_ship = true`. `daily_order_capacity = 500`.
- **Store**: Returned `id` as `NODE_QA_ID`.

---

#### TC-NODE-02: Create node — duplicate code returns 409

- **Priority**: P0
- **Precondition**: `NODE_QA_ID` exists with `code = "QA-NODE-001"`.
- **Action**: `POST /nodes/` with `code = "QA-NODE-001"` (all other fields different).
- **Expected**: HTTP 409. `detail` contains "already exists".

---

#### TC-NODE-03: Update node capacity and cost multiplier

- **Priority**: P1
- **Precondition**: `NODE_QA_ID` exists.
- **Action**: `PATCH /nodes/<NODE_QA_ID>`
  ```json
  {"daily_order_capacity": 800, "cost_multiplier": 1.25}
  ```
- **Expected**: HTTP 200. `daily_order_capacity = 800`. `cost_multiplier = 1.25`. Other fields unchanged.

---

#### TC-NODE-04: Deactivate node — soft delete sets status=INACTIVE

- **Priority**: P0
- **Precondition**: `NODE_QA_ID` exists with `status = "ACTIVE"`.
- **Action**: `DELETE /nodes/<NODE_QA_ID>`
- **Expected**: HTTP 204. Subsequent `GET /nodes/<NODE_QA_ID>` returns HTTP 200 with `status = "INACTIVE"`. The node row still exists (soft delete, not hard delete).

---

#### TC-NODE-05: Get node capacity utilization

- **Priority**: P1
- **Precondition**: `NODE_QA_ID` exists with `daily_order_capacity = 800`.
- **Action**: `GET /nodes/<NODE_QA_ID>/capacity`
- **Expected**: HTTP 200. Response contains `node_id`, `daily_capacity`, `current_orders`, `available_capacity`, `utilization_pct`. `daily_capacity + available_capacity - current_orders = daily_capacity` (i.e. `available_capacity = daily_capacity - current_orders`). `utilization_pct` is between 0 and 100.

---

#### TC-NODE-06: List nodes filtered by node_type

- **Priority**: P1
- **Action**: `GET /nodes/?node_type=DISTRIBUTION_CENTER`
- **Expected**: HTTP 200. All entries in `items` have `node_type = "DISTRIBUTION_CENTER"`. `total` field is present. No RETAIL_STORE or other type nodes appear.

---

#### TC-NODE-07: Get non-existent node returns 404

- **Priority**: P1
- **Action**: `GET /nodes/00000000-0000-0000-0000-000000000000`
- **Expected**: HTTP 404. `detail = "Node not found"`.

---

### Custom Field Definitions (TC-CA)

#### TC-CA-01: Create custom attribute for ORDER entity

- **Priority**: P0
- **Precondition**: Superadmin token.
- **Action**: `POST /architect/custom-attributes`
  ```json
  {
    "entity_type": "ORDER",
    "field_key": "gift_message",
    "label": "Gift Message",
    "data_type": "text",
    "is_required": false,
    "default_value": null
  }
  ```
- **Expected**: HTTP 201. `id` is set. `entity_type = "ORDER"`. `field_key = "gift_message"`. `label = "Gift Message"`. `data_type = "text"`. `is_required = false`. `created_at` is a valid ISO timestamp.
- **Store**: Returned `id` as `CA_ORDER_ID`.

---

#### TC-CA-02: Create custom attribute for INVENTORY_ITEM entity

- **Priority**: P1
- **Action**: `POST /architect/custom-attributes`
  ```json
  {
    "entity_type": "INVENTORY_ITEM",
    "field_key": "hazmat_class",
    "label": "Hazmat Classification",
    "data_type": "text",
    "is_required": false,
    "default_value": "none"
  }
  ```
- **Expected**: HTTP 201. `entity_type = "INVENTORY_ITEM"`. `field_key = "hazmat_class"`. `default_value = "none"`.

---

#### TC-CA-03: Create custom attribute for NODE entity with number data_type

- **Priority**: P1
- **Action**: `POST /architect/custom-attributes`
  ```json
  {
    "entity_type": "NODE",
    "field_key": "floor_area_sqft",
    "label": "Floor Area (sq ft)",
    "data_type": "number",
    "is_required": false,
    "default_value": null
  }
  ```
- **Expected**: HTTP 201. `data_type = "number"`. `entity_type = "NODE"`.
- **Store**: Returned `id` as `CA_NODE_ID`.

---

#### TC-CA-04: Create custom attribute — invalid entity_type returns 400

- **Priority**: P1
- **Action**: `POST /architect/custom-attributes` with `entity_type = "SHIPMENT"`.
- **Expected**: HTTP 400. `detail` contains "entity_type must be one of".

---

#### TC-CA-05: Create custom attribute — invalid data_type returns 400

- **Priority**: P1
- **Action**: `POST /architect/custom-attributes` with `entity_type = "ORDER"`, `data_type = "json"`.
- **Expected**: HTTP 400. `detail` contains "data_type must be one of".

---

#### TC-CA-06: Create custom attribute — invalid field_key format returns 400

- **Priority**: P1
- **Description**: field_key must start with a lowercase letter and contain only lowercase letters, digits, and underscores.
- **Actions** (test each):
  1. `field_key = "GiftMessage"` (uppercase) — Expected: HTTP 400.
  2. `field_key = "1gift"` (starts with digit) — Expected: HTTP 400.
  3. `field_key = "gift-message"` (hyphen not allowed) — Expected: HTTP 400.
  4. `field_key = "gift_message"` (valid) — Expected: HTTP 201.

---

#### TC-CA-07: List custom attributes — all definitions returned

- **Priority**: P0
- **Precondition**: At least `CA_ORDER_ID` and `CA_NODE_ID` exist.
- **Action**: `GET /architect/custom-attributes`
- **Expected**: HTTP 200. Returns an array. Entries for `CA_ORDER_ID` and `CA_NODE_ID` are present. Each entry has `id`, `entity_type`, `field_key`, `label`, `data_type`, `is_required`, `default_value`, `created_at`.

---

#### TC-CA-08: List custom attributes filtered by entity_type

- **Priority**: P1
- **Action**: `GET /architect/custom-attributes?entity_type=ORDER`
- **Expected**: HTTP 200. All entries have `entity_type = "ORDER"`. The `CA_NODE_ID` entry (entity_type = NODE) is not included.

---

#### TC-CA-09: Delete custom attribute

- **Priority**: P0
- **Precondition**: `CA_NODE_ID` exists.
- **Action**: `DELETE /architect/custom-attributes/<CA_NODE_ID>`
- **Expected**: HTTP 204. Subsequent `GET /architect/custom-attributes` does not contain an entry with `id = CA_NODE_ID`.

---

#### TC-CA-10: Delete non-existent custom attribute returns 404

- **Priority**: P1
- **Action**: `DELETE /architect/custom-attributes/00000000-0000-0000-0000-000000000000`
- **Expected**: HTTP 404. `detail = "Custom field not found"`.

---

#### TC-CA-11: Custom attribute requires superadmin

- **Priority**: P0
- **Precondition**: `USER_TOKEN` is a non-superadmin token.
- **Action**: `POST /architect/custom-attributes` with `Authorization: Bearer <USER_TOKEN>`.
- **Expected**: HTTP 403.

---

### Worker Reliability (TC-WRK)

#### TC-WRK-01: start_picking idempotency — second call is a no-op

- **Priority**: P0
- **Description**: Validates that the Redis idempotency guard (`task:start_picking:{order_id}`) prevents a duplicate picking transition even if the Celery task is delivered twice.
- **Precondition**: An order `ORDER_SOURCED_ID` is in `SOURCED` status with at least one `ALLOCATED` fulfillment allocation. Redis is reachable.
- **Steps**:
  1. Trigger `start_picking` for `ORDER_SOURCED_ID` via the Celery API or by dispatching the task directly: `app.workers.fulfillment.start_picking.delay(order_id="<ORDER_SOURCED_ID>")`.
  2. Wait 2 seconds for the task to process.
  3. Verify `GET /orders/<ORDER_SOURCED_ID>` returns `status = "PICKING"`.
  4. Immediately trigger `start_picking` again for the same `order_id`.
  5. Wait 2 seconds.
  6. `GET /orders/<ORDER_SOURCED_ID>` again.
- **Expected**: Step 3: `status = "PICKING"`. Step 6: `status` is still `"PICKING"` — the order has not transitioned to `"PACKING"` or any other status due to the duplicate call. Worker log contains "start_picking duplicate detected for … skipping". `GET /orders/<ORDER_SOURCED_ID>/events` contains exactly one `order.picking` event (not two).

---

#### TC-WRK-02: SLA breach detection — order stuck in PICKING generates sla_breach event

- **Priority**: P1
- **Description**: Validates that the SLA breach worker detects an order that has been in PICKING status longer than its configured `sla_hours` and records an `order.sla_breach` event in MongoDB.
- **Precondition**: A sourcing rule lifecycle step for PICKING has `sla_hours = 2`. An order `ORDER_BREACH_ID` has been in `PICKING` status for more than 2 hours (simulate by setting `order.picking_started_at` to `NOW() - interval '3 hours'` directly in the database, or by using a lifecycle with `sla_hours = 0`).
- **Steps**:
  1. Manually trigger the SLA breach check worker task (or wait for the scheduled run).
  2. `GET /orders/<ORDER_BREACH_ID>/events`.
- **Expected**: The events list contains an entry with `event_type = "order.sla_breach"`. The `data` field includes `order_id`, `current_status`, and indicates which SLA threshold was exceeded. The `GET /monitoring/sla-summary` counter increases by at least 1 for today's date.

---

#### TC-WRK-03: source_order task rate limit is configured at 100/m

- **Priority**: P1
- **Description**: Validates that the Celery task rate limit is declared correctly and that the Celery worker respects it under burst conditions. This is a configuration validation test.
- **Precondition**: Celery workers are running with the sourcing queue active.
- **Steps**:
  1. Inspect the registered task metadata: `celery inspect registered` (or equivalent). Confirm `app.workers.sourcing.source_order` reports `rate_limit = "100/m"`.
  2. Submit 110 `source_order` tasks in rapid succession (each with a different dummy `order_id` that does not exist in the DB so they exit quickly).
  3. Monitor the sourcing queue throughput over 60 seconds.
- **Expected**: Step 1: `rate_limit = "100/m"` is present in the task registration. Step 3: No more than 100 tasks are processed within any single 60-second window. Tasks beyond the rate cap are queued and processed in the next window, not dropped or errored.

---

#### TC-WRK-04: source_order skips orders not in sourceable status

- **Priority**: P1
- **Description**: Validates the guard in the sourcing worker that prevents re-sourcing an order already in PICKING or later status.
- **Precondition**: `ORDER_PICKING_ID` is in `PICKING` status.
- **Steps**:
  1. Dispatch `source_order` for `ORDER_PICKING_ID`.
  2. Wait 3 seconds for task processing.
  3. `GET /orders/<ORDER_PICKING_ID>`.
- **Expected**: `status` remains `"PICKING"`. No new `order.sourced` event is created in MongoDB. Worker log contains "cannot be sourced" or equivalent skip message.

---

#### TC-WRK-05: Fulfillment worker logs audit events to MongoDB

- **Priority**: P0
- **Description**: Validates the async MongoDB write path from the synchronous Celery fulfillment worker.
- **Precondition**: `ORDER_SOURCED_ID` is in `SOURCED` status.
- **Steps**:
  1. Trigger `start_picking` for `ORDER_SOURCED_ID`.
  2. Wait for the order to reach `PICKING` status.
  3. `GET /orders/<ORDER_SOURCED_ID>/events`.
- **Expected**: The events list contains `event_type = "order.picking"` with a valid `timestamp`. The event `data` includes the transition details. This confirms the `_log_event_sync` → `asyncio.run(_do())` path successfully writes to MongoDB from the synchronous worker context.

---

## Sprint 3 Test Summary

| Feature Area | Test Cases | P0 | P1 | P2 |
|---|---|---|---|---|
| Distribution Groups CRUD | TC-DG-01 to TC-DG-18 | 6 | 10 | 2 |
| Lifecycle Pipeline Types | TC-LC-01 to TC-LC-10 | 5 | 4 | 1 |
| API Keys | TC-APIKEY-01 to TC-APIKEY-12 | 5 | 6 | 1 |
| Brand-Scoped User Access | TC-BA-01 to TC-BA-15 | 5 | 8 | 2 |
| SLA Breach Detection | TC-SLA-01 to TC-SLA-04 | 2 | 2 | 0 |
| Node CRUD | TC-NODE-01 to TC-NODE-07 | 3 | 4 | 0 |
| Custom Field Definitions | TC-CA-01 to TC-CA-11 | 4 | 6 | 1 |
| Worker Reliability | TC-WRK-01 to TC-WRK-05 | 2 | 3 | 0 |
| **Total** | **82** | **32** | **43** | **7** |

**Recommended execution order**: Node CRUD (TC-NODE) → Distribution Groups (TC-DG) → Sourcing Rules with DG targets (TC-DG-16 to TC-DG-18) → Lifecycle (TC-LC) → API Keys (TC-APIKEY) → Brand Access (TC-BA) → SLA (TC-SLA) → Custom Attributes (TC-CA) → Worker Reliability (TC-WRK).
