import json
import re
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_engine
from app.main import create_app
from app.models import UsageEvent, User
from app.providers.fake import FakeLLM, FakeSTT, FakeTTS
from app.providers.registry import Providers, get_providers
from app.routers.auth import get_apple, get_google, get_mailer, get_oauth_http, optional_stripe
from app.routers.billing import get_stripe
from app.services import auth
from app.services.email import ConsoleEmail
from app.services.stripe_api import StripeClient, sign

WEBHOOK_SECRET = "whsec_test"


class FakeVerifier:
    def __init__(self, email="ada@example.com", name="Ada"):
        self.email, self.name, self.seen = email, name, []

    def verify(self, id_token):
        self.seen.append(id_token)
        if id_token == "bad":
            raise auth.AuthError("invalid")
        return auth.Identity(email=self.email, name=self.name)


class StripeRecorder:
    """Mock Stripe REST API; records form posts."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        self.calls.append((req.url.path, form))
        if req.url.path == "/v1/customers":
            return httpx.Response(200, json={"id": "cus_123"})
        if req.url.path == "/v1/checkout/sessions":
            return httpx.Response(
                200, json={"id": "cs_1", "url": "https://checkout.stripe.test/cs_1"}
            )
        if req.method == "DELETE" and req.url.path.startswith("/v1/subscriptions/"):
            return httpx.Response(200, json={"id": req.url.path.rsplit("/", 1)[1]})
        if req.url.path == "/v1/billing_portal/sessions":
            return httpx.Response(200, json={"url": "https://billing.stripe.test/p"})
        return httpx.Response(404, json={"error": {"message": "nope"}})


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_PRO", "price_pro")
    monkeypatch.setenv("STRIPE_PRICE_TEAM", "price_team")
    monkeypatch.setenv("STRIPE_COUPON_STUDENT", "coupon_student")
    settings = Settings(
        jwt_secret="test-secret-0123456789-0123456789-abcdef",
        public_url="https://nudgy.test",
        auth_required=True,
        google_client_id="gid",
        google_client_secret="gsecret",
        apple_client_id="app.nudgy.signin",
    )
    settings.stripe_webhook_secret = WEBHOOK_SECRET
    mailer = ConsoleEmail()
    google, apple = FakeVerifier(), FakeVerifier(email="apple@example.com")
    stripe = StripeRecorder()
    app = create_app()
    app.dependency_overrides.update(
        {
            get_settings: lambda: settings,
            get_mailer: lambda: mailer,
            get_google: lambda: google,
            get_apple: lambda: apple,
            get_stripe: lambda: StripeClient(
                "sk_test", transport=httpx.MockTransport(stripe.handler)
            ),
            optional_stripe: lambda: StripeClient(
                "sk_test", transport=httpx.MockTransport(stripe.handler)
            ),
            get_providers: lambda: Providers(llm=FakeLLM(), stt=FakeSTT(), tts=FakeTTS()),
            get_oauth_http: lambda: httpx.Client(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(200, json={"id_token": "google-token"})
                )
            ),
        }
    )
    with TestClient(app) as client:
        yield {
            "client": client,
            "settings": settings,
            "mailer": mailer,
            "google": google,
            "stripe": stripe,
        }


def magic_sign_in(env, email="ada@example.com") -> str:
    c = env["client"]
    assert c.post("/v1/auth/magic", json={"email": email}).json() == {"sent": True}
    to, _subject, body = env["mailer"].sent[-1]
    assert to == email
    link = re.search(r"https://nudgy\.test/auth/magic\?token=\S+", body).group(0)
    page = c.get(link.replace("https://nudgy.test", ""))
    assert page.status_code == 200
    return parse_qs(urlparse(re.search(r'href="(nudgy://auth\?[^"]+)"', page.text).group(1)).query)[
        "token"
    ][0]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def ask(env, token, text="how do I change the font?"):
    return env["client"].post(
        "/v1/ask", data={"context": json.dumps({"text": text})}, headers=bearer(token)
    )


def webhook(env, event: dict, secret=WEBHOOK_SECRET):
    payload = json.dumps(event).encode()
    return env["client"].post(
        "/v1/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": sign(payload, secret), "Content-Type": "application/json"},
    )


def use_up(user_email: str, kind: str, n: int):
    with Session(get_engine()) as db:
        user = db.query(User).filter_by(email=user_email).one()
        db.add_all([UsageEvent(user_id=user.id, kind=kind) for _ in range(n)])
        db.commit()


# --- auth ---


def test_magic_link_signs_in_once(env):
    token = magic_sign_in(env)
    me = env["client"].get("/v1/me", headers=bearer(token)).json()
    assert me["email"] == "ada@example.com"
    assert me["plan"] == "free" and me["limits"]["asks"] == 30 and me["usage"]["asks"] == 0
    # The same link cannot be used twice.
    _, _, body = env["mailer"].sent[-1]
    link = re.search(r"/auth/magic\?token=\S+", body).group(0)
    assert "already used" in env["client"].get(link).text


def test_expired_and_forged_tokens(env):
    s = env["settings"]
    expired = auth._encode(s, {"purpose": "magic", "email": "x@y.z", "jti": "j"}, -10)
    assert "expired" in env["client"].get(f"/auth/magic?token={expired}").text
    forged = auth._encode(
        Settings(jwt_secret="another-secret-0123456789-0123456789-xyz"),
        {"purpose": "session", "sub": "1", "email": "x"},
        60,
    )
    r = env["client"].get("/v1/me", headers=bearer(forged))
    assert r.status_code == 401 and r.json()["detail"]["code"] == "auth_expired"
    magic = auth.issue_magic(s, "x@y.z")
    assert env["client"].get("/v1/me", headers=bearer(magic)).status_code == 401  # wrong purpose


def test_google_sign_in(env):
    state = auth.issue_state(env["settings"], "google")
    page = env["client"].get(f"/v1/auth/google/callback?code=abc&state={state}")
    assert "nudgy://auth?token=" in page.text
    assert env["google"].seen == ["google-token"]
    bad = env["client"].get("/v1/auth/google/callback?code=abc&state=forged")
    assert "Please try again" in bad.text


def test_google_start_redirects_with_state(env):
    r = env["client"].get("/v1/auth/google/start", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["client_id"] == ["gid"] and q["redirect_uri"] == [
        "https://nudgy.test/v1/auth/google/callback"
    ]
    auth.check_state(env["settings"], q["state"][0], "google")


def test_apple_sign_in_form_post(env):
    state = auth.issue_state(env["settings"], "apple")
    page = env["client"].post(
        "/v1/auth/apple/callback", data={"state": state, "id_token": "apple-token", "code": "c"}
    )
    token = parse_qs(
        urlparse(re.search(r'href="(nudgy://auth\?[^"]+)"', page.text).group(1)).query
    )["token"][0]
    assert env["client"].get("/v1/me", headers=bearer(token)).json()["email"] == "apple@example.com"
    google_state = auth.issue_state(env["settings"], "google")
    assert (
        "Please try again"
        in env["client"]
        .post("/v1/auth/apple/callback", data={"state": google_state, "id_token": "x"})
        .text
    )


def test_jwks_verifier_checks_signature_issuer_and_audience():
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    v = auth.JwksVerifier("https://example/jwks", ["https://accounts.google.com"], "gid")

    class K:
        def __init__(self, k):
            self.key = k

    v.client.get_signing_key_from_jwt = lambda _t: K(key.public_key())
    now = int(time.time())
    good = {
        "iss": "https://accounts.google.com",
        "aud": "gid",
        "email": "A@B.C",
        "email_verified": True,
        "exp": now + 60,
    }
    import jwt as pyjwt

    tok = lambda c: pyjwt.encode(c, key, algorithm="RS256")
    assert v.verify(tok(good)).email == "a@b.c"
    for bad in (
        {**good, "aud": "other"},
        {**good, "iss": "https://evil"},
        {**good, "email_verified": False},
        {**good, "exp": now - 5},
    ):
        with pytest.raises(auth.AuthError):
            v.verify(tok(bad))
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(auth.AuthError):
        v.verify(pyjwt.encode(good, other, algorithm="RS256"))


def test_auth_required_blocks_anonymous_ai_calls(env):
    r = env["client"].post("/v1/ask", data={"context": json.dumps({"text": "hi"})})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "auth_required"
    assert env["client"].get("/v1/me").status_code == 401


# --- limits ---


def test_free_ask_limit_then_402(env):
    token = magic_sign_in(env)
    use_up("ada@example.com", "asks", 29)
    assert ask(env, token).status_code == 200  # the 30th
    r = ask(env, token)
    assert r.status_code == 402
    assert r.json()["detail"] | {"message": ""} == {
        "code": "limit_reached",
        "kind": "asks",
        "limit": 30,
        "plan": "free",
        "message": "",
    }


def test_lesson_limit_is_separate(env):
    token = magic_sign_in(env)
    use_up("ada@example.com", "lessons", 3)
    r = env["client"].post(
        "/v1/lessons/plan", data={"context": json.dumps({"goal": "x"})}, headers=bearer(token)
    )
    assert r.status_code == 402 and r.json()["detail"]["kind"] == "lessons"
    assert ask(env, token).status_code == 200


def test_usage_tokens_recorded_after_stream(env):
    token = magic_sign_in(env)
    ask(env, token)
    with Session(get_engine()) as db:
        ev = db.query(UsageEvent).filter_by(kind="asks").one()
        assert ev.tokens_in > 0 and ev.tokens_out > 0


# --- billing ---


def test_checkout_creates_customer_and_session(env):
    token = magic_sign_in(env)
    r = env["client"].post("/v1/billing/checkout", json={"plan": "pro"}, headers=bearer(token))
    assert r.json() == {"url": "https://checkout.stripe.test/cs_1"}
    paths = [p for p, _ in env["stripe"].calls]
    assert paths == ["/v1/customers", "/v1/checkout/sessions"]
    form = env["stripe"].calls[1][1]
    assert form["line_items[0][price]"] == "price_pro" and form["line_items[0][quantity]"] == "1"
    assert form["mode"] == "subscription" and form["allow_promotion_codes"] == "true"
    assert form["metadata[plan]"] == "pro" and form["success_url"].startswith(
        "https://nudgy.test/billing/done"
    )
    # Second checkout reuses the customer; student discount applies the coupon.
    env["client"].post(
        "/v1/billing/checkout", json={"plan": "pro", "student": True}, headers=bearer(token)
    )
    assert [p for p, _ in env["stripe"].calls][2:] == ["/v1/checkout/sessions"]
    assert env["stripe"].calls[2][1]["discounts[0][coupon]"] == "coupon_student"
    assert "allow_promotion_codes" not in env["stripe"].calls[2][1]


def test_checkout_needs_account_and_configured_price(env, monkeypatch):
    assert env["client"].post("/v1/billing/checkout", json={"plan": "pro"}).status_code == 401
    token = magic_sign_in(env)
    monkeypatch.delenv("STRIPE_PRICE_PRO")
    r = env["client"].post("/v1/billing/checkout", json={"plan": "pro"}, headers=bearer(token))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "config"


def test_webhook_rejects_bad_signatures(env):
    ev = {"id": "evt_x", "type": "checkout.session.completed", "data": {"object": {}}}
    assert webhook(env, ev, secret="wrong").status_code == 400
    payload = json.dumps(ev).encode()
    old = sign(payload, WEBHOOK_SECRET, ts=int(time.time()) - 3600)
    r = env["client"].post(
        "/v1/billing/webhook", content=payload, headers={"Stripe-Signature": old}
    )
    assert r.status_code == 400
    r = env["client"].post("/v1/billing/webhook", content=payload)
    assert r.status_code == 400


def test_signup_hit_limit_pay_and_get_upgraded(env):
    """The Phase 7 'done when' scenario, end to end with a mocked Stripe."""
    token = magic_sign_in(env, "grace@example.com")
    use_up("grace@example.com", "asks", 30)
    assert ask(env, token).status_code == 402

    assert (
        env["client"]
        .post("/v1/billing/checkout", json={"plan": "pro"}, headers=bearer(token))
        .status_code
        == 200
    )
    user_id = env["client"].get("/v1/me", headers=bearer(token)).json()["id"]
    completed = {
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": "cus_123",
                "subscription": "sub_1",
                "client_reference_id": str(user_id),
                "metadata": {"user_id": str(user_id), "plan": "pro"},
            }
        },
    }
    assert webhook(env, completed).json() == {"outcome": "upgraded:pro"}
    assert webhook(env, completed).json() == {
        "outcome": "duplicate"
    }  # Stripe retries are idempotent

    me = env["client"].get("/v1/me", headers=bearer(token)).json()
    assert (
        me["plan"] == "pro"
        and me["subscription_status"] == "active"
        and me["limits"]["asks"] == 1500
    )
    assert ask(env, token).status_code == 200

    # Cancelling in the portal downgrades via the subscription webhook.
    deleted = {
        "id": "evt_2",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_1", "customer": "cus_123", "status": "canceled"}},
    }
    assert webhook(env, deleted).json() == {"outcome": "downgraded"}
    assert env["client"].get("/v1/me", headers=bearer(token)).json()["plan"] == "free"


def test_subscription_updates_map_price_to_plan(env):
    token = magic_sign_in(env)
    uid = env["client"].get("/v1/me", headers=bearer(token)).json()["id"]
    upd = {
        "id": "evt_3",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_9",
                "status": "active",
                "metadata": {"user_id": str(uid)},
                "items": {"data": [{"price": {"id": "price_pro"}, "quantity": 1}]},
            }
        },
    }
    assert webhook(env, upd).json() == {"outcome": "plan:pro"}
    failed = {
        "id": "evt_4",
        "type": "invoice.payment_failed",
        "data": {"object": {"customer": None, "metadata": {"user_id": str(uid)}}},
    }
    assert webhook(env, failed).json() == {"outcome": "past_due"}
    assert (
        env["client"].get("/v1/me", headers=bearer(token)).json()["plan"] == "pro"
    )  # kept while Stripe retries


def test_portal(env):
    token = magic_sign_in(env)
    assert env["client"].post("/v1/billing/portal", headers=bearer(token)).status_code == 400
    env["client"].post("/v1/billing/checkout", json={"plan": "pro"}, headers=bearer(token))
    assert (
        env["client"]
        .post("/v1/billing/portal", headers=bearer(token))
        .json()["url"]
        .startswith("https://billing")
    )


# --- teams ---


def test_team_plan_invites_and_shared_library(env):
    owner = magic_sign_in(env, "boss@acme.com")
    uid = env["client"].get("/v1/me", headers=bearer(owner)).json()["id"]
    team_paid = {
        "id": "evt_t",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": "cus_t",
                "subscription": "sub_t",
                "metadata": {"user_id": str(uid), "plan": "team", "seats": "2"},
            }
        },
    }
    assert webhook(env, team_paid).json()["outcome"] == "upgraded:team"
    team = env["client"].get("/v1/team", headers=bearer(owner)).json()
    assert (
        team["owner"]
        and team["seats"] == 2
        and [m["email"] for m in team["members"]] == ["boss@acme.com"]
    )

    assert env["client"].post(
        "/v1/team/invites", json={"email": "new@acme.com"}, headers=bearer(owner)
    ).json() == {"invited": True}
    r = env["client"].post(
        "/v1/team/invites", json={"email": "third@acme.com"}, headers=bearer(owner)
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_seats"

    member = magic_sign_in(env, "new@acme.com")  # accepting = signing in with the invited address
    me = env["client"].get("/v1/me", headers=bearer(member)).json()
    assert me["plan"] == "team" and me["team"]["owner"] is False
    assert (
        env["client"]
        .post("/v1/team/invites", json={"email": "x@acme.com"}, headers=bearer(member))
        .status_code
        == 403
    )

    doc = {
        "id": "w",
        "title": "Onboarding: expense report",
        "app": "SAP",
        "steps": [{"instruction": "Open Expenses."}],
    }
    assert (
        env["client"]
        .post("/v1/walkthroughs", json={"walkthrough": doc, "team": True}, headers=bearer(owner))
        .status_code
        == 200
    )
    library = env["client"].get("/v1/team/walkthroughs", headers=bearer(member)).json()
    assert [w["title"] for w in library] == ["Onboarding: expense report"]

    outsider = magic_sign_in(env, "solo@else.com")
    assert env["client"].get("/v1/team/walkthroughs", headers=bearer(outsider)).status_code == 403
    r = env["client"].post(
        "/v1/walkthroughs", json={"walkthrough": doc, "team": True}, headers=bearer(outsider)
    )
    assert r.status_code == 403


def test_export_lists_what_the_server_holds(env):
    assert env["client"].get("/v1/me/export").status_code == 401
    token = magic_sign_in(env, "ada@example.com")
    ask(env, token)
    doc = {"id": "w", "title": "Tabs", "app": "Chrome", "steps": [{"instruction": "Open a tab."}]}
    env["client"].post("/v1/walkthroughs", json={"walkthrough": doc}, headers=bearer(token))
    data = env["client"].get("/v1/me/export", headers=bearer(token)).json()
    assert data["format"] == "nudgy-account-export"
    assert data["account"]["email"] == "ada@example.com"
    assert [u["kind"] for u in data["usage"]] == ["asks"]
    assert data["shared_walkthroughs"][0]["document"]["title"] == "Tabs"
    # Metadata only: no screenshots, audio or question text are ever stored server-side.
    assert "how do I change the font" not in json.dumps(data)


def test_delete_account_cancels_billing_and_dissolves_team(env):
    owner = magic_sign_in(env, "boss@acme.com")
    uid = env["client"].get("/v1/me", headers=bearer(owner)).json()["id"]
    webhook(
        env,
        {
            "id": "evt_d",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_d",
                    "subscription": "sub_d",
                    "metadata": {"user_id": str(uid), "plan": "team", "seats": "3"},
                }
            },
        },
    )
    env["client"].post("/v1/team/invites", json={"email": "m@acme.com"}, headers=bearer(owner))
    member = magic_sign_in(env, "m@acme.com")
    doc = {"id": "w", "title": "Onboarding", "app": "SAP", "steps": [{"instruction": "Go."}]}
    env["client"].post(
        "/v1/walkthroughs", json={"walkthrough": doc, "team": True}, headers=bearer(owner)
    )

    r = env["client"].delete("/v1/me", headers=bearer(owner))
    assert r.status_code == 200
    assert r.json()["deleted"] is True and r.json()["team_dissolved"] is True
    assert ("/v1/subscriptions/sub_d", {}) in env["stripe"].calls
    assert env["client"].get("/v1/me", headers=bearer(owner)).status_code == 401
    me = env["client"].get("/v1/me", headers=bearer(member)).json()
    assert me["plan"] == "free" and me["team"] is None


def test_delete_free_account_without_billing(env):
    token = magic_sign_in(env, "solo@example.com")
    ask(env, token)
    assert env["client"].delete("/v1/me", headers=bearer(token)).json()["usage"] == 1
    assert env["client"].delete("/v1/me", headers=bearer(token)).status_code == 401
    # Signing in again starts a fresh, empty account.
    again = magic_sign_in(env, "solo@example.com")
    assert env["client"].get("/v1/me/export", headers=bearer(again)).json()["usage"] == []
