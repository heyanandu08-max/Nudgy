import json

import httpx
import pytest

from app import paypal_setup
from app.services.paypal_api import PayPalClient


class FakePayPal:
    """Just enough of PayPal's catalog, plans and webhooks APIs."""

    def __init__(self):
        self.products, self.plans, self.webhooks = [], [], []
        self.posts = 0

    def __call__(self, r: httpx.Request) -> httpx.Response:
        path = r.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if r.method == "GET":
            if path == "/v1/catalogs/products":
                return httpx.Response(200, json={"products": self.products})
            if path == "/v1/billing/plans":
                pid = r.url.params["product_id"]
                return httpx.Response(
                    200, json={"plans": [p for p in self.plans if p["product_id"] == pid]}
                )
            if path == "/v1/notifications/webhooks":
                return httpx.Response(200, json={"webhooks": self.webhooks})
        body = json.loads(r.content)
        self.posts += 1
        if path == "/v1/catalogs/products":
            item = {"id": f"PROD-{len(self.products)}", **body}
            self.products.append(item)
        elif path == "/v1/billing/plans":
            item = {"id": f"P-{len(self.plans)}", **body}
            self.plans.append(item)
        elif path == "/v1/notifications/webhooks":
            item = {"id": f"WH-{len(self.webhooks)}", **body}
            self.webhooks.append(item)
        else:
            return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND"})
        return httpx.Response(201, json=item)


def client(fake):
    return PayPalClient("id", "secret", "sandbox", transport=httpx.MockTransport(fake))


def test_creates_everything_once_and_reuses_it():
    fake = FakePayPal()
    url = "https://api.nudgy.test/v1/billing/webhook"
    first = paypal_setup.run(client(fake), team_price=8, webhook_url=url)
    assert first == {
        "PAYPAL_ENV": "sandbox",
        "PAYPAL_PLAN_PRO": "P-0",
        "PAYPAL_PLAN_PRO_YEARLY": "P-1",
        "PAYPAL_PLAN_TEAM": "P-2",
        "PAYPAL_WEBHOOK_ID": "WH-0",
    }
    pro, year, team = fake.plans

    def price(plan):
        return plan["billing_cycles"][0]["pricing_scheme"]["fixed_price"]

    assert price(pro) == {"value": "20.00", "currency_code": "USD"}
    assert year["billing_cycles"][0]["frequency"]["interval_unit"] == "YEAR"
    assert price(year)["value"] == "40.00"
    assert team.get("quantity_supported") is True and "quantity_supported" not in pro
    events = {e["name"] for e in fake.webhooks[0]["event_types"]}
    assert "BILLING.SUBSCRIPTION.ACTIVATED" in events and "PAYMENT.SALE.COMPLETED" in events

    posts = fake.posts
    assert paypal_setup.run(client(fake), team_price=8, webhook_url=url) == first
    assert fake.posts == posts  # nothing duplicated


def test_new_price_makes_a_new_plan_and_webhook_needs_https():
    fake = FakePayPal()
    paypal_setup.run(client(fake))
    again = paypal_setup.run(client(fake), pro_month=25)
    assert again["PAYPAL_PLAN_PRO"] == "P-2" and again["PAYPAL_PLAN_PRO_YEARLY"] == "P-1"
    with pytest.raises(ValueError):
        paypal_setup.run(client(fake), webhook_url="http://127.0.0.1:8787/v1/billing/webhook")


def test_cli_explains_missing_credentials(monkeypatch, capsys):
    from app.config import Settings

    monkeypatch.setattr(paypal_setup, "get_settings", lambda: Settings(_env_file=None))
    assert paypal_setup.main([]) == 1
    assert "PAYPAL_CLIENT_ID" in capsys.readouterr().err
