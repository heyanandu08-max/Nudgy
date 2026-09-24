"""OpenAI-compatible gateway providers (LLM, STT, TTS) against a mocked HTTP server."""

import asyncio
import functools
import json

import httpx
import pytest

from app.config import Settings
from app.providers.base import ImagePart, Message, ProviderError, Usage, collect
from app.providers.http_stt import OpenAIWhisperSTT
from app.providers.http_tts import OpenAITTS
from app.providers.openai_compat_llm import OpenAICompatibleLLM, v1_url
from app.providers.registry import build_llm, build_stt, build_tts

KEY = "gateway-test-key"


def sync(fn):
    """Runs an async test body (the suite uses asyncio.run, no async plugin)."""

    @functools.wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return run


class Server:
    def __init__(self, respond):
        self.requests: list[httpx.Request] = []
        self.respond = respond

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        return self.respond(req)


def sse(*chunks: dict) -> httpx.Response:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)


def delta(text: str) -> dict:
    return {"choices": [{"delta": {"content": text}, "finish_reason": None}]}


MESSAGES = [Message("user", [ImagePart(b"\xff\xd8jpeg"), "how do I bold this?"])]


def llm(server: Server, **kw) -> OpenAICompatibleLLM:
    return OpenAICompatibleLLM(
        "http://127.0.0.1:31415", KEY, "some-model", transport=httpx.MockTransport(server), **kw
    )


def test_v1_url_accepts_base_with_or_without_v1():
    assert v1_url("http://h:1", "/audio/speech") == "http://h:1/v1/audio/speech"
    assert v1_url("http://h:1/v1/", "/audio/speech") == "http://h:1/v1/audio/speech"
    gemini = "https://generativelanguage.googleapis.com/v1beta/openai"
    assert v1_url(gemini, "/chat/completions") == f"{gemini}/chat/completions"
    assert v1_url("https://api.groq.com/openai/v1", "/chat/completions").endswith(
        "/openai/v1/chat/completions"
    )


@sync
async def test_streams_deltas_with_image_and_usage():
    server = Server(
        lambda r: sse(
            delta('{"speech": "Press '),
            delta('Control B."}'),
            {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 5}},
        )
    )
    usage = Usage()
    text = await collect(
        llm(server), system="be brief", messages=MESSAGES, max_tokens=100, usage=usage
    )
    assert text == '{"speech": "Press Control B."}'
    assert (usage.input_tokens, usage.output_tokens) == (12, 5)
    req = server.requests[0]
    assert str(req.url) == "http://127.0.0.1:31415/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert body["model"] == "some-model" and body["stream"] is True
    assert body["messages"][0] == {"role": "system", "content": "be brief"}
    parts = body["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "how do I bold this?"}
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


@sync
async def test_without_vision_sends_text_only():
    server = Server(lambda r: sse(delta("ok")))
    await collect(
        llm(server, vision=False), system="s", messages=MESSAGES, max_tokens=10, usage=Usage()
    )
    assert json.loads(server.requests[0].content)["messages"][1] == {
        "role": "user",
        "content": "how do I bold this?",
    }


@sync
async def test_gateway_that_ignores_stream_returns_one_json_body():
    server = Server(
        lambda r: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )
    )
    usage = Usage()
    assert (
        await collect(llm(server), system="s", messages=MESSAGES, max_tokens=10, usage=usage)
        == "hello"
    )
    assert usage.input_tokens == 3


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [(401, "llm_auth", False), (429, "llm_rate_limited", True), (503, "llm_failed", True)],
)
@sync
async def test_errors_map_to_stable_codes(status, code, retryable):
    server = Server(lambda r: httpx.Response(status, json={"error": "x"}))
    with pytest.raises(ProviderError) as e:
        await collect(llm(server), system="s", messages=MESSAGES, max_tokens=10, usage=Usage())
    assert (e.value.code, e.value.retryable) == (code, retryable)


@sync
async def test_unreachable_gateway():
    def down(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderError) as e:
        await collect(
            llm(Server(down)), system="s", messages=MESSAGES, max_tokens=10, usage=Usage()
        )
    assert e.value.code == "llm_unreachable" and e.value.retryable


@sync
async def test_gateway_tts_like_deepgram_aura():
    """Matches: POST /v1/audio/speech {"model": "@cf/deepgram/aura-2-en", "input": ...}."""
    server = Server(
        lambda r: httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"ID3mp3")
    )
    tts = OpenAITTS(
        KEY,
        "@cf/deepgram/aura-2-en",
        base_url="http://127.0.0.1:31415",
        default_voice=None,
        transport=httpx.MockTransport(server),
    )
    assert await tts.synthesize("Hello world", voice_id=None, language="en") == b"ID3mp3"
    req = server.requests[0]
    assert str(req.url) == "http://127.0.0.1:31415/v1/audio/speech"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(req.content) == {"model": "@cf/deepgram/aura-2-en", "input": "Hello world"}
    assert tts.mime == "audio/mpeg"


@sync
async def test_gateway_tts_sends_a_picked_voice():
    server = Server(
        lambda r: httpx.Response(200, headers={"content-type": "audio/wav"}, content=b"RIFF")
    )
    tts = OpenAITTS(
        KEY, "m", base_url="http://g", default_voice=None, transport=httpx.MockTransport(server)
    )
    await tts.synthesize("hi", voice_id="luna", language="en")
    assert json.loads(server.requests[0].content)["voice"] == "luna"
    assert tts.mime == "audio/wav"


@sync
async def test_gateway_stt():
    server = Server(lambda r: httpx.Response(200, json={"text": " how do I bold this "}))
    stt = OpenAIWhisperSTT(
        KEY,
        "@cf/openai/whisper",
        base_url="http://127.0.0.1:31415/v1",
        transport=httpx.MockTransport(server),
    )
    assert await stt.transcribe(b"RIFF", mime="audio/wav", language="en") == "how do I bold this"
    req = server.requests[0]
    assert str(req.url) == "http://127.0.0.1:31415/v1/audio/transcriptions"
    assert b"@cf/openai/whisper" in req.content


def test_registry_builds_gateway_providers():
    s = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        stt_provider="openai_compatible",
        tts_provider="openai_compatible",
        gateway_url="http://127.0.0.1:31415",
        gateway_key=KEY,
        llm_model="m",
        stt_model="@cf/openai/whisper",
        tts_model="@cf/deepgram/aura-2-en",
    )
    assert build_llm(s).name == "openai_compatible"
    assert build_stt(s).url.endswith("/v1/audio/transcriptions")
    tts = build_tts(s)
    assert tts.url.endswith("/v1/audio/speech") and tts.default_voice is None
    with pytest.raises(ProviderError, match="NUDGY_TTS_MODEL"):
        build_tts(s.model_copy(update={"tts_model": ""}))
    with pytest.raises(ProviderError, match="NUDGY_GATEWAY_URL"):
        build_llm(s.model_copy(update={"gateway_url": None}))


def test_llm_can_use_its_own_service_while_voice_uses_the_gateway():
    s = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        tts_provider="openai_compatible",
        gateway_url="http://127.0.0.1:31415",
        gateway_key=KEY,
        llm_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        llm_api_key="other-key",
        llm_model="vision-model",
        tts_model="@cf/deepgram/aura-2-en",
    )
    llm = build_llm(s)
    assert llm.url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert llm.headers["Authorization"] == "Bearer other-key"
    assert build_tts(s).url == "http://127.0.0.1:31415/v1/audio/speech"
