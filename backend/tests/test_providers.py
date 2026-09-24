import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.providers.anthropic_llm import _to_api
from app.providers.base import ImagePart, Message, ProviderError
from app.providers.http_stt import DeepgramSTT, OpenAIWhisperSTT
from app.providers.http_tts import ElevenLabsTTS, OpenAITTS
from app.providers.registry import build_llm, build_stt, build_tts


def run(coro):
    return asyncio.run(coro)


def transport(handler):
    return httpx.MockTransport(handler)


def test_deepgram_request_and_parse():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["ct"] = req.headers["content-type"]
        return httpx.Response(
            200,
            json={
                "results": {"channels": [{"alternatives": [{"transcript": " change the font "}]}]}
            },
        )

    stt = DeepgramSTT("dg-key", transport=transport(handler))
    assert run(stt.transcribe(b"RIFF", mime="audio/wav", language="en")) == "change the font"
    assert seen["auth"] == "Token dg-key"
    assert "model=nova-3" in seen["url"] and "language=en" in seen["url"]
    assert seen["ct"] == "audio/wav"


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (429, "stt_rate_limited", True),
        (401, "stt_auth", False),
        (503, "stt_failed", True),
        (400, "stt_failed", False),
    ],
)
def test_stt_error_mapping(status, code, retryable):
    stt = OpenAIWhisperSTT("k", transport=transport(lambda r: httpx.Response(status)))
    with pytest.raises(ProviderError) as e:
        run(stt.transcribe(b"x", mime="audio/wav", language="en"))
    assert (e.value.code, e.value.retryable) == (code, retryable)


def test_whisper_multipart():
    def handler(req: httpx.Request):
        body = req.content.decode(errors="replace")
        assert 'name="model"' in body and "whisper-1" in body and 'filename="speech.wav"' in body
        return httpx.Response(200, json={"text": "hello"})

    assert (
        run(
            OpenAIWhisperSTT("k", transport=transport(handler)).transcribe(
                b"x", mime="audio/wav", language="en"
            )
        )
        == "hello"
    )


def test_elevenlabs_request():
    def handler(req: httpx.Request):
        assert req.url.path == "/v1/text-to-speech/voice123"
        assert req.headers["xi-api-key"] == "el-key"
        assert json.loads(req.content)["text"] == "Hi there."
        return httpx.Response(200, content=b"MP3DATA")

    tts = ElevenLabsTTS("el-key", transport=transport(handler))
    assert run(tts.synthesize("Hi there.", voice_id="voice123", language="en")) == b"MP3DATA"


def test_openai_tts_default_voice_and_errors():
    def handler(req: httpx.Request):
        assert json.loads(req.content)["voice"] == "alloy"
        return httpx.Response(429)

    with pytest.raises(ProviderError) as e:
        run(
            OpenAITTS("k", transport=transport(handler)).synthesize(
                "x", voice_id=None, language="en"
            )
        )
    assert e.value.code == "tts_rate_limited"


def test_network_failure_is_unreachable():
    def handler(req):
        raise httpx.ConnectError("down")

    with pytest.raises(ProviderError) as e:
        run(
            DeepgramSTT("k", transport=transport(handler)).transcribe(
                b"x", mime="audio/wav", language="en"
            )
        )
    assert e.value.code == "stt_unreachable"


def test_anthropic_message_conversion():
    msgs = [Message(role="user", parts=[ImagePart(b"\xff\xd8jpg"), "What is this?"])]
    api = _to_api(msgs)
    assert api[0]["content"][0]["type"] == "image"
    assert api[0]["content"][0]["source"]["media_type"] == "image/jpeg"
    assert api[0]["content"][0]["source"]["data"] == "/9hqcGc="
    assert api[0]["content"][1] == {"type": "text", "text": "What is this?"}


def test_missing_keys_fail_fast():
    s = Settings(llm_provider="anthropic", stt_provider="deepgram", tts_provider="elevenlabs")
    s.anthropic_api_key = s.deepgram_api_key = s.elevenlabs_api_key = None
    for build in (build_llm, build_stt, build_tts):
        with pytest.raises(ProviderError) as e:
            build(s)
        assert e.value.code == "config"


def test_unknown_provider_is_config_error():
    with pytest.raises(ProviderError):
        build_llm(Settings(llm_provider="nope"))
