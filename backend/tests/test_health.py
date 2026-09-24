def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_client_config_lists_english_default(client):
    r = client.get("/v1/config")
    assert r.status_code == 200
    body = r.json()
    defaults = [lang for lang in body["languages"] if lang["default"]]
    assert [lang["code"] for lang in defaults] == ["en"]
    assert body["voices"], "voices for the configured TTS provider should not be empty"


def test_cors_allows_tauri_origin(client):
    r = client.get("/health", headers={"Origin": "tauri://localhost"})
    assert r.headers.get("access-control-allow-origin") == "tauri://localhost"


def test_production_refuses_unsafe_defaults():
    import pytest

    from app.config import Settings

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        Settings(env="prod").check_production_safety()
    Settings(
        env="prod",
        jwt_secret="x" * 40,
        auth_required=True,
        email_provider="smtp",
    ).check_production_safety()
    Settings(env="dev").check_production_safety()  # dev stays key-less
