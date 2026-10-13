import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.fake import EXCEL_LESSON, FakeLLM, FakeSTT, FakeTTS
from app.providers.registry import Providers, get_providers
from app.schemas.ask import UiElement
from app.services.lessons import diff_elements
from tests.sse_utils import parse_sse

JPEG = b"\xff\xd8\xff\xe0jpeg"
EXCEL_ELEMENTS = [
    {"id": "e1", "role": "tab", "name": "Home", "rect": {"x": 10, "y": 5, "w": 50, "h": 20}},
    {
        "id": "e2",
        "role": "splitbutton",
        "name": "Accounting Number Format",
        "rect": {"x": 300, "y": 40, "w": 30, "h": 22},
    },
    {"id": "e3", "role": "cell", "name": "B7", "rect": {"x": 120, "y": 300, "w": 64, "h": 20}},
]


@pytest.fixture
def providers():
    return Providers(llm=FakeLLM(), stt=FakeSTT(), tts=FakeTTS())


@pytest.fixture
def client(providers):
    app = create_app()
    app.dependency_overrides[get_providers] = lambda: providers
    return TestClient(app)


def post(client, path, context, screenshot=JPEG):
    files = {"screenshot": ("s.jpg", screenshot, "image/jpeg")} if screenshot else None
    return client.post(path, data={"context": json.dumps(context)}, files=files)


def test_plan_returns_valid_lesson_with_medium_effort(client, providers):
    r = post(
        client,
        "/v1/lessons/plan",
        {"goal": "SUM and currency in Excel", "elements": EXCEL_ELEMENTS, "app": {"name": "Excel"}},
    )
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["skill"] == "excel.sum_and_currency"
    assert len(plan["steps"]) == 5
    assert all(s["success_check"] for s in plan["steps"])
    call = providers.llm.calls[0]
    assert call["effort"] == "medium"
    assert "SUM and currency in Excel" in call["system"]
    assert "e2 | splitbutton | Accounting Number Format" in call["messages"][0].parts[-1]


def test_plan_repairs_bad_json_then_gives_up(client, providers):
    providers.llm = FakeLLM(scripted=["not json", json.dumps(EXCEL_LESSON)])
    assert post(client, "/v1/lessons/plan", {"goal": "x"}).status_code == 200
    providers.llm = FakeLLM(scripted=["nope", '{"title": "missing steps"}'])
    r = post(client, "/v1/lessons/plan", {"goal": "x"})
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "llm_bad_output"


def test_plan_requires_goal(client):
    assert post(client, "/v1/lessons/plan", {"goal": ""}).status_code == 422


def verify_ctx(before, after, attempt=1):
    return {
        "step": EXCEL_LESSON["steps"][0],
        "before": {"elements": before},
        "after": {"elements": after},
        "screenshot": {"width": 1280, "height": 720},
        "attempt": attempt,
    }


def test_verify_fails_without_change_then_passes(client, providers):
    r = post(client, "/v1/lessons/verify", verify_ctx(EXCEL_ELEMENTS, EXCEL_ELEMENTS))
    assert r.json() == {"passed": False, "hint": "Not quite yet. Look for it near the top."}
    changed = EXCEL_ELEMENTS + [
        {
            "id": "e4",
            "role": "edit",
            "name": "Formula Bar",
            "rect": {"x": 0, "y": 0, "w": 5, "h": 5},
        }
    ]
    r = post(client, "/v1/lessons/verify", verify_ctx(EXCEL_ELEMENTS, changed))
    assert r.json()["passed"] is True
    system = providers.llm.calls[-1]["system"]
    assert "Cell B7 is selected" in system and "attempt 1." in system
    assert "+ edit 'Formula Bar'" in providers.llm.calls[-1]["messages"][0].parts[-1]


def test_verify_unparseable_is_a_gentle_fail(client, providers):
    providers.llm = FakeLLM(scripted=["??", "??"])
    r = post(client, "/v1/lessons/verify", verify_ctx([], []))
    assert r.status_code == 200 and r.json()["passed"] is False


def test_locate_exact_match_skips_llm(client, providers):
    ctx = {
        "target": {"role": "cell", "name": "b7"},
        "elements": EXCEL_ELEMENTS,
        "screenshot": {"width": 1280, "height": 720},
    }
    r = post(client, "/v1/lessons/locate", ctx)
    assert r.json() == {"target": {"element_id": "e3"}}
    assert providers.llm.calls == []


def test_locate_falls_back_to_llm(client, providers):
    ctx = {
        "target": {"role": "button", "name": "Accounting format"},
        "elements": EXCEL_ELEMENTS,
        "screenshot": {"width": 1280, "height": 720},
    }
    r = post(client, "/v1/lessons/locate", ctx)
    assert r.json() == {"target": {"element_id": "e2"}}
    assert len(providers.llm.calls) == 1


def test_speak_returns_ordered_clips(client):
    r = client.post(
        "/v1/speak", json={"text": "Great job on that one! Now let's move to the next step."}
    )
    clips = r.json()["clips"]
    assert [c["seq"] for c in clips] == list(range(len(clips)))
    assert clips[0]["mime"] == "audio/mpeg"


def test_diff_elements():
    a = [UiElement(id="e1", role="button", name="Bold", rect={"x": 0, "y": 0, "w": 1, "h": 1})]
    b = [UiElement(id="e1", role="button", name="Italic", rect={"x": 0, "y": 0, "w": 1, "h": 1})]
    assert diff_elements(a, b) == "+ button 'Italic'\n- button 'Bold'"
    assert diff_elements(a, a) == "(no element changes detected)"


@pytest.mark.parametrize(
    ("said", "intent", "goal"),
    [
        ("teach me to add up a column in Excel", "start_lesson", "to add up a column in Excel"),
        ("done", "done", None),
        ("skip this one", "skip", None),
        ("show me how", "show_me", None),
    ],
)
def test_ask_reports_intents(client, providers, said, intent, goal):
    ctx = {
        "text": said,
        "lesson": {"title": "t", "step_index": 0, "step_count": 5, "instruction": "Click B7."},
    }
    r = client.post("/v1/ask", data={"context": json.dumps(ctx)})
    done = parse_sse(r.text)[-1]
    assert done[0] == "done"
    assert done[1]["intent"] == intent and done[1]["lesson_goal"] == goal
    assert 'A lesson is running: "t", step 1 of 5' in providers.llm.calls[0]["system"]


def test_talk_prompt_has_no_lesson_block_outside_lessons(client, providers):
    client.post("/v1/ask", data={"context": json.dumps({"text": "hi"})})
    assert "A lesson is running" not in providers.llm.calls[0]["system"]
    assert "{{" not in providers.llm.calls[0]["system"]
