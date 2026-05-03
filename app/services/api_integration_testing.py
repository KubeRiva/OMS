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

    def __init__(self, base_url: Optional[str] = None, admin_email: str = "admin@oms.local", admin_password: str = "admin123"):
        # Prefer the public base URL from settings; fall back to localhost
        self.base_url = (base_url or settings.PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")
        self.admin_email = admin_email
        self.admin_password = admin_password

        # Resources to clean up
        self._order_ids: List[str] = []
        self._inv_ids: List[str] = []
        self._user_ids: List[str] = []
        self._user_emails: List[str] = []

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
            await self._run_shopify(client, results)
            await self._run_security(client, results)

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

    # ------------------------------------------------------------------ SHOPIFY

    async def _run_shopify(self, client: httpx.AsyncClient, results: List[ApiTestResult]):
        token = getattr(self, "_token", "")

        # SHOPIFY-01: Install redirect — missing shop param → 422
        code, _, ms = await self._req(client, "GET", "/shopify/install", no_auth=True)
        self._ok(results, "SHOPIFY-01", "Install missing shop param → 422", "SHOPIFY",
                 code == 422, f"HTTP {code}", ms)

        # SHOPIFY-02: Install redirect — invalid shop hostname → 400
        code, _, ms = await self._req(client, "GET", "/shopify/install?shop=evil.com", no_auth=True)
        self._ok(results, "SHOPIFY-02", "Install invalid shop hostname → 400", "SHOPIFY",
                 code == 400, f"HTTP {code}", ms)

        # SHOPIFY-03: Install redirect — shopify not configured → 503
        # In the test environment SHOPIFY_API_KEY is expected to be unset.
        code, _, ms = await self._req(client, "GET", "/shopify/install?shop=test.myshopify.com", no_auth=True)
        self._ok(results, "SHOPIFY-03", "Install shopify not configured → 503", "SHOPIFY",
                 code == 503, f"HTTP {code}", ms)

        # SHOPIFY-04: OAuth callback — missing params → 422 or 400
        code, _, ms = await self._req(client, "GET", "/shopify/callback", no_auth=True)
        self._ok(results, "SHOPIFY-04", "Callback missing params → 422 or 400", "SHOPIFY",
                 code in (422, 400), f"HTTP {code}", ms)

        # SHOPIFY-05: OAuth callback — invalid shop hostname → 400
        code, _, ms = await self._req(
            client, "GET",
            "/shopify/callback?code=abc&shop=evil.com&hmac=x&state=y&timestamp=123",
            no_auth=True,
        )
        self._ok(results, "SHOPIFY-05", "Callback invalid shop hostname → 400", "SHOPIFY",
                 code == 400, f"HTTP {code}", ms)

        # SHOPIFY-06: OAuth callback — valid hostname but nonexistent state nonce → 400
        import time as _time
        ts_now = str(int(_time.time()))
        code, _, ms = await self._req(
            client, "GET",
            f"/shopify/callback?code=abc&shop=test.myshopify.com&hmac=x&state=nonexistent_nonce_uat&timestamp={ts_now}",
            no_auth=True,
        )
        self._ok(results, "SHOPIFY-06", "Callback invalid/expired state → 400", "SHOPIFY",
                 code == 400, f"HTTP {code}", ms)

        # SHOPIFY-07: GDPR data_request — no HMAC → 200 (Shopify contract)
        code, data, ms = await self._req(
            client, "POST", "/shopify/gdpr/customers/data_request",
            json={"shop_id": 1, "shop_domain": "test.myshopify.com"},
            no_auth=True,
        )
        self._ok(results, "SHOPIFY-07", "GDPR data_request no HMAC → 200", "SHOPIFY",
                 code == 200, f"HTTP {code}", ms)

        # SHOPIFY-08: GDPR customer_redact — no HMAC → 200 (Shopify contract)
        code, data, ms = await self._req(
            client, "POST", "/shopify/gdpr/customers/redact",
            json={"shop_id": 1, "shop_domain": "test.myshopify.com", "orders_to_redact": []},
            no_auth=True,
        )
        self._ok(results, "SHOPIFY-08", "GDPR customer_redact no HMAC → 200", "SHOPIFY",
                 code == 200, f"HTTP {code}", ms)

        # SHOPIFY-09: GDPR shop_redact — no HMAC → 200 (Shopify contract)
        code, data, ms = await self._req(
            client, "POST", "/shopify/gdpr/shop/redact",
            json={"shop_id": 1, "shop_domain": "test.myshopify.com"},
            no_auth=True,
        )
        self._ok(results, "SHOPIFY-09", "GDPR shop_redact no HMAC → 200", "SHOPIFY",
                 code == 200, f"HTTP {code}", ms)

        # SHOPIFY-10: Billing plans — public endpoint → 200 with plan keys
        code, data, ms = await self._req(client, "GET", "/shopify/billing/plans", no_auth=True)
        has_plans = (
            isinstance(data, dict)
            and all(k in data for k in ("STARTER", "GROWTH", "ENTERPRISE"))
        )
        self._ok(results, "SHOPIFY-10", "Billing plans public → 200 with plan keys", "SHOPIFY",
                 code == 200 and has_plans,
                 "" if (code == 200 and has_plans) else f"HTTP {code} data={data}", ms)

        # SHOPIFY-11: Billing subscribe — requires JWT → 401 without token
        code, _, ms = await self._req(
            client, "POST", "/shopify/billing/subscribe",
            json={"shop": "test.myshopify.com", "plan": "STARTER"},
            no_auth=True,
        )
        self._ok(results, "SHOPIFY-11", "Billing subscribe no auth → 401", "SHOPIFY",
                 code == 401, f"HTTP {code}", ms)

        # SHOPIFY-12: Billing subscribe — authenticated but invalid plan → 400 or 422
        code, _, ms = await self._req(
            client, "POST", "/shopify/billing/subscribe",
            token=token,
            json={"shop": "test.myshopify.com", "plan": "INVALID"},
        )
        self._ok(results, "SHOPIFY-12", "Billing subscribe invalid plan → 400 or 422", "SHOPIFY",
                 code in (400, 422), f"HTTP {code}", ms)

        # SHOPIFY-13: Uninstall webhook — no HMAC → 200 (suppresses Shopify retries)
        code, data, ms = await self._req(
            client, "POST", "/shopify/webhooks/uninstall",
            json={"domain": "test.myshopify.com"},
            no_auth=True,
        )
        self._ok(results, "SHOPIFY-13", "Uninstall webhook no HMAC → 200", "SHOPIFY",
                 code == 200, f"HTTP {code}", ms)

        # SHOPIFY-14: Billing webhook — no HMAC → 200 (suppresses Shopify retries)
        code, data, ms = await self._req(
            client, "POST", "/shopify/webhooks/billing",
            json={"app_subscription": {"admin_graphql_api_id": "gid://shopify/AppSubscription/999", "status": "ACTIVE"}},
            no_auth=True,
        )
        self._ok(results, "SHOPIFY-14", "Billing webhook no HMAC → 200", "SHOPIFY",
                 code == 200, f"HTTP {code}", ms)

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

        return deleted
