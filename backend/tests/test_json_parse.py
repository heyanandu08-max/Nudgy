import pytest

from app.services.json_parse import SentenceChunker, StringFieldExtractor, extract_json_object


@pytest.mark.parametrize(
    "text",
    [
        '{"speech": "hi", "target": null}',
        '```json\n{"speech": "hi", "target": null}\n```',
        'Sure! {"speech": "hi", "target": null} hope that helps',
        '{"speech": "a {brace} and \\"quote\\"", "target": null}',
    ],
)
def test_extract_json_object_tolerates_wrapping(text):
    obj = extract_json_object(text)
    assert obj is not None and "speech" in obj


def test_extract_json_object_rejects_garbage():
    assert extract_json_object("no json here") is None
    assert extract_json_object('{"speech": "unterminated') is None
    assert extract_json_object("[1, 2, 3]") is None


def test_extract_skips_broken_object_and_finds_next():
    assert extract_json_object('{bad} {"speech": "ok"}') == {"speech": "ok"}


def _feed_all(extractor, text, size):
    out = ""
    for i in range(0, len(text), size):
        out += extractor.feed(text[i : i + size])
    return out


@pytest.mark.parametrize("size", [1, 2, 3, 5, 64])
def test_speech_extractor_streams_across_any_chunking(size):
    text = '{"speech": "Click \\"Bold\\" \\u2014 top left.\\nDone", "target": {"element_id": "e1"}}'
    ex = StringFieldExtractor("speech")
    out = _feed_all(ex, text, size)
    assert out == 'Click "Bold" — top left.\nDone'
    assert ex.done and ex.value == out


def test_speech_extractor_ignores_other_fields_and_key_in_values():
    text = '{"note": "the \\"speech\\" key", "speech":"real"}'
    assert _feed_all(StringFieldExtractor(), text, 4) == "real"


def test_speech_extractor_without_field_yields_nothing():
    ex = StringFieldExtractor()
    assert _feed_all(ex, "plain text answer", 3) == ""
    assert not ex.done


def test_sentence_chunker_merges_short_and_flushes():
    c = SentenceChunker(min_chars=10)
    out = c.feed("Hi. Open the Home tab now. Then pick")
    assert out == ["Hi. Open the Home tab now."]
    assert c.feed(" a font.") == []
    assert c.flush() == ["Then pick a font."]
    assert c.flush() == []
