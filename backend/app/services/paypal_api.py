"""Minimal PayPal Subscriptions client over httpx: OAuth token, create / read / cancel a
subscription, and webhook verification through PayPal's verify-webhook-signature API.

Plans (Nudgy Pro monthly / yearly, Team) are created once in the PayPal dashboard; their IDs
("P-…") come from the environment (see config/plans.yaml).
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping

import httpx

API = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}
# Where a subscriber manages or cancels automatic payments (PayPal has no per-merchant portal).
MANAGE_URL = {
    "sandbox": "https://www.sandbox.paypal.com/myaccount/autopay/",
    "live": "https://www.paypal.com/myaccount/autopay/",
}
WEBHOOK_HEADERS = (
    "paypal-auth-algo",
    "paypal-cert-url",
    "paypal-transmission-id",
    "paypal-transmission-sig",
    "paypal-transmission-time",
)


class PayPalError(Exception):
    pass


class PayPalClient:
    def __init__(
        self,
        client_id: str | None,
        secret: str | None,
        env: str = "sandbox",
        transport: httpx.BaseTransport | None = None,
    ):
        if not client_id or not secret:
            raise PayPalError("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are not set")
        if env not in API:
            raise PayPalError("PAYPAL_ENV must be 'sandbox' or 'live'")
        self.env = env
        self.http = httpx.Client(base_url=API[env], timeout=20, transport=transport)
        self._auth = (client_id, secret)
        self._token: str | None = None
        self._token_until = 0.0

    @property
    def manage_url(self) -> str:
        return MANAGE_URL[self.env]

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_until:
            return self._token
        r = self.http.post(
            "/v1/oauth2/token", data={"grant_type": "client_credentials"}, auth=self._auth
        )
        if r.status_code >= 400:
            raise PayPalError("PayPal rejected the client ID / secret")
        body = r.json()
        self._token = body["access_token"]
        self._token_until = time.monotonic() + max(60, int(body.get("expires_in", 300)) - 60)
        return self._token

    def _request(self, method: str, path: str, *, json_body=None, content: str | None = None):
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
        }
        r = self.http.request(method, path, headers=headers, json=json_body, content=content)
        if r.status_code >= 400:
            try:
                err = r.json()
                msg = err.get("message") or err.get("name") or f"PayPal error {r.status_code}"
            except ValueError:
                msg = f"PayPal error {r.status_code}"
            raise PayPalError(msg)
        return r.json() if r.content else {}

    def create_subscription(
        self, *, plan_id: str, user_id: int, quantity: int, return_url: str, cancel_url: str
    ) -> tuple[str, str]:
        """Returns (subscription id, URL where the buyer approves it)."""
        body: dict = {
            "plan_id": plan_id,
            "custom_id": str(user_id),
            "application_context": {
                "brand_name": "Nudgy",
                "user_action": "SUBSCRIBE_NOW",
                "shipping_preference": "NO_SHIPPING",
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        }
        if quantity > 1:
            body["quantity"] = str(quantity)
        sub = self._request("POST", "/v1/billing/subscriptions", json_body=body)
        approve = next(
            (ln["href"] for ln in sub.get("links", []) if ln.get("rel") == "approve"), None
        )
        if not approve:
            raise PayPalError("PayPal returned no approval link")
        return sub["id"], approve

    def get_subscription(self, subscription_id: str) -> dict:
        return self._request("GET", f"/v1/billing/subscriptions/{subscription_id}")

    def cancel_subscription(self, subscription_id: str, reason: str = "Account deleted") -> None:
        """Stops future payments. Already cancelled/expired subscriptions are fine."""
        try:
            self._request(
                "POST",
                f"/v1/billing/subscriptions/{subscription_id}/cancel",
                json_body={"reason": reason},
            )
        except PayPalError as e:
            if "SUBSCRIPTION_STATUS_INVALID" in str(e) or "RESOURCE_NOT_FOUND" in str(e):
                return
            raise

    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes, webhook_id: str) -> bool:
        """Asks PayPal whether this delivery really came from PayPal. The event is passed
        through byte for byte: re-serializing it can change it and fail verification."""
        values = {h: headers.get(h) for h in WEBHOOK_HEADERS}
        if not all(values.values()):
            return False
        meta = {
            "auth_algo": values["paypal-auth-algo"],
            "cert_url": values["paypal-cert-url"],
            "transmission_id": values["paypal-transmission-id"],
            "transmission_sig": values["paypal-transmission-sig"],
            "transmission_time": values["paypal-transmission-time"],
            "webhook_id": webhook_id,
        }
        body = json.dumps(meta)[:-1] + ', "webhook_event": ' + raw_body.decode() + "}"
        result = self._request("POST", "/v1/notifications/verify-webhook-signature", content=body)
        return result.get("verification_status") == "SUCCESS"
