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
from app.routers.auth import get_apple, get_google, get_mailer, get_oauth_http
from app.routers.billing import get_paypal, optional_paypal
from app.services import auth
from app.services.email import ConsoleEmail
from app.services.paypal_api import PayPalClient

WEBHOOK_ID = "WH-TEST"


class FakeVerifier:
    def __init__(self, email="ada@example.com", name="Ada"):
        self.email, self.name, self.seen = email, name, []

    def verify(self, id_token):
        self.seen.append(id_token)
        if id_token == "bad":
            raise auth.AuthError("invalid")
        return auth.Identity(email=self.email, name=self.name)


class PayPalMock:
    """Mock PayPal REST API: OAuth, subscriptions (with a fake buyer approval step) and
    webhook verification (only deliveries signed "good" verify)."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.subs: dict[str, dict] = {}
        self.raw: list[bytes] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        body = json.loads(req.content) if req.content and path != "/v1/oauth2/token" else {}
        self.calls.append((req.method, path, body))
        self.raw.append(req.content)
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if path == "/v1/billing/subscriptions" and req.method == "POST":
            sid = f"I-{len(self.subs) + 1}"
            self.subs[sid] = {
                "id": sid,
                "plan_id": body["plan_id"],
                "custom_id": body["custom_id"],
                "quantity": body.get("quantity", "1"),
                "status": "APPROVAL_PENDING",
            }
            return httpx.Response(
                201,
                json={
                    **self.subs[sid],
                    "links": [{"rel": "approve", "href": f"https://paypal.test/approve/{sid}"}],
                },
            )
        if path.startswith("/v1/billing/subscriptions/") and path.endswith("/cancel"):
            self.subs.setdefault(path.split("/")[4], {})["status"] = "CANCELLED"
            return httpx.Response(204)
        if path.startswith("/v1/billing/subscriptions/"):
            sub = self.subs.get(path.rsplit("/", 1)[1])
            return (
                httpx.Response(200, json=sub)
                if sub
                else httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND"})
            )
        if path == "/v1/notifications/verify-webhook-signature":
            ok = body.get("transmission_sig") == "good" and body.get("webhook_id") == WEBHOOK_ID
            return httpx.Response(200, json={"verification_status": "SUCCESS" if ok else "FAILURE"})
        return httpx.Response(404, json={"name": "NOT_FOUND"})

    def approve(self, sid: str, next_billing: str = "2099-01-01T00:00:00Z") -> dict:
        """What happens when the buyer approves on PayPal's page."""
        self.subs[sid].update(status="ACTIVE", billing_info={"next_billing_time": next_billing})
        return self.subs[sid]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("PAYPAL_PLAN_PRO", "P-PRO")
    monkeypatch.setenv("PAYPAL_PLAN_TEAM", "P-TEAM")
    settings = Settings(
        jwt_secret="test-secret-0123456789-0123456789-abcdef",
        public_url="https://nudgy.test",
        auth_required=True,
        google_client_id="gid",
        google_client_secret="gsecret",
        apple_client_id="app.nudgy.signin",
    )
    settings.paypal_webhook_id = WEBHOOK_ID
    mailer = ConsoleEmail()
    google, apple = FakeVerifier(), FakeVerifier(email="apple@example.com")
    paypal = PayPalMock()
    app = create_app()
    app.dependency_overrides.update(
        {
            get_settings: lambda: settings,
            get_mailer: lambda: mailer,
            get_google: lambda: google,
            get_apple: lambda: apple,
            get_paypal: lambda: PayPalClient(
                "cid", "secret", "sandbox", transport=httpx.MockTransport(paypal.handler)
            ),
            optional_paypal: lambda: PayPalClient(
                "cid", "secret", "sandbox", transport=httpx.MockTransport(paypal.handler)
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
            "paypal": paypal,
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


def plan_lesson(env, token, goal="add up a column"):
    return env["client"].post(
        "/v1/lessons/plan", data={"context": json.dumps({"goal": goal})}, headers=bearer(token)
    )


def webhook(env, event: dict, sig="good"):
    headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.paypal.test/cert",
        "paypal-transmission-id": "t-1",
        "paypal-transmission-sig": sig,
        "paypal-transmission-time": "2027-01-01T00:00:00Z",
        "Content-Type": "application/json",
    }
    return env["client"].post("/v1/billing/webhook", content=json.dumps(event), headers=headers)


def sub_event(eid: str, etype: str, resource: dict) -> dict:
    return {"id": eid, "event_type": etype, "resource": resource}


def subscribe(env, token, **body) -> str:
    """Starts a PayPal subscription through the API; returns its id."""
    r = env["client"].post(
        "/v1/billing/checkout", json={"plan": "pro", **body}, headers=bearer(token)
    )
    assert r.status_code == 200, r.text
    return r.json()["url"].rsplit("/", 1)[1]


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
    assert me["plan"] == "free" and me["paid"] is False and "usage" not in me
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


def test_questions_are_never_capped(env):
    token = magic_sign_in(env)
    use_up("ada@example.com", "asks", 500)
    use_up("ada@example.com", "lesson_calls", 2000)
    assert ask(env, token).status_code == 200


def test_free_tier_lesson_cap_without_launch_date(env):
    """Dev default (no NUDGY_LAUNCH_DATE): no free window, free accounts are capped."""
    token = magic_sign_in(env)
    use_up("ada@example.com", "lessons", 5)
    r = env["client"].post(
        "/v1/lessons/plan", data={"context": json.dumps({"goal": "x"})}, headers=bearer(token)
    )
    assert r.status_code == 402
    detail = r.json()["detail"]
    assert detail["code"] == "limit_reached" and detail["kind"] == "lessons"
    assert (detail["used"], detail["limit"], detail["left"]) == (5, 5, 0)
    assert detail["resets_at"].endswith("-01T00:00:00+00:00")
    assert ask(env, token).status_code == 200  # questions keep working


def test_usage_tokens_recorded_after_stream(env):
    token = magic_sign_in(env)
    ask(env, token)
    with Session(get_engine()) as db:
        ev = db.query(UsageEvent).filter_by(kind="asks").one()
        assert ev.tokens_in > 0 and ev.tokens_out > 0


# --- billing ---


def test_checkout_creates_a_paypal_subscription(env):
    token = magic_sign_in(env)
    uid = env["client"].get("/v1/me", headers=bearer(token)).json()["id"]
    r = env["client"].post("/v1/billing/checkout", json={"plan": "pro"}, headers=bearer(token))
    assert r.json() == {"url": "https://paypal.test/approve/I-1"}
    method, path, body = env["paypal"].calls[-1]
    assert (method, path) == ("POST", "/v1/billing/subscriptions")
    assert body["plan_id"] == "P-PRO" and body["custom_id"] == str(uid)
    ctx = body["application_context"]
    assert ctx["return_url"] == "https://nudgy.test/billing/done?status=success"
    assert ctx["shipping_preference"] == "NO_SHIPPING" and "quantity" not in body
    me = env["client"].get("/v1/me", headers=bearer(token)).json()
    assert me["subscription_status"] == "approval_pending" and me["plan"] == "free"


def test_checkout_needs_account_and_configured_plan(env, monkeypatch):
    assert env["client"].post("/v1/billing/checkout", json={"plan": "pro"}).status_code == 401
    token = magic_sign_in(env)
    monkeypatch.delenv("PAYPAL_PLAN_PRO")
    r = env["client"].post("/v1/billing/checkout", json={"plan": "pro"}, headers=bearer(token))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "config"


def test_webhook_rejects_deliveries_paypal_does_not_verify(env):
    ev = sub_event("WH-x", "BILLING.SUBSCRIPTION.ACTIVATED", {"id": "I-9", "status": "ACTIVE"})
    assert webhook(env, ev, sig="forged").status_code == 400
    r = env["client"].post("/v1/billing/webhook", content=json.dumps(ev))  # no PayPal headers
    assert r.status_code == 400
    env["settings"].paypal_webhook_id = None
    assert webhook(env, ev).status_code == 503


def test_signup_hit_limit_pay_and_get_upgraded(env):
    """Cap reached → subscribe on PayPal → back in Nudgy with Pro right away."""
    token = magic_sign_in(env, "grace@example.com")
    use_up("grace@example.com", "lessons", 5)
    assert plan_lesson(env, token).status_code == 402

    sid = subscribe(env, token)
    env["paypal"].approve(sid)
    # The return page confirms with PayPal (the URL alone is never trusted).
    page = env["client"].get(f"/billing/done?status=success&subscription_id={sid}")
    assert "Your plan is active" in page.text
    me = env["client"].get("/v1/me", headers=bearer(token)).json()
    assert me["plan"] == "pro" and me["subscription_status"] == "active" and me["paid"]
    assert me["access"] == {"notice": None, "capped": False, "lessons": None, "offer": None}
    assert plan_lesson(env, token).status_code == 200

    # The webhook arriving later agrees, and PayPal retries are idempotent.
    activated = sub_event("WH-1", "BILLING.SUBSCRIPTION.ACTIVATED", env["paypal"].subs[sid])
    assert webhook(env, activated).json() == {"outcome": "active:pro"}
    assert webhook(env, activated).json() == {"outcome": "duplicate"}

    # Cancelling keeps Pro until the paid period ends…
    cancelled = sub_event(
        "WH-2",
        "BILLING.SUBSCRIPTION.CANCELLED",
        {**env["paypal"].subs[sid], "status": "CANCELLED"},
    )
    assert webhook(env, cancelled).json() == {"outcome": "canceled"}
    me = env["client"].get("/v1/me", headers=bearer(token)).json()
    assert me["plan"] == "pro" and me["subscription_status"] == "canceled"
    # …and once it's over they're back on Free.
    expired = sub_event("WH-3", "BILLING.SUBSCRIPTION.EXPIRED", {"id": sid, "status": "EXPIRED"})
    assert webhook(env, expired).json() == {"outcome": "downgraded"}
    assert env["client"].get("/v1/me", headers=bearer(token)).json()["plan"] == "free"


def test_cancel_with_paid_period_already_over_is_free(env):
    token = magic_sign_in(env)
    sid = subscribe(env, token)
    sub = env["paypal"].approve(sid, next_billing="2020-01-01T00:00:00Z")
    webhook(env, sub_event("WH-a", "BILLING.SUBSCRIPTION.ACTIVATED", sub))
    webhook(
        env,
        sub_event("WH-c", "BILLING.SUBSCRIPTION.CANCELLED", {**sub, "status": "CANCELLED"}),
    )
    assert env["client"].get("/v1/me", headers=bearer(token)).json()["plan"] == "free"


def test_failed_payment_keeps_the_plan_while_paypal_retries(env):
    token = magic_sign_in(env)
    sid = subscribe(env, token)
    webhook(env, sub_event("WH-a", "BILLING.SUBSCRIPTION.ACTIVATED", env["paypal"].approve(sid)))
    failed = sub_event("WH-f", "BILLING.SUBSCRIPTION.PAYMENT.FAILED", env["paypal"].subs[sid])
    assert webhook(env, failed).json() == {"outcome": "past_due"}
    me = env["client"].get("/v1/me", headers=bearer(token)).json()
    assert me["plan"] == "pro" and me["subscription_status"] == "past_due"
    paid = sub_event("WH-p", "PAYMENT.SALE.COMPLETED", {"billing_agreement_id": sid})
    assert webhook(env, paid).json() == {"outcome": "renewed"}
    assert (
        env["client"].get("/v1/me", headers=bearer(token)).json()["subscription_status"] == "active"
    )
    suspended = sub_event(
        "WH-s", "BILLING.SUBSCRIPTION.SUSPENDED", {"id": sid, "status": "SUSPENDED"}
    )
    assert webhook(env, suspended).json() == {"outcome": "downgraded"}


def test_manage_billing_opens_paypal_autopay(env):
    token = magic_sign_in(env)
    assert env["client"].post("/v1/billing/portal", headers=bearer(token)).status_code == 400
    subscribe(env, token)
    url = env["client"].post("/v1/billing/portal", headers=bearer(token)).json()["url"]
    assert url == "https://www.sandbox.paypal.com/myaccount/autopay/"


def test_return_page_without_paypal_confirmation_changes_nothing(env):
    token = magic_sign_in(env)
    sid = subscribe(env, token)  # never approved on PayPal
    env["client"].get(f"/billing/done?status=success&subscription_id={sid}")
    assert env["client"].get("/v1/me", headers=bearer(token)).json()["plan"] == "free"


# --- teams ---


def test_team_plan_invites_and_shared_library(env):
    owner = magic_sign_in(env, "boss@acme.com")
    uid = env["client"].get("/v1/me", headers=bearer(owner)).json()["id"]
    team_paid = sub_event(
        "WH-t",
        "BILLING.SUBSCRIPTION.ACTIVATED",
        {
            "id": "I-T",
            "plan_id": "P-TEAM",
            "custom_id": str(uid),
            "status": "ACTIVE",
            "quantity": "2",
        },
    )
    assert webhook(env, team_paid).json()["outcome"] == "active:team"
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
        sub_event(
            "WH-d",
            "BILLING.SUBSCRIPTION.ACTIVATED",
            {
                "id": "I-D",
                "plan_id": "P-TEAM",
                "custom_id": str(uid),
                "status": "ACTIVE",
                "quantity": "3",
            },
        ),
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
    assert ("POST", "/v1/billing/subscriptions/I-D/cancel", {"reason": "Account deleted"}) in env[
        "paypal"
    ].calls
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


def test_monthly_and_yearly_pro_prices(env, monkeypatch):
    monkeypatch.setenv("PAYPAL_PLAN_PRO_YEARLY", "P-PRO-YEAR")
    token = magic_sign_in(env)
    # Capped free users are offered both prices (labels from plans.yaml).
    me = env["client"].get("/v1/me", headers=bearer(token)).json()
    assert me["access"]["offer"] == {"month": "$20", "year": "$40"}
    sid = subscribe(env, token, interval="year")
    assert env["paypal"].subs[sid]["plan_id"] == "P-PRO-YEAR"
    # A yearly subscription maps back to Pro.
    webhook(env, sub_event("WH-y", "BILLING.SUBSCRIPTION.ACTIVATED", env["paypal"].approve(sid)))
    me = env["client"].get("/v1/me", headers=bearer(token)).json()
    assert me["plan"] == "pro" and me["access"]["offer"] is None


def test_offer_lists_only_prices_that_exist(env, monkeypatch):
    monkeypatch.delenv("PAYPAL_PLAN_PRO_YEARLY", raising=False)
    token = magic_sign_in(env)
    assert env["client"].get("/v1/access", headers=bearer(token)).json()["offer"] == {
        "month": "$20"
    }
    r = env["client"].post(
        "/v1/billing/checkout", json={"plan": "pro", "interval": "year"}, headers=bearer(token)
    )
    assert r.status_code == 503 and r.json()["detail"]["code"] == "config"


def test_webhook_verification_sends_the_event_exactly_as_received(env):
    ev = sub_event("WH-raw", "BILLING.SUBSCRIPTION.UPDATED", {"id": "I-404", "status": "ACTIVE"})
    raw = json.dumps(ev, indent=3)  # unusual spacing must survive untouched
    headers = {
        "paypal-auth-algo": "a",
        "paypal-cert-url": "c",
        "paypal-transmission-id": "i",
        "paypal-transmission-sig": "good",
        "paypal-transmission-time": "t",
    }
    assert (
        env["client"].post("/v1/billing/webhook", content=raw, headers=headers).status_code == 200
    )
    verify = [c for c in env["paypal"].calls if c[1].endswith("verify-webhook-signature")][-1]
    assert verify[2]["webhook_event"] == ev and verify[2]["webhook_id"] == WEBHOOK_ID
    assert raw.encode() in env["paypal"].raw[env["paypal"].calls.index(verify)]
