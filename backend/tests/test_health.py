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
    safe = {
        "env": "prod",
        "jwt_secret": "x" * 40,
        "auth_required": True,
        "email_provider": "smtp",
        "llm_provider": "anthropic",
        "stt_provider": "deepgram",
        "tts_provider": "elevenlabs",
        "public_url": "https://api.nudgy.test",
    }
    Settings(**safe).check_production_safety()
    with pytest.raises(RuntimeError, match="LLM_PROVIDER"):
        Settings(**{**safe, "llm_provider": "fake"}).check_production_safety()
    with pytest.raises(RuntimeError, match="PUBLIC_URL"):
        Settings(**{**safe, "public_url": "http://127.0.0.1:8787"}).check_production_safety()
    Settings(env="dev").check_production_safety()  # dev stays key-less


def test_packs_are_filtered_by_platform(client):
    everything = client.get("/v1/packs").json()
    ids = {p["id"] for p in everything}
    assert {"excel-basics", "file-explorer", "finder"} <= ids
    for p in everything:
        assert p["lessons"], p["id"]
        assert len({lesson["id"] for lesson in p["lessons"]}) == len(p["lessons"])
    win = {p["id"] for p in client.get("/v1/packs?platform=windows").json()}
    mac = {p["id"] for p in client.get("/v1/packs?platform=mac").json()}
    assert "file-explorer" in win and "finder" not in win
    assert "finder" in mac and "file-explorer" not in mac
    assert "excel-basics" in win and "excel-basics" in mac


def test_packs_are_translated_but_goals_are_not(client):
    en = {p["id"]: p for p in client.get("/v1/packs").json()}
    es = {p["id"]: p for p in client.get("/v1/packs?lang=es").json()}
    assert es["excel-basics"]["title"] == "Excel básico"
    assert es["excel-basics"]["lessons"][1]["title"] == "Sumar una columna"
    assert es["excel-basics"]["lessons"][1]["goal"] == en["excel-basics"]["lessons"][1]["goal"]
    # Unknown languages fall back to English.
    xx = {p["id"]: p for p in client.get("/v1/packs?lang=xx").json()}
    assert xx["excel-basics"]["title"] == en["excel-basics"]["title"] == "Excel basics"
