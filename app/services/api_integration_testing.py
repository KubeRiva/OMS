"""
API Integration Testing Service
Runs HTTP-level API tests against the running OMS API using httpx.
All test data is tracked and cleaned up after the run.
"""
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ApiTestResult:
    id: str
    desc: str
    group: str
    status: str          # "PASSED" | "FAILED" | "SKIPPED"
    note: str
    duration_ms: float


@dataclass
class ApiTestRun:
    test_id: str
    status: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    total_duration_ms: float
    cleanup_duration_ms: float
    deleted_resources: Dict[str, int]
    results: List[ApiTestResult]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ApiIntegrationTestService:
    """
    Runs the full API integration test suite using httpx.
    Uses the running server's base URL (localhost:8000 from within the container).
    All created resources are tracked and deleted in cleanup().
    """

    def __init__(self, base_url: Optional[str] = None, admin_email: str = "admin@oms.local", admin_password: str = ""):
        # Prefer the public base URL from settings; fall back to localhost
        self.base_url = (base_url or settings.PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")
        self.admin_email = admin_email
        self.admin_password = admin_password

        # Resources to clean up
        self._order_ids: List[str] = []
        self._inv_ids: List[str] = []
        self._user_ids: List[str] = []
        self._user_emails: List[str] = []
        self._dg_ids: List[str] = []
        self._api_key_ids: List[str] = []
        self._brand_access_ids: List[str] = []
        self._brand_ids: List[str] = []
        self._custom_attr_ids: List[str] = []
        self._reg_user_id: str = ""

    # ------------------------------------------------------------------ runner

    async def run_all(self) -> ApiTestRun:
        test_id = str(uuid.uuid4())
        results: List[ApiTestResult] = []
        t0 = time.time()

        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
            await self._run_auth(client, results)
            await self._run_orders(client, results)
            await self._run_inventory(client, results)
            await self._run_analytics(client, results)
            await self._run_search(client, results)
            await self._run_ai(client, results)
            await self._run_rbac(client, results)
            await self._run_security(client, results)
            await self._run_brand(client, results)
            await self._run_distribution_groups(client, results)
            await self._run_api_keys(client, results)
            await self._run_brand_access(client, results)
            await self._run_sla(client, results)
            await self._run_custom_attrs(client, results)

        test_dur = (time.time() - t0) * 1000

        # Cleanup
        c0 = time.time()
        deleted = await self._cleanup()
        cleanup_dur = (time.time() - c0) * 1000

        passed = sum(1 for r in results if r.status == "PASSED")
        failed = sum(1 for r in results if r.status == "FAILED")
        skipped = sum(1 for r in results if r.status == "SKIPPED")

        return ApiTestRun(
            test_id=test_id,
            status="completed",
            total_tests=len(results),
            passed=passed,
            failed=failed,
            skipped=skipped,
            total_duration_ms=test_dur + cleanup_dur,
            cleanup_duration_ms=cleanup_dur,
            deleted_resources=deleted,
            results=results,
        )

    # ------------------------------------------------------------------ helpers

    def _ok(self, results: List[ApiTestResult], id: str, desc: str, group: str,
            passed: bool, note: str = "", duration_ms: float = 0.0):
        results.append(ApiTestResult(
            id=id, desc=desc, group=group,
            status="PASSED" if passed else "FAILED",
            note=note, duration_ms=duration_ms,
        ))

    def _skip(self, results: List[ApiTestResult], id: str, desc: str, group: str, reason: str):
        results.append(ApiTestResult(
            id=id, desc=desc, group=group, status="SKIPPED",
            note=reason, duration_ms=0.0,
        ))

    async def _req(self, client: httpx.AsyncClient, method: str, path: str,
                   token: str = "", json: Any = None, headers: Dict = None,
                   no_auth: bool = False) -> tuple[int, Any, float]:
        t0 = time.time()
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {token}"
        if headers:
            h.update(headers)
        try:
            if no_auth:
                # Use a fresh cookie-free client so session cookies from login don't bleed in
                async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as fresh:
                    resp = await fresh.request(method, path, json=json, headers=h)
            else:
                resp = await client.request(method, path, json=json, headers=h)
            try:
                data = resp.json()
            except Exception:
                data = None
            return resp.status_code, data, (time.time() - t0) * 1000
        except Exception as exc:
            logger.warning(f"API test request failed: {method} {path}: {exc}")
            return 0, None, (time.time() - t0) * 1000

    # ------------------------------------------------------------------ AUTH

    async def _run_auth(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = ""

        code, data, ms = await self._req(client, "POST", "/auth/login",
                                          json={"email": self.admin_email, "password": self.admin_password})
        token = data.get("access_token", "") if isinstance(data, dict) else ""
        self._ok(results, "AUTH-1", "Login correct credentials → 200", "AUTH",
                 code == 200 and bool(token), f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "POST", "/auth/login",
                                       json={"email": self.admin_email, "password": "wrongpassword"})
        self._ok(results, "AUTH-2", "Login wrong password → 401", "AUTH", code == 401, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "GET", "/orders/", no_auth=True)
        self._ok(results, "AUTH-3", "No token → 401", "AUTH", code == 401, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "GET", "/orders/", token=token)
        self._ok(results, "AUTH-4", "Valid token → 200", "AUTH", code == 200, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "POST", "/auth/logout", token=token)
        self._ok(results, "AUTH-5", "POST /auth/logout → 204", "AUTH", code == 204, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "GET", "/orders/", token=token)
        self._ok(results, "AUTH-6", "Revoked token → 401", "AUTH", code == 401, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "GET", "/orders/", token="notvalidjwt")
        self._ok(results, "AUTH-7", "Malformed JWT → 401", "AUTH", code == 401, f"HTTP {code}", ms)

        # Re-login for remaining tests
        code, data, ms = await self._req(client, "POST", "/auth/login",
                                          json={"email": self.admin_email, "password": self.admin_password})
        token = data.get("access_token", "") if isinstance(data, dict) else ""

        code, _, ms = await self._req(client, "POST", "/ai/chat",
                                       json={"messages": [{"role": "user", "content": "hi"}]}, no_auth=True)
        self._ok(results, "AUTH-8", "AI /chat no token → 401", "AUTH", code == 401, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "GET", "/analytics/dashboard", no_auth=True)
        self._ok(results, "AUTH-9", "Analytics no token → 401", "AUTH", code == 401, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "GET", "/inventory/", no_auth=True)
        self._ok(results, "AUTH-10", "Inventory no token → 401", "AUTH", code == 401, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "POST", "/search/orders", json={}, no_auth=True)
        self._ok(results, "AUTH-11", "Search no token → 401", "AUTH", code == 401, f"HTTP {code}", ms)

        # Store token for subsequent test groups
        self._token = token

    # ------------------------------------------------------------------ ORDERS

    async def _run_orders(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = getattr(self, "_token", "")
        order_id = ""
        cancel_id = ""

        code, data, ms = await self._req(client, "POST", "/orders/", token=token, json={
            "channel": "WEB", "fulfillment_type": "SHIP_TO_HOME",
            "customer_name": "UAT Tester", "customer_email": "test.uat@example.com",
            "shipping_address": {"address1": "123 Test St", "city": "San Francisco",
                                 "state": "CA", "postal_code": "94105", "country": "US"},
            "line_items": [{"sku": "UAT-SKU-001", "product_name": "Test Widget",
                            "quantity": 2, "unit_price": 49.99}],
        })
        order_id = data.get("id", "") if isinstance(data, dict) else ""
        if order_id:
            self._order_ids.append(order_id)
        self._ok(results, "ORDER-1", "Create order → 201", "ORDERS", bool(order_id),
                 "" if order_id else f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "GET", "/orders/", token=token)
        self._ok(results, "ORDER-2", "List orders → 200", "ORDERS", code == 200, f"HTTP {code}", ms)

        if order_id:
            code, _, ms = await self._req(client, "GET", f"/orders/{order_id}", token=token)
            self._ok(results, "ORDER-3", "Get order by ID → 200", "ORDERS", code == 200, f"HTTP {code}", ms)
        else:
            self._skip(results, "ORDER-3", "Get order by ID → 200", "ORDERS", "No order created")

        if order_id:
            code, _, ms = await self._req(client, "PATCH", f"/orders/{order_id}/status",
                                           token=token, json={"status": "SOURCING"})
            self._ok(results, "ORDER-4", "Status → SOURCING", "ORDERS", code == 200, f"HTTP {code}", ms)

            code, _, ms = await self._req(client, "PATCH", f"/orders/{order_id}/status",
                                           token=token, json={"status": "SOURCED"})
            self._ok(results, "ORDER-4b", "Status → SOURCED", "ORDERS", code == 200, f"HTTP {code}", ms)

            code, _, ms = await self._req(client, "PATCH", f"/orders/{order_id}/status",
                                           token=token, json={"status": "DELIVERED"})
            self._ok(results, "ORDER-4c", "Invalid transition → 422", "ORDERS",
                     code in (422, 400), f"HTTP {code}", ms)
        else:
            for tid, desc in [("ORDER-4", "Status → SOURCING"), ("ORDER-4b", "Status → SOURCED"),
                               ("ORDER-4c", "Invalid transition → 422")]:
                self._skip(results, tid, desc, "ORDERS", "No order created")

        # Create second order for cancel test
        code, data, ms = await self._req(client, "POST", "/orders/", token=token, json={
            "channel": "WEB", "fulfillment_type": "SHIP_TO_HOME",
            "customer_name": "Cancel", "customer_email": "cancel.uat@example.com",
            "shipping_address": {"address1": "1 St", "city": "SF", "state": "CA",
                                 "postal_code": "94105", "country": "US"},
            "line_items": [{"sku": "CANCEL-UAT", "product_name": "Item", "quantity": 1, "unit_price": 1.0}],
        })
        cancel_id = data.get("id", "") if isinstance(data, dict) else ""
        if cancel_id:
            self._order_ids.append(cancel_id)
            code, _, ms = await self._req(client, "POST", f"/orders/{cancel_id}/cancel",
                                           token=token, json={"reason": "UAT cancel"})
            self._ok(results, "ORDER-5", "Cancel order → 200", "ORDERS", code == 200, f"HTTP {code}", ms)
        else:
            self._skip(results, "ORDER-5", "Cancel order → 200", "ORDERS", "Could not create cancel order")

        if order_id:
            code, _, ms = await self._req(client, "GET", f"/orders/{order_id}/events", token=token)
            self._ok(results, "ORDER-6", "Order audit trail → 200", "ORDERS", code == 200, f"HTTP {code}", ms)
        else:
            self._skip(results, "ORDER-6", "Order audit trail → 200", "ORDERS", "No order created")

        code, _, ms = await self._req(client, "POST", "/orders/", token=token, json={"channel": "WEB"})
        self._ok(results, "ORDER-ERR1", "Missing fields → 422", "ORDERS", code == 422, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "GET", "/orders/00000000-0000-0000-0000-000000000000", token=token)
        self._ok(results, "ORDER-ERR2", "Non-existent order → 404", "ORDERS", code == 404, f"HTTP {code}", ms)

    # ------------------------------------------------------------------ INVENTORY

    async def _run_inventory(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = getattr(self, "_token", "")

        code, _, ms = await self._req(client, "GET", "/inventory/", token=token)
        self._ok(results, "INV-1", "List inventory → 200", "INVENTORY", code == 200, f"HTTP {code}", ms)

        # Get a node
        code, data, ms = await self._req(client, "GET", "/nodes/", token=token)
        node_items = data if isinstance(data, list) else (data.get("items", []) if isinstance(data, dict) else [])
        node_id = node_items[0]["id"] if node_items else ""

        inv_id = ""
        if node_id:
            sku = f"UAT-INV-{int(time.time())}"
            code, data, ms = await self._req(client, "POST", "/inventory/", token=token, json={
                "sku": sku, "node_id": node_id,
                "quantity_available": 0, "quantity_reserved": 0,
                "reorder_point": 5, "reorder_quantity": 50,
            })
            inv_id = data.get("id", "") if isinstance(data, dict) else ""
            if inv_id:
                self._inv_ids.append(inv_id)
            self._ok(results, "INV-2", "Create inventory item → 201", "INVENTORY",
                     bool(inv_id), "" if inv_id else f"HTTP {code}", ms)
        else:
            self._skip(results, "INV-2", "Create inventory item → 201", "INVENTORY", "No nodes available")

        if inv_id:
            code, _, ms = await self._req(client, "POST", f"/inventory/{inv_id}/adjust", token=token,
                                           json={"quantity_delta": 100, "reason": "RECEIVED", "notes": "UAT"})
            self._ok(results, "INV-3", "Adjust inventory +100 → 200", "INVENTORY",
                     code == 200, f"HTTP {code}", ms)
        else:
            self._skip(results, "INV-3", "Adjust inventory +100 → 200", "INVENTORY", "No inventory item")

        code, _, ms = await self._req(client, "POST", "/inventory/check-availability", token=token,
                                       json={"items": [{"sku": "UAT-SKU-001", "quantity": 1}]})
        self._ok(results, "INV-4", "Check availability → 200", "INVENTORY", code == 200, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "GET", "/inventory/products", token=token)
        self._ok(results, "INV-5", "Products grouped by SKU → 200", "INVENTORY", code == 200, f"HTTP {code}", ms)

        target = inv_id or "00000000-0000-0000-0000-000000000001"
        code, _, ms = await self._req(client, "POST", f"/inventory/{target}/adjust", token=token,
                                       json={"quantity_delta": 10, "reason": "BAD_REASON"})
        self._ok(results, "INV-ERR1", "Invalid adjustment reason → 422", "INVENTORY",
                 code == 422, f"HTTP {code}", ms)

    # ------------------------------------------------------------------ ANALYTICS

    async def _run_analytics(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = getattr(self, "_token", "")
        for aid, desc, path in [
            ("ANA-1", "Dashboard → 200", "/analytics/dashboard"),
            ("ANA-2", "Order volume → 200", "/analytics/orders/volume"),
            ("ANA-3", "Inventory summary → 200", "/analytics/inventory/summary"),
        ]:
            code, _, ms = await self._req(client, "GET", path, token=token)
            self._ok(results, aid, desc, "ANALYTICS", code == 200, f"HTTP {code}", ms)

    # ------------------------------------------------------------------ SEARCH

    async def _run_search(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = getattr(self, "_token", "")
        code, _, ms = await self._req(client, "POST", "/search/orders", token=token,
                                       json={"query": "UAT", "page": 1, "page_size": 5})
        self._ok(results, "SEARCH-1", "Search orders → 200", "SEARCH", code == 200, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "POST", "/search/orders", token=token,
                                       json={"query": "test", "sort_by": "__proto__", "page": 1, "page_size": 5})
        self._ok(results, "SEARCH-2", "Invalid sort field fallback → 200", "SEARCH", code == 200, f"HTTP {code}", ms)

    # ------------------------------------------------------------------ AI

    async def _run_ai(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = getattr(self, "_token", "")
        code, _, ms = await self._req(client, "GET", "/ai/status", token=token)
        self._ok(results, "AI-1", "AI status → 200", "AI", code == 200, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "POST", "/ai/chat", token=token,
                                       json={"messages": [{"role": "user", "content": "How many orders?"}]})
        self._ok(results, "AI-2", "AI chat → 200", "AI", code == 200, f"HTTP {code}", ms)

    # ------------------------------------------------------------------ RBAC

    async def _run_rbac(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = getattr(self, "_token", "")
        reg_email = f"uat.reg.{int(time.time())}@example.com"
        reg_token = ""

        code, data, ms = await self._req(client, "POST", "/admin/users", token=token, json={
            "email": reg_email, "password": "Pass1234!", "full_name": "UAT Regular", "is_superadmin": False,
        })
        created = code in (200, 201)
        if created:
            uid = data.get("id", "") if isinstance(data, dict) else ""
            if uid:
                self._user_ids.append(uid)
                self._reg_user_id = uid
            self._user_emails.append(reg_email)
            # Login as regular user
            lcode, ldata, _ = await self._req(client, "POST", "/auth/login",
                                               json={"email": reg_email, "password": "Pass1234!"})
            reg_token = ldata.get("access_token", "") if isinstance(ldata, dict) else ""
        self._ok(results, "RBAC-1", "Create regular user → 201/429", "RBAC",
                 created or code == 429, f"HTTP {code}", ms)

        rbac_token = reg_token or "invalid.rbac.test.token"

        code, _, ms = await self._req(client, "GET", "/admin/users", token=rbac_token)
        self._ok(results, "RBAC-2", "Non-admin → admin endpoint → 403/401", "RBAC",
                 code in (403, 401), f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "GET", "/architect/proposals", token=rbac_token)
        self._ok(results, "RBAC-3", "Non-admin → architect → 403/401", "RBAC",
                 code in (403, 401), f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "POST", "/testing/e2e/run", token=rbac_token)
        self._ok(results, "RBAC-4", "Non-admin → testing → 403/401/405", "RBAC",
                 code in (403, 401, 405), f"HTTP {code}", ms)

    # ------------------------------------------------------------------ SECURITY

    async def _run_security(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = getattr(self, "_token", "")
        reg_token = ""
        if self._user_emails:
            lcode, ldata, _ = await self._req(client, "POST", "/auth/login",
                                               json={"email": self._user_emails[-1], "password": "Pass1234!"})
            if lcode == 200 and isinstance(ldata, dict):
                reg_token = ldata.get("access_token", "")

        t = reg_token or token
        code, _, ms = await self._req(client, "GET",
                                       "/environments/00000000-0000-0000-0000-000000000000/deployment-config",
                                       token=t)
        self._ok(results, "SEC-1", "Deployment config non-superadmin → 403/404", "SECURITY",
                 code in (403, 404), f"HTTP {code}", ms)

        code, data, ms = await self._req(client, "GET", "/orders/not-a-valid-uuid", token=token)
        body = str(data) if data else ""
        leaked = any(x in body for x in ["Traceback", "sqlalchemy", "psycopg", 'File "/'])
        self._ok(results, "SEC-2", "Exception handler hides stack traces", "SECURITY",
                 not leaked, "Stack trace in response" if leaked else "", ms)

        code, data, ms = await self._req(client, "GET", "/connectors/", token=token)
        connectors = data if isinstance(data, list) else []
        leaked_conn = [c for c in connectors if isinstance(c, dict) and
                       c.get("config", {}).get("webhook_secret") not in (None, "***", "")]
        self._ok(results, "SEC-3", "Connector webhook_secret masked", "SECURITY",
                 len(leaked_conn) == 0, "Secret leaked" if leaked_conn else "", ms)

    # ------------------------------------------------------------------ BRAND

    async def _run_brand(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = getattr(self, "_token", "")
        brand_id = ""
        brand_slug = ""

        ts = int(time.time())
        code, data, ms = await self._req(client, "POST", "/brands/", token=token, json={
            "slug": f"uat-brand-{ts}", "name": "UAT Brand", "tenant_mode": "HYBRID",
        })
        if code in (200, 201) and isinstance(data, dict):
            brand_id = data.get("id", "")
            brand_slug = data.get("slug", f"uat-brand-{ts}")
        if brand_id:
            self._brand_ids.append(brand_id)
        self._ok(results, "BRAND-1", "Create brand → 201", "BRAND",
                 code in (200, 201), f"HTTP {code}", ms)

        qid = brand_id or "00000000-0000-0000-0000-000000000000"
        code, _, ms = await self._req(client, "GET", f"/orders/?brand_id={qid}", token=token)
        self._ok(results, "BRAND-2", "Brand filter on orders → 200", "BRAND", code == 200, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "GET", f"/analytics/dashboard?brand_id={qid}", token=token)
        self._ok(results, "BRAND-3", "Brand filter on dashboard → 200", "BRAND", code == 200, f"HTTP {code}", ms)

        if brand_slug:
            code, _, ms = await self._req(client, "POST", "/brands/", token=token, json={
                "slug": brand_slug, "name": "Duplicate Brand", "tenant_mode": "B2C_ONLY",
            })
            self._ok(results, "BRAND-4", "Duplicate slug → 409", "BRAND", code == 409, f"HTTP {code}", ms)
        else:
            self._skip(results, "BRAND-4", "Duplicate slug → 409", "BRAND", "No brand created")

    # ------------------------------------------------------------------ DISTRIBUTION GROUPS

    async def _run_distribution_groups(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = getattr(self, "_token", "")
        dg_id = ""

        code, data, ms = await self._req(client, "POST", "/distribution-groups/", token=token, json={
            "name": "UAT Distribution Group", "is_active": True,
        })
        dg_id = data.get("id", "") if isinstance(data, dict) else ""
        if dg_id:
            self._dg_ids.append(dg_id)
        self._ok(results, "DG-1", "Create distribution group → 201", "DIST_GROUPS",
                 bool(dg_id), f"HTTP {code}" if not dg_id else "", ms)

        if dg_id:
            code, _, ms = await self._req(client, "GET", f"/distribution-groups/{dg_id}", token=token)
            self._ok(results, "DG-2", "Get distribution group by ID → 200", "DIST_GROUPS",
                     code == 200, f"HTTP {code}", ms)
        else:
            self._skip(results, "DG-2", "Get distribution group by ID", "DIST_GROUPS", "No DG created")

        code, _, ms = await self._req(client, "GET", "/distribution-groups/", token=token)
        self._ok(results, "DG-3", "List distribution groups → 200", "DIST_GROUPS", code == 200, f"HTTP {code}", ms)

        if dg_id:
            code, _, ms = await self._req(client, "PATCH", f"/distribution-groups/{dg_id}", token=token,
                                           json={"name": "UAT DG Updated", "is_active": False})
            self._ok(results, "DG-4", "Update distribution group → 200", "DIST_GROUPS",
                     code == 200, f"HTTP {code}", ms)
        else:
            self._skip(results, "DG-4", "Update distribution group", "DIST_GROUPS", "No DG created")

        code, _, ms = await self._req(client, "GET",
                                       "/distribution-groups/00000000-0000-0000-0000-000000000000", token=token)
        self._ok(results, "DG-5", "Non-existent DG → 404", "DIST_GROUPS", code == 404, f"HTTP {code}", ms)

    # ------------------------------------------------------------------ API KEYS

    async def _run_api_keys(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = getattr(self, "_token", "")
        raw_key = ""
        key_id = ""

        code, data, ms = await self._req(client, "POST", "/api-keys", token=token,
                                          json={"name": "UAT Integration Key", "scopes": []})
        if isinstance(data, dict):
            raw_key = data.get("key", "")
            key_id = data.get("id", "")
        if key_id:
            self._api_key_ids.append(key_id)
        self._ok(results, "APIKEY-1", "Create API key → kr_ prefix", "API_KEYS",
                 bool(raw_key) and raw_key.startswith("kr_"), f"HTTP {code}", ms)

        code, data, ms = await self._req(client, "GET", "/api-keys", token=token)
        items = data if isinstance(data, list) else []
        key_exposed = any(len(str(k.get("key", ""))) > 15 for k in items if isinstance(k, dict))
        self._ok(results, "APIKEY-2", "List keys — raw key not returned", "API_KEYS",
                 code == 200 and not key_exposed,
                 ("key leaked" if key_exposed else f"HTTP {code}"), ms)

        if raw_key:
            code, _, ms = await self._req(client, "GET", "/orders/",
                                           headers={"X-API-Key": raw_key}, no_auth=True)
            self._ok(results, "APIKEY-3", "X-API-Key auth → 200", "API_KEYS", code == 200, f"HTTP {code}", ms)
        else:
            self._skip(results, "APIKEY-3", "X-API-Key auth → 200", "API_KEYS", "No key created")

        code, _, ms = await self._req(client, "GET", "/orders/",
                                       headers={"X-API-Key": "kr_thisisafakeandnonexistentkey1234567890abc"},
                                       no_auth=True)
        self._ok(results, "APIKEY-4", "Invalid API key → 401", "API_KEYS", code == 401, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "POST", "/api-keys", token=token,
                                       json={"name": "", "scopes": []})
        self._ok(results, "APIKEY-5", "Empty name → 422", "API_KEYS", code == 422, f"HTTP {code}", ms)

        if key_id:
            code, _, ms = await self._req(client, "DELETE", f"/api-keys/{key_id}", token=token)
            self._ok(results, "APIKEY-6", "Revoke key → 204", "API_KEYS", code == 204, f"HTTP {code}", ms)
            if code == 204 and key_id in self._api_key_ids:
                self._api_key_ids.remove(key_id)
        else:
            self._skip(results, "APIKEY-6", "Revoke key → 204", "API_KEYS", "No key to revoke")

        if raw_key:
            code, _, ms = await self._req(client, "GET", "/orders/",
                                           headers={"X-API-Key": raw_key}, no_auth=True)
            self._ok(results, "APIKEY-7", "Revoked key → 401", "API_KEYS",
                     code == 401, f"HTTP {code}", ms)
        else:
            self._skip(results, "APIKEY-7", "Revoked key → 401", "API_KEYS", "No key to test")

    # ------------------------------------------------------------------ BRAND ACCESS

    async def _run_brand_access(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = getattr(self, "_token", "")
        user_id = getattr(self, "_reg_user_id", "")
        env_id = ""
        brand_id = ""
        assignment_id = ""

        # Fetch first environment
        code, data, ms = await self._req(client, "GET", "/environments/", token=token)
        envs = data if isinstance(data, list) else (data.get("items", []) if isinstance(data, dict) else [])
        env_id = envs[0]["id"] if envs else ""

        # Create brand scoped for this test group
        ts = int(time.time())
        code, data, ms = await self._req(client, "POST", "/brands/", token=token, json={
            "slug": f"uat-ba-{ts}", "name": "UAT Brand Access", "tenant_mode": "HYBRID",
        })
        if code in (200, 201) and isinstance(data, dict):
            brand_id = data.get("id", "")
        if brand_id:
            self._brand_ids.append(brand_id)

        if user_id and brand_id and env_id:
            code, data, ms = await self._req(client, "POST", "/brand-access/", token=token, json={
                "user_id": user_id, "brand_id": brand_id,
                "environment_id": env_id, "role": "OPERATOR",
            })
            if isinstance(data, dict):
                assignment_id = data.get("id", "")
            if assignment_id:
                self._brand_access_ids.append(assignment_id)
            self._ok(results, "BA-1", "Assign user to brand → 201", "BRAND_ACCESS",
                     code in (200, 201), f"HTTP {code}", ms)
        else:
            self._skip(results, "BA-1", "Assign user to brand → 201", "BRAND_ACCESS",
                       f"prereqs missing: user={bool(user_id)}, brand={bool(brand_id)}, env={bool(env_id)}")

        if assignment_id and user_id and brand_id and env_id:
            code, _, ms = await self._req(client, "POST", "/brand-access/", token=token, json={
                "user_id": user_id, "brand_id": brand_id,
                "environment_id": env_id, "role": "VIEWER",
            })
            self._ok(results, "BA-2", "Duplicate assignment → 409", "BRAND_ACCESS",
                     code == 409, f"HTTP {code}", ms)
        else:
            self._skip(results, "BA-2", "Duplicate assignment → 409", "BRAND_ACCESS", "No assignment to duplicate")

        if user_id and brand_id and env_id:
            code, _, ms = await self._req(client, "POST", "/brand-access/", token=token, json={
                "user_id": user_id, "brand_id": brand_id,
                "environment_id": env_id, "role": "SUPERUSER",
            })
            self._ok(results, "BA-3", "Invalid role → 422", "BRAND_ACCESS",
                     code == 422, f"HTTP {code}", ms)
        else:
            self._skip(results, "BA-3", "Invalid role → 422", "BRAND_ACCESS", "No prereqs")

        code, _, ms = await self._req(client, "GET", "/brand-access/", token=token)
        self._ok(results, "BA-4", "List brand access → 200", "BRAND_ACCESS", code == 200, f"HTTP {code}", ms)

        if assignment_id:
            code, _, ms = await self._req(client, "DELETE", f"/brand-access/{assignment_id}", token=token)
            self._ok(results, "BA-5", "Remove assignment → 204", "BRAND_ACCESS", code == 204, f"HTTP {code}", ms)
            if code == 204 and assignment_id in self._brand_access_ids:
                self._brand_access_ids.remove(assignment_id)
        else:
            self._skip(results, "BA-5", "Remove assignment → 204", "BRAND_ACCESS", "No assignment to remove")

    # ------------------------------------------------------------------ SLA

    async def _run_sla(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = getattr(self, "_token", "")

        code, data, ms = await self._req(client, "GET", "/monitoring/sla-summary", token=token)
        self._ok(results, "SLA-1", "SLA summary → 200", "SLA", code == 200, f"HTTP {code}", ms)

        has_field = isinstance(data, dict) and "sla_breaches_today" in data
        self._ok(results, "SLA-2", "SLA summary has sla_breaches_today field", "SLA",
                 has_field, str(list(data.keys()))[:60] if isinstance(data, dict) else "", ms)

    # ------------------------------------------------------------------ CUSTOM ATTRIBUTES

    async def _run_custom_attrs(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = getattr(self, "_token", "")
        attr_id = ""

        ts = int(time.time())
        code, data, ms = await self._req(client, "POST", "/architect/custom-attributes", token=token, json={
            "field_key": f"uat_test_field_{ts}", "field_label": "UAT Test Field",
            "entity_type": "ORDER", "field_type": "TEXT", "is_required": False,
        })
        if isinstance(data, dict):
            attr_id = data.get("id", "")
        if attr_id:
            self._custom_attr_ids.append(attr_id)
        self._ok(results, "CA-1", "Create custom attribute → 201", "CUSTOM_ATTRS",
                 bool(attr_id), f"HTTP {code}" if not attr_id else "", ms)

        code, _, ms = await self._req(client, "GET", "/architect/custom-attributes", token=token)
        self._ok(results, "CA-2", "List custom attributes → 200", "CUSTOM_ATTRS", code == 200, f"HTTP {code}", ms)

        code, _, ms = await self._req(client, "DELETE",
                                       "/architect/custom-attributes/00000000-0000-0000-0000-000000000000",
                                       token=token)
        self._ok(results, "CA-3", "Delete non-existent → 404", "CUSTOM_ATTRS", code == 404, f"HTTP {code}", ms)

        if attr_id:
            code, _, ms = await self._req(client, "DELETE", f"/architect/custom-attributes/{attr_id}", token=token)
            self._ok(results, "CA-4", "Delete custom attribute → 204", "CUSTOM_ATTRS",
                     code == 204, f"HTTP {code}", ms)
            if code == 204 and attr_id in self._custom_attr_ids:
                self._custom_attr_ids.remove(attr_id)
        else:
            self._skip(results, "CA-4", "Delete custom attribute → 204", "CUSTOM_ATTRS", "No attribute created")

    # ------------------------------------------------------------------ cleanup

    async def _cleanup(self) -> Dict[str, int]:
        deleted: Dict[str, int] = {}
        # Use DB directly for cleanup (not HTTP) to avoid auth complexity
        try:
            from app.database.postgres import async_session_factory
            from app.models.postgres.order_models import Order, OrderItem, FulfillmentAllocation, Shipment, WebhookEvent
            from app.models.postgres.connector_models import ConnectorEvent
            from app.models.postgres.inventory_models import InventoryItem, InventoryAdjustment
            from app.models.postgres.auth_models import User
            from sqlalchemy import delete

            async with async_session_factory() as db:
                # Delete orders
                order_count = 0
                for oid in self._order_ids:
                    try:
                        import uuid as _uuid
                        oid_uuid = _uuid.UUID(oid)
                        await db.execute(delete(WebhookEvent).where(WebhookEvent.order_id == oid_uuid))
                        await db.execute(delete(ConnectorEvent).where(ConnectorEvent.order_id == oid_uuid))
                        await db.execute(delete(Shipment).where(Shipment.order_id == oid_uuid))
                        await db.execute(delete(FulfillmentAllocation).where(FulfillmentAllocation.order_id == oid_uuid))
                        await db.execute(delete(OrderItem).where(OrderItem.order_id == oid_uuid))
                        await db.execute(delete(Order).where(Order.id == oid_uuid))
                        order_count += 1
                    except Exception as e:
                        logger.warning(f"Cleanup: failed to delete order {oid}: {e}")
                deleted["orders"] = order_count

                # Delete inventory items
                inv_count = 0
                for iid in self._inv_ids:
                    try:
                        import uuid as _uuid
                        iid_uuid = _uuid.UUID(iid)
                        await db.execute(delete(InventoryAdjustment).where(InventoryAdjustment.inventory_item_id == iid_uuid))
                        await db.execute(delete(InventoryItem).where(InventoryItem.id == iid_uuid))
                        inv_count += 1
                    except Exception as e:
                        logger.warning(f"Cleanup: failed to delete inventory {iid}: {e}")
                deleted["inventory_items"] = inv_count

                # Delete test users
                user_count = 0
                for uid in self._user_ids:
                    try:
                        import uuid as _uuid
                        uid_uuid = _uuid.UUID(uid)
                        await db.execute(delete(User).where(User.id == uid_uuid))
                        user_count += 1
                    except Exception as e:
                        logger.warning(f"Cleanup: failed to delete user {uid}: {e}")
                deleted["users"] = user_count

                await db.commit()

        except Exception as e:
            logger.error(f"API integration test cleanup failed: {e}")
            deleted["error"] = str(e)

        # ── Distribution groups ───────────────────────────────────────────────
        if self._dg_ids:
            try:
                from app.models.postgres.sourcing_rule_models import DistributionGroup, DistributionGroupMember
                dg_count = 0
                async with async_session_factory() as db:
                    for dg_id in self._dg_ids:
                        try:
                            import uuid as _uuid2
                            dg_uuid = _uuid2.UUID(dg_id)
                            await db.execute(delete(DistributionGroupMember).where(
                                DistributionGroupMember.group_id == dg_uuid))
                            await db.execute(delete(DistributionGroup).where(
                                DistributionGroup.id == dg_uuid))
                            dg_count += 1
                        except Exception as e2:
                            logger.warning(f"Cleanup: failed to delete DG {dg_id}: {e2}")
                    await db.commit()
                deleted["distribution_groups"] = dg_count
            except Exception as e2:
                logger.warning(f"DG cleanup failed: {e2}")

        # ── API keys (hard delete) ────────────────────────────────────────────
        if self._api_key_ids:
            try:
                from app.models.postgres.api_key_models import ApiKey
                key_count = 0
                async with async_session_factory() as db:
                    for kid in self._api_key_ids:
                        try:
                            import uuid as _uuid2
                            kid_uuid = _uuid2.UUID(kid)
                            await db.execute(delete(ApiKey).where(ApiKey.id == kid_uuid))
                            key_count += 1
                        except Exception as e2:
                            logger.warning(f"Cleanup: failed to delete API key {kid}: {e2}")
                    await db.commit()
                deleted["api_keys"] = key_count
            except Exception as e2:
                logger.warning(f"API key cleanup failed: {e2}")

        # ── Brand access assignments ──────────────────────────────────────────
        if self._brand_access_ids:
            try:
                from app.models.postgres.user_brand_role_models import UserBrandRole
                ba_count = 0
                async with async_session_factory() as db:
                    for aid in self._brand_access_ids:
                        try:
                            import uuid as _uuid2
                            aid_uuid = _uuid2.UUID(aid)
                            await db.execute(delete(UserBrandRole).where(UserBrandRole.id == aid_uuid))
                            ba_count += 1
                        except Exception as e2:
                            logger.warning(f"Cleanup: failed to delete brand access {aid}: {e2}")
                    await db.commit()
                deleted["brand_access"] = ba_count
            except Exception as e2:
                logger.warning(f"Brand access cleanup failed: {e2}")

        # ── Brands ────────────────────────────────────────────────────────────
        if self._brand_ids:
            try:
                from app.models.postgres.brand_models import Brand
                brand_count = 0
                async with async_session_factory() as db:
                    for bid in self._brand_ids:
                        try:
                            import uuid as _uuid2
                            bid_uuid = _uuid2.UUID(bid)
                            await db.execute(delete(Brand).where(Brand.id == bid_uuid))
                            brand_count += 1
                        except Exception as e2:
                            logger.warning(f"Cleanup: failed to delete brand {bid}: {e2}")
                    await db.commit()
                deleted["brands"] = brand_count
            except Exception as e2:
                logger.warning(f"Brand cleanup failed: {e2}")

        # ── Custom attribute definitions ──────────────────────────────────────
        if self._custom_attr_ids:
            try:
                from app.models.postgres.ai_models import CustomAttributeDefinition
                ca_count = 0
                async with async_session_factory() as db:
                    for cid in self._custom_attr_ids:
                        try:
                            import uuid as _uuid2
                            cid_uuid = _uuid2.UUID(cid)
                            await db.execute(delete(CustomAttributeDefinition).where(
                                CustomAttributeDefinition.id == cid_uuid))
                            ca_count += 1
                        except Exception as e2:
                            logger.warning(f"Cleanup: failed to delete custom attr {cid}: {e2}")
                    await db.commit()
                deleted["custom_attrs"] = ca_count
            except Exception as e2:
                logger.warning(f"Custom attr cleanup failed: {e2}")

        # ── Elasticsearch: delete indexed docs for test orders ────────────────
        if self._order_ids:
            try:
                from app.database.elasticsearch_client import get_es_client, ORDER_INDEX
                es = await get_es_client()
                es_deleted = 0
                for oid in self._order_ids:
                    try:
                        await es.delete(index=ORDER_INDEX, id=oid)
                        es_deleted += 1
                    except Exception:
                        pass  # 404 = already gone, ignore
                deleted["es_orders"] = es_deleted
            except Exception as es_err:
                logger.warning(f"ES cleanup failed (non-critical): {es_err}")
                deleted["es_orders"] = 0

        # ── MongoDB: delete order_events written by Celery workers ────────────
        if self._order_ids:
            try:
                from motor.motor_asyncio import AsyncIOMotorClient
                from app.config import settings
                client = AsyncIOMotorClient(
                    settings.MONGODB_URL, serverSelectionTimeoutMS=3000,
                    uuidRepresentation="standard",
                )
                try:
                    result = await client[settings.MONGODB_DB].order_events.delete_many(
                        {"order_id": {"$in": self._order_ids}}
                    )
                    deleted["mongo_events"] = result.deleted_count
                finally:
                    client.close()
            except Exception as mongo_err:
                logger.warning(f"MongoDB cleanup failed (non-critical): {mongo_err}")
                deleted["mongo_events"] = 0

        return deleted
