"""Launch date → free year → capped free tier, driven by an overridable server clock."""

import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db import get_engine
from app.deps import get_clock
from app.models import UsageEvent, User
from app.providers.base import ProviderError
from app.providers.fake import FakeLLM, FakeSTT, FakeTTS
from app.providers.registry import Providers, get_providers
from tests.test_accounts import ask, bearer, env, magic_sign_in, plan_lesson  # noqa: F401

ADMIN = "admin-token-0123456789-0123456789-xyz"
LAUNCH = date(2026, 10, 1)  # → FREE_UNTIL 2027-10-01


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 1, 12, tzinfo=UTC)

    def at(self, *args):
        self.now = datetime(*args, tzinfo=UTC)


@pytest.fixture
def launched(env):  # noqa: F811
    env["settings"].launch_date = LAUNCH
    env["settings"].admin_token = ADMIN
    clock = Clock()
    env["client"].app.dependency_overrides[get_clock] = lambda: lambda: clock.now
    env["clock"] = clock
    return env


def access(e, token=None):
    headers = bearer(token) if token else {}
    return e["client"].get("/v1/access", headers=headers).json()


def admin(e, method, path, **kw):
    return e["client"].request(method, path, headers={"X-Admin-Token": ADMIN}, **kw)


def test_free_year_is_unlimited_and_silent(launched):
    token = magic_sign_in(launched)
    launched["clock"].at(2027, 3, 15)
    for _ in range(12):
        r = plan_lesson(launched, token)
        assert r.status_code == 200 and r.json()["quota"] is None
    assert access(launched, token) == {"notice": None, "capped": False, "lessons": None}
    me = launched["client"].get("/v1/me", headers=bearer(token)).json()
    assert me["access"] == {"notice": None, "capped": False, "lessons": None}
    # Still logged for cost tracking.
    with Session(get_engine()) as db:
        lessons = db.query(UsageEvent).filter_by(kind="lessons").all()
        assert len(lessons) == 12 and all(e.tokens_in > 0 for e in lessons)


def test_notice_only_in_the_last_30_days(launched):
    token = magic_sign_in(launched)
    launched["clock"].at(2027, 8, 31, 23, 59)
    assert access(launched, token)["notice"] is None
    launched["clock"].at(2027, 9, 1)
    assert access(launched, token)["notice"] == {"free_until": "2027-10-01", "lessons_per_month": 5}
    assert access(launched)["notice"] is not None  # global: signed-out too
    assert access(launched, token)["capped"] is False


def test_capped_after_free_until_then_resets_monthly(launched):
    token = magic_sign_in(launched)
    launched["clock"].at(2027, 9, 30, 23)
    assert plan_lesson(launched, token).json()["quota"] is None  # last unlimited day
    launched["clock"].at(2027, 10, 1)  # the same date for every account
    lefts = [plan_lesson(launched, token).json()["quota"]["left"] for _ in range(5)]
    assert lefts == [4, 3, 2, 1, 0]
    r = plan_lesson(launched, token)
    assert r.status_code == 402
    assert r.json()["detail"]["resets_at"] == "2027-11-01T00:00:00+00:00"
    assert access(launched, token)["lessons"] == {
        "used": 5,
        "limit": 5,
        "left": 0,
        "resets_at": "2027-11-01T00:00:00+00:00",
    }
    assert ask(launched, token).status_code == 200  # not a lockout
    launched["clock"].at(2027, 11, 1)
    assert plan_lesson(launched, token).json()["quota"]["left"] == 4


def test_lessons_from_the_free_window_do_not_count(launched):
    token = magic_sign_in(launched)
    admin(launched, "PUT", "/v1/admin/access", json={"free_until": "2027-10-15"})
    launched["clock"].at(2027, 10, 10)
    for _ in range(7):
        assert plan_lesson(launched, token).status_code == 200
    launched["clock"].at(2027, 10, 15)
    assert access(launched, token)["lessons"]["used"] == 0


def test_new_signups_after_free_until_start_capped(launched):
    launched["clock"].at(2028, 2, 3)
    token = magic_sign_in(launched, "late@example.com")
    assert access(launched, token)["capped"] is True
    assert access(launched, token)["lessons"]["left"] == 5


def test_failed_plan_is_not_counted(launched):
    class Down(FakeLLM):
        async def stream(self, **kw):
            raise ProviderError("llm_unreachable", "down", retryable=True)
            yield ""  # pragma: no cover

    token = magic_sign_in(launched)
    launched["clock"].at(2027, 10, 2)
    launched["client"].app.dependency_overrides[get_providers] = lambda: Providers(
        llm=Down(), stt=FakeSTT(), tts=FakeTTS()
    )
    assert plan_lesson(launched, token).status_code in (502, 503)
    assert access(launched, token)["lessons"]["used"] == 0


def test_paid_plan_is_never_capped(launched):
    token = magic_sign_in(launched)
    launched["clock"].at(2027, 12, 5)
    assert admin(
        launched, "PUT", "/v1/admin/users/ada@example.com/plan", json={"plan": "pro"}
    ).json() == {"email": "ada@example.com", "plan": "pro"}
    for _ in range(8):
        r = plan_lesson(launched, token)
        assert r.status_code == 200 and r.json()["quota"] is None
    assert access(launched, token) == {"notice": None, "capped": False, "lessons": None}
    launched["clock"].at(2027, 9, 10)
    assert access(launched, token)["notice"] is None  # nothing changes for payers


def test_admin_changes_apply_without_restart(launched):
    token = magic_sign_in(launched)
    assert launched["client"].get("/v1/admin/access").status_code == 403
    cfg = admin(launched, "GET", "/v1/admin/access").json()
    assert cfg == {
        "launch_date": "2026-10-01",
        "free_until": "2027-10-01",
        "free_until_source": "launch_date",
        "free_tier_lessons_per_month": 5,
    }
    launched["clock"].at(2027, 10, 20)
    assert access(launched, token)["capped"] is True
    # Push the date back: unlimited again, the same instant, for everyone.
    cfg = admin(launched, "PUT", "/v1/admin/access", json={"free_until": "2028-01-01"}).json()
    assert cfg["free_until_source"] == "admin"
    assert access(launched, token)["capped"] is False
    # Clearing the override returns to LAUNCH_DATE + 365.
    admin(launched, "PUT", "/v1/admin/access", json={"free_until": None})
    assert access(launched, token)["capped"] is True
    admin(launched, "PUT", "/v1/admin/access", json={"free_tier_lessons_per_month": 2})
    assert access(launched, token)["lessons"]["limit"] == 2
    assert (
        admin(launched, "PUT", "/v1/admin/access", json={"free_until": "2026-01-01"}).status_code
        == 422
    )


def test_admin_api_off_without_token(env):  # noqa: F811
    assert env["client"].get("/v1/admin/access").status_code == 404


def test_env_override_moves_free_until(launched):
    launched["settings"].free_until_override = date(2027, 12, 1)
    token = magic_sign_in(launched)
    launched["clock"].at(2027, 11, 5)
    assert access(launched, token)["notice"]["free_until"] == "2027-12-01"


def test_usage_report(launched):
    a = magic_sign_in(launched, "a@example.com")
    magic_sign_in(launched, "b@example.com")
    launched["clock"].at(2027, 3, 10)
    for _ in range(3):
        plan_lesson(launched, a)
    ask(launched, a)
    with Session(get_engine()) as db:
        b = db.query(User).filter_by(email="b@example.com").one()
        db.add(UsageEvent(user_id=b.id, kind="asks", at=datetime(2027, 3, 11, tzinfo=UTC)))
        db.commit()
    month = admin(launched, "GET", "/v1/admin/usage?months=2").json()
    assert [m["month"] for m in month] == ["2027-03", "2027-02"]
    march = month[0]
    assert march["active_users"] == 2 and march["calls"]["lessons"] == 3
    assert march["lessons_per_user"] == {"p50": 3, "p90": 3, "max": 3}
    assert march["tokens_in"] > 0


def test_new_usage_columns_are_added_to_old_databases(tmp_path, monkeypatch):
    from app import db as dbmod

    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as c:
        c.execute(
            text(
                "CREATE TABLE usage_events (id INTEGER PRIMARY KEY, user_id INTEGER, kind TEXT, "
                "at DATETIME, tokens_in INTEGER, tokens_out INTEGER, latency_ms INTEGER)"
            )
        )
        c.execute(text("INSERT INTO usage_events (user_id, kind) VALUES (1, 'asks')"))
    dbmod._add_missing_columns(eng)
    cols = {c["name"] for c in inspect(eng).get_columns("usage_events")}
    assert {"audio_ms", "tts_chars"} <= cols
    with eng.connect() as c:
        assert c.execute(text("SELECT audio_ms FROM usage_events")).scalar() == 0


def test_lesson_plan_context_is_still_validated(launched):
    token = magic_sign_in(launched)
    r = launched["client"].post(
        "/v1/lessons/plan", data={"context": json.dumps({})}, headers=bearer(token)
    )
    assert r.status_code == 422
