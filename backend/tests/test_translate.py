from pipeline.translate import parse_gemini_json, build_prompt

def test_parse_plain_json_array():
    raw = '[{"id":0,"text":"Xin chào"},{"id":1,"text":"Tạm biệt"}]'
    out = parse_gemini_json(raw, count=2)
    assert out == {0: "Xin chào", 1: "Tạm biệt"}

def test_parse_json_wrapped_in_markdown_fence():
    raw = '```json\n[{"id":0,"text":"A"},{"id":1,"text":"B"}]\n```'
    out = parse_gemini_json(raw, count=2)
    assert out[0] == "A" and out[1] == "B"

def test_parse_with_leading_explanation_text():
    raw = 'Here is the translation:\n[{"id":0,"text":"Một"}]'
    out = parse_gemini_json(raw, count=1)
    assert out[0] == "Một"

def test_parse_invalid_returns_empty():
    out = parse_gemini_json("not json at all", count=2)
    assert out == {}

def test_build_prompt_contains_language_and_ids():
    items = [{"id": 0, "text": "Hello"}, {"id": 1, "text": "World"}]
    p = build_prompt(items, "Vietnamese")
    assert "Vietnamese" in p
    assert '"id"' in p and "Hello" in p
