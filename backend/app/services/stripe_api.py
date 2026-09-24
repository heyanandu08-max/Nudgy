"""Minimal Stripe client over httpx (form-encoded REST) + webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx

API = "https://api.stripe.com/v1"
TOLERANCE = 300


class StripeError(Exception):
    pass


def _flatten(data: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Stripe's nested form encoding: a[b][0][c]=v."""
    out: list[tuple[str, str]] = []
    for k, v in data.items():
        key = f"{prefix}[{k}]" if prefix else k
        if isinstance(v, dict):
            out += _flatten(v, key)
        elif isinstance(v, list):
            for i, item in enumerate(v):
                out += (
                    _flatten(item, f"{key}[{i}]")
                    if isinstance(item, dict)
                    else [(f"{key}[{i}]", str(item))]
                )
        elif isinstance(v, bool):
            out.append((key, "true" if v else "false"))
        elif v is not None:
            out.append((key, str(v)))
    return out


class StripeClient:
    def __init__(self, secret_key: str | None, transport: httpx.BaseTransport | None = None):
        if not secret_key:
            raise StripeError("STRIPE_SECRET_KEY is not set")
        self.http = httpx.Client(
            base_url=API, auth=(secret_key, ""), timeout=20, transport=transport
        )

    def _post(self, path: str, data: dict) -> dict:
        r = self.http.post(
            path,
            content=urlencode(_flatten(data)),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code >= 400:
            raise StripeError(
                r.json().get("error", {}).get("message", f"Stripe error {r.status_code}")
            )
        return r.json()

    def create_customer(self, email: str, user_id: int) -> str:
        return self._post("/customers", {"email": email, "metadata": {"user_id": user_id}})["id"]

    def create_checkout(
        self,
        *,
        customer: str,
        price: str,
        quantity: int,
        user_id: int,
        plan: str,
        success_url: str,
        cancel_url: str,
        coupon: str | None,
    ) -> str:
        data: dict = {
            "mode": "subscription",
            "customer": customer,
            "client_reference_id": user_id,
            "line_items": [{"price": price, "quantity": quantity}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {"user_id": user_id, "plan": plan},
            "subscription_data": {"metadata": {"user_id": user_id, "plan": plan}},
        }
        # Stripe allows either a fixed discount or user-entered promotion codes, not both.
        if coupon:
            data["discounts"] = [{"coupon": coupon}]
        else:
            data["allow_promotion_codes"] = True
        return self._post("/checkout/sessions", data)["url"]

    def create_portal(self, customer: str, return_url: str) -> str:
        return self._post(
            "/billing_portal/sessions", {"customer": customer, "return_url": return_url}
        )["url"]


def verify_signature(payload: bytes, header: str, secret: str, now: int | None = None) -> None:
    """Checks the Stripe-Signature header (t=…,v1=…): HMAC-SHA256 of "{t}.{payload}"."""
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        k, _, v = item.strip().partition("=")
        parts.setdefault(k, []).append(v)
    try:
        ts = int(parts["t"][0])
    except (KeyError, ValueError) as e:
        raise StripeError("malformed signature header") from e
    if abs((now or int(time.time())) - ts) > TOLERANCE:
        raise StripeError("signature timestamp outside tolerance")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in parts.get("v1", [])):
        raise StripeError("signature mismatch")


def sign(payload: bytes, secret: str, ts: int | None = None) -> str:
    """Builds a valid Stripe-Signature header (tests and local tooling)."""
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"
