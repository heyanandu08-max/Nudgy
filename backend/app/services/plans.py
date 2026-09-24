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
    # billing interval ("month" | "year") → env var holding the Stripe price ID
    price_envs: dict[str, str] = field(default_factory=dict)
    # billing interval → price shown in the app, e.g. "$20"
    labels: dict[str, str] = field(default_factory=dict)
    per_seat: bool = False

    def stripe_price(self, interval: str = "month") -> str | None:
        env = self.price_envs.get(interval)
        return os.environ.get(env) or None if env else None

    def offer(self) -> dict[str, str]:
        """Intervals that can actually be bought, with their labels."""
        return {i: self.labels.get(i, "") for i in self.price_envs if self.stripe_price(i)}


@lru_cache
def plans() -> dict[str, Plan]:
    raw = load_yaml("plans.yaml")["plans"]
    return {
        pid: Plan(
            id=pid,
            name=p["name"],
            paid=bool(p.get("paid", False)),
            features=p.get("features", {}),
            price_envs=dict(p.get("prices") or {}),
            labels=dict(p.get("labels") or {}),
            per_seat=bool(p.get("per_seat", False)),
        )
        for pid, p in raw.items()
    }


def get_plan(plan_id: str) -> Plan:
    return plans().get(plan_id) or plans()["free"]


def plan_for_price(price_id: str | None) -> str | None:
    for p in plans().values():
        if price_id and price_id in (p.stripe_price(i) for i in p.price_envs):
            return p.id
    return None


def coupon(name: str) -> str | None:
    c = load_yaml("plans.yaml").get("coupons", {}).get(name)
    return os.environ.get(c["stripe_coupon_env"]) if c else None
