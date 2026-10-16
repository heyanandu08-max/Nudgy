"""The built-in AI connectors, against fake llama.cpp / whisper.cpp servers."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.base import ImagePart, Message, ProviderError, Usage
from app.providers.local import LocalLLM, LocalWhisperSTT, SystemTTS
from app.providers.registry import Providers, get_providers
from app.schemas.ask import UiElement
from app.services import elements
from tests.sse_utils import parse_sse

ANSWER = {
    "speech": "Click Font name at the top. I've pointed at it.",
    "target": {"element_id": "e2"},
    "action_hint": "click",
}


def llama_server(seen: list):
    """Streams ANSWER back in small pieces, like llama-server's OpenAI-compatible API."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        seen.append(body)
        text = json.dumps(ANSWER)
        pieces = [text[i : i + 9] for i in range(0, len(text), 9)]
        lines = ["data: " + json.dumps({"choices": [{"delta": {"content": p}}]}) for p in pieces]
        lines.append(
            "data: "
            + json.dumps({"choices": [], "usage": {"prompt_tokens": 812, "completion_tokens": 40}})
        )
        lines.append("data: [DONE]")
        return httpx.Response(200, text="\n\n".join(lines) + "\n\n")

    return httpx.MockTransport(handler)


def whisper_server(seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/inference"
        seen.append(request.content)
        return httpx.Response(200, json={"text": " How do I change the font? "})

    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_local_llm_streams_openai_chunks_with_the_image():
    seen: list = []
    llm = LocalLLM("http://127.0.0.1:8790", transport=llama_server(seen))
    usage = Usage()
    msg = Message(role="user", parts=[ImagePart(b"\xff\xd8jpeg"), "UI elements..."])
    out = [d async for d in llm.stream(system="SYS", messages=[msg], max_tokens=4096, usage=usage)]
    assert json.loads("".join(out)) == ANSWER and len(out) > 3
    assert (usage.input_tokens, usage.output_tokens) == (812, 40)
    body = seen[0]
    assert body["messages"][0] == {"role": "system", "content": "SYS"}
    image = body["messages"][1]["content"][0]
    assert image["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert body["response_format"] == {"type": "json_object"} and body["max_tokens"] == 1024


@pytest.mark.anyio
async def test_local_llm_not_running_is_a_friendly_error():
    def refuse(request):
        raise httpx.ConnectError("refused")

    llm = LocalLLM("http://127.0.0.1:1", transport=httpx.MockTransport(refuse))
    with pytest.raises(ProviderError) as e:
        async for _ in llm.stream(system="s", messages=[], max_tokens=10, usage=Usage()):
            pass
    assert e.value.code == "llm_unreachable" and e.value.retryable


@pytest.mark.anyio
async def test_local_whisper_and_system_voice():
    seen: list = []
    stt = LocalWhisperSTT("http://127.0.0.1:8791", transport=whisper_server(seen))
    assert await stt.transcribe(b"RIFF....", mime="audio/wav", language="en") == (
        "How do I change the font?"
    )
    assert b'name="language"' in seen[0] and b"RIFF" in seen[0]
    assert await SystemTTS().synthesize("hi", voice_id=None, language="en") == b""


def test_ask_with_the_built_in_ai_points_and_sends_no_audio():
    seen: list = []
    providers = Providers(
        llm=LocalLLM("http://127.0.0.1:8790", transport=llama_server(seen)),
        stt=LocalWhisperSTT("http://127.0.0.1:8791", transport=whisper_server([])),
        tts=SystemTTS(),
    )
    app = create_app()
    app.dependency_overrides[get_providers] = lambda: providers
    els = [
        {"id": "e1", "role": "button", "name": "Bold", "rect": {"x": 1, "y": 1, "w": 9, "h": 9}},
        {
            "id": "e2",
            "role": "combobox",
            "name": "Font name",
            "rect": {"x": 9, "y": 1, "w": 9, "h": 9},
        },
    ]
    r = TestClient(app).post(
        "/v1/ask",
        data={"context": json.dumps({"elements": els, "screenshot": {"width": 100, "height": 50}})},
        files={"audio": ("q.wav", b"RIFFfake", "audio/wav")},
    )
    events = parse_sse(r.text)
    assert events[0] == ("transcript", {"text": "How do I change the font?"})
    assert "".join(d["delta"] for e, d in events if e == "speech_text") == ANSWER["speech"]
    assert next(d for e, d in events if e == "target")["target"] == {"element_id": "e2"}
    assert not [e for e, _ in events if e == "audio"]  # the app speaks with the system voice
    assert events[-1][0] == "done"


def test_trim_keeps_clickable_elements_and_ids():
    def el(i, role, name):
        return UiElement(id=f"e{i}", role=role, name=name, rect={"x": 0, "y": 0, "w": 1, "h": 1})

    many = [el(i, "text" if i % 2 else "button", f"n{i}") for i in range(1, 101)]
    kept = elements.trim(many, 30)
    assert len(kept) == 30 and all(e.role == "button" for e in kept)
    assert [e.id for e in kept] == [e.id for e in many if e in kept]  # screen order kept
    assert elements.trim(many[:10], 30) == many[:10]
