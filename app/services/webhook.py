"""HMAC-signed webhook delivery service."""
import hashlib
import hmac
import json
import time
import logging
from datetime import datetime
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class WebhookService:
    def __init__(self):
        self.timeout = settings.WEBHOOK_TIMEOUT_SECONDS
        self.max_retries = settings.WEBHOOK_MAX_RETRIES

    def _sign_payload(self, payload: dict, secret: str) -> str:
        """Generate HMAC-SHA256 signature."""
        payload_bytes = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        signature = hmac.new(
            secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return f"sha256={signature}"

    async def deliver(
        self,
        url: str,
        secret: str,
        payload: dict,
        custom_headers: Optional[dict] = None,
    ) -> tuple[int, str]:
        """Deliver webhook with HMAC signature. Returns (status_code, response_body)."""
        timestamp = int(time.time())
        signed_payload = {**payload, "_timestamp": timestamp}
        signature = self._sign_payload(signed_payload, secret)

        headers = {
            "Content-Type": "application/json",
            "X-OMS-Signature": signature,
            "X-OMS-Timestamp": str(timestamp),
            "X-OMS-Event": payload.get("event_type", "unknown"),
            "User-Agent": "OMS-Webhook/1.0",
        }
        if custom_headers:
            headers.update(custom_headers)

        body = json.dumps(signed_payload, default=str)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, content=body, headers=headers)
            return response.status_code, response.text[:2000]

    def deliver_sync(
        self,
        url: str,
        secret: str,
        payload: dict,
        custom_headers: Optional[dict] = None,
    ) -> tuple[int, str]:
        """Synchronous webhook delivery for Celery tasks."""
        timestamp = int(time.time())
        signed_payload = {**payload, "_timestamp": timestamp}
        signature = self._sign_payload(signed_payload, secret)

        headers = {
            "Content-Type": "application/json",
            "X-OMS-Signature": signature,
            "X-OMS-Timestamp": str(timestamp),
            "X-OMS-Event": payload.get("event_type", "unknown"),
            "User-Agent": "OMS-Webhook/1.0",
        }
        if custom_headers:
            headers.update(custom_headers)

        body = json.dumps(signed_payload, default=str)

        with httpx.Client(timeout=self.timeout) as client:
            try:
                response = client.post(url, content=body, headers=headers)
                return response.status_code, response.text[:2000]
            except httpx.TimeoutException:
                return 0, "Request timed out"
            except httpx.RequestError as e:
                return 0, str(e)
