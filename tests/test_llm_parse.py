from app.services.llm import _extract_json_text, _strip_think


def test_strip_think_blocks():
    raw = '<think>internal reasoning</think>{"answer":"ok"}'
    assert 'internal' not in _strip_think(raw)
    assert _extract_json_text(raw) == '{"answer":"ok"}'


def test_extract_json_from_fences():
    raw = '```json\n{"title":"x"}\n```'
    assert _extract_json_text(raw) == '{"title":"x"}'