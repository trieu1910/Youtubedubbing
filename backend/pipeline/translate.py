import json
import re
import time

import requests

LANG_NAMES = {
    "vi": "Vietnamese", "en": "English", "ja": "Japanese", "ko": "Korean",
    "zh": "Chinese", "fr": "French", "es": "Spanish", "de": "German",
}

CHUNK_SIZE = 40


def build_prompt(items, lang_name):
    return (
        f"Translate the 'text' of each item in this JSON array into natural, "
        f"fluent {lang_name} suitable for voice-over dubbing. Keep the same "
        f"speaking register and keep pronouns/terms consistent across items. "
        f"Return ONLY a JSON array with the same 'id' values and translated "
        f"'text'. No markdown, no commentary.\n\n"
        f"{json.dumps(items, ensure_ascii=False)}"
    )


def parse_gemini_json(raw, count):
    """Extract {id: text} from a model response that may contain markdown
    fences or leading prose. Returns {} on failure."""
    if not raw:
        return {}
    text = raw.strip()
    if "```" in text:
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
    first = text.find("[")
    last = text.rfind("]")
    if first == -1 or last == -1 or last <= first:
        return {}
    try:
        arr = json.loads(text[first:last + 1])
    except Exception:
        return {}
    if not isinstance(arr, list):
        return {}
    out = {}
    for item in arr:
        if isinstance(item, dict) and "id" in item and "text" in item:
            try:
                out[int(item["id"])] = str(item["text"])
            except Exception:
                continue
    return out


def _google_free(text, target_lang):
    params = {"client": "gtx", "sl": "auto", "tl": target_lang, "dt": "t", "q": text}
    r = requests.get("https://translate.googleapis.com/translate_a/single",
                     params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    return "".join(part[0] for part in data[0] if part and part[0])


def _gemini_chunk(items, lang_name, api_key, model="gemini-2.0-flash"):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={api_key}")
    body = {
        "contents": [{"parts": [{"text": build_prompt(items, lang_name)}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192},
    }
    r = requests.post(url, json=body, timeout=120)
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def translate_segments(segments, target_lang, api_key=None, progress=None):
    """Add 'translatedText' to each segment. Uses Gemini when api_key given,
    falling back to Google free per-segment on any failure."""
    lang_name = LANG_NAMES.get(target_lang, target_lang)
    indexed = [{"id": i, "text": s["text"]} for i, s in enumerate(segments)]

    translations = {}
    if api_key:
        for c in range(0, len(indexed), CHUNK_SIZE):
            chunk = indexed[c:c + CHUNK_SIZE]
            try:
                raw = _gemini_chunk(chunk, lang_name, api_key)
                translations.update(parse_gemini_json(raw, len(chunk)))
            except Exception:
                pass
            if progress:
                progress(min(1.0, (c + CHUNK_SIZE) / max(1, len(indexed))))
            time.sleep(0.3)

    for i, s in enumerate(segments):
        txt = translations.get(i)
        if not txt:
            try:
                txt = _google_free(s["text"], target_lang)
            except Exception:
                txt = s["text"]
        s["translatedText"] = txt
    return segments
