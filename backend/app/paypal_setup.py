"""One-time PayPal setup: creates the Nudgy product, the subscription plans and (once the
server has a public https address) the webhook, then prints the lines for .env.

Safe to run again: anything that already exists with the same name / URL is reused, so it
never makes duplicates. A changed price makes a new plan (the old one keeps serving existing
subscribers).

    cd backend
    python -m app.paypal_setup                      # product + Pro monthly/yearly
    python -m app.paypal_setup --team-price 8       # + Team, $8 per seat per month
    python -m app.paypal_setup --webhook-url https://api.example.com/v1/billing/webhook

Reads PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET / PAYPAL_ENV from .env (sandbox first).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from app.config import get_settings
from app.services.paypal_api import PayPalClient, PayPalError

PRODUCT_NAME = "Nudgy Pro"
CURRENCY = "USD"
# The events billing.handle_event acts on.
WEBHOOK_EVENTS = (
    "BILLING.SUBSCRIPTION.ACTIVATED",
    "BILLING.SUBSCRIPTION.CANCELLED",
    "BILLING.SUBSCRIPTION.SUSPENDED",
    "BILLING.SUBSCRIPTION.EXPIRED",
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
    "PAYMENT.SALE.COMPLETED",
)


@dataclass(frozen=True)
class PlanSpec:
    env: str  # the .env variable that will hold the plan ID
    name: str
    unit: str  # MONTH | YEAR
    price: str  # "20.00"
    per_seat: bool = False


def plan_specs(pro_month: float, pro_year: float, team_price: float | None) -> list[PlanSpec]:
    def money(v: float) -> str:
        return f"{v:.2f}"

    specs = [
        PlanSpec(
            "PAYPAL_PLAN_PRO", f"Nudgy Pro monthly ${money(pro_month)}", "MONTH", money(pro_month)
        ),
        PlanSpec(
            "PAYPAL_PLAN_PRO_YEARLY",
            f"Nudgy Pro yearly ${money(pro_year)}",
            "YEAR",
            money(pro_year),
        ),
    ]
    if team_price is not None:
        specs.append(
            PlanSpec(
                "PAYPAL_PLAN_TEAM",
                f"Nudgy Team ${money(team_price)} per seat monthly",
                "MONTH",
                money(team_price),
                per_seat=True,
            )
        )
    return specs


def ensure_product(pp: PayPalClient) -> str:
    found = pp._request("GET", "/v1/catalogs/products?page_size=20&total_required=true")
    for p in found.get("products", []):
        if p.get("name") == PRODUCT_NAME:
            return p["id"]
    created = pp._request(
        "POST",
        "/v1/catalogs/products",
        json_body={
            "name": PRODUCT_NAME,
            "description": "Nudgy, the tutor next to your cursor: unlimited lessons.",
            "type": "SERVICE",
            "category": "SOFTWARE",
        },
    )
    return created["id"]


def ensure_plan(pp: PayPalClient, product_id: str, spec: PlanSpec) -> str:
    found = pp._request("GET", f"/v1/billing/plans?product_id={product_id}&page_size=20")
    for p in found.get("plans", []):
        if p.get("name") == spec.name and p.get("status") == "ACTIVE":
            return p["id"]
    body: dict = {
        "product_id": product_id,
        "name": spec.name,
        "description": spec.name,
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "frequency": {"interval_unit": spec.unit, "interval_count": 1},
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,  # renews until cancelled
                "pricing_scheme": {"fixed_price": {"value": spec.price, "currency_code": CURRENCY}},
            }
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "setup_fee_failure_action": "CONTINUE",
            "payment_failure_threshold": 3,
        },
    }
    if spec.per_seat:
        body["quantity_supported"] = True
    return pp._request("POST", "/v1/billing/plans", json_body=body)["id"]


def ensure_webhook(pp: PayPalClient, url: str) -> str:
    found = pp._request("GET", "/v1/notifications/webhooks")
    for w in found.get("webhooks", []):
        if w.get("url") == url:
            return w["id"]
    created = pp._request(
        "POST",
        "/v1/notifications/webhooks",
        json_body={"url": url, "event_types": [{"name": e} for e in WEBHOOK_EVENTS]},
    )
    return created["id"]


def run(
    pp: PayPalClient,
    *,
    pro_month: float = 20,
    pro_year: float = 40,
    team_price: float | None = None,
    webhook_url: str | None = None,
) -> dict[str, str]:
    """Returns the .env lines to set, as {variable: value}."""
    if webhook_url and not webhook_url.startswith("https://"):
        raise ValueError("PayPal only delivers webhooks to an https:// address")
    out = {"PAYPAL_ENV": pp.env}
    product = ensure_product(pp)
    for spec in plan_specs(pro_month, pro_year, team_price):
        out[spec.env] = ensure_plan(pp, product, spec)
    if webhook_url:
        out["PAYPAL_WEBHOOK_ID"] = ensure_webhook(pp, webhook_url)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--pro-month", type=float, default=20, help="Pro monthly price in USD (20)")
    ap.add_argument("--pro-year", type=float, default=40, help="Pro yearly price in USD (40)")
    ap.add_argument("--team-price", type=float, help="Team price per seat per month in USD")
    ap.add_argument("--webhook-url", help="https://<server>/v1/billing/webhook")
    args = ap.parse_args(argv)

    s = get_settings()
    try:
        pp = PayPalClient(s.paypal_client_id, s.paypal_client_secret, s.paypal_env)
        lines = run(
            pp,
            pro_month=args.pro_month,
            pro_year=args.pro_year,
            team_price=args.team_price,
            webhook_url=args.webhook_url,
        )
    except (PayPalError, ValueError) as e:
        print(f"PayPal setup failed: {e}", file=sys.stderr)
        return 1
    print(f"Done ({pp.env}). Put these in .env, then restart the server:\n")
    for k, v in lines.items():
        print(f"{k}={v}")
    if not args.webhook_url:
        print("\nNo webhook yet: run again with --webhook-url once the server is online.")
    if args.team_price is None:
        print("No Team plan: run again with --team-price <USD per seat> when you've chosen it.")
    if (args.pro_month, args.pro_year) != (20, 40):
        print("Prices differ from the app's labels: update labels in config/plans.yaml.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
