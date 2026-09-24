"""Plans from config/plans.yaml (see that file for semantics)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from app.config import load_yaml


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    paid: bool
    features: dict[str, bool] = field(default_factory=dict)
    stripe_price_env: str | None = None
    per_seat: bool = False

    @property
    def stripe_price(self) -> str | None:
        return os.environ.get(self.stripe_price_env) if self.stripe_price_env else None


@lru_cache
def plans() -> dict[str, Plan]:
    raw = load_yaml("plans.yaml")["plans"]
    return {
        pid: Plan(
            id=pid,
            name=p["name"],
            paid=bool(p.get("paid", False)),
            features=p.get("features", {}),
            stripe_price_env=p.get("stripe_price_env"),
            per_seat=bool(p.get("per_seat", False)),
        )
        for pid, p in raw.items()
    }


def get_plan(plan_id: str) -> Plan:
    return plans().get(plan_id) or plans()["free"]


def plan_for_price(price_id: str | None) -> str | None:
    for p in plans().values():
        if price_id and p.stripe_price == price_id:
            return p.id
    return None


def coupon(name: str) -> str | None:
    c = load_yaml("plans.yaml").get("coupons", {}).get(name)
    return os.environ.get(c["stripe_coupon_env"]) if c else None
