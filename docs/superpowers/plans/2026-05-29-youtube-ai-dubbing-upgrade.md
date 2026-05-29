# YouTube AI Dubbing Upgrade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Python backend + rewritten Chrome extension that dubs any YouTube video with natural neural TTS, time-fitted to the original timing, over the original music/SFX bed.

**Architecture:** Chrome extension (UI + audio overlay synced to the `<video>`) talks over HTTP/SSE to a local FastAPI backend. The backend runs a sequential GPU pipeline: yt-dlp → faster-whisper (ASR) → Demucs (vocal/music separation) → Gemini translate → Edge-TTS → time-fit (pitch-preserving stretch) → mix (sidechain ducking) → one full-length audio file, cached per `videoId+lang`.

**Tech Stack:** Python 3.10+, FastAPI, uvicorn, yt-dlp, faster-whisper (CUDA), demucs, edge-tts, google-generativeai, pydub, ffmpeg, pytest. Chrome MV3 extension (vanilla JS).

**Target machine:** Windows 11, NVIDIA RTX 4050 Laptop (6GB VRAM, CUDA). Backend at `http://localhost:8788`. Default target language `vi`. Output format `.m4a` (AAC).

---

## File Structure

```
backend/
  ├─ main.py              # FastAPI app: /health, /dub, /progress (SSE), /audio
  ├─ jobs.py             # in-memory job registry + progress queue + cache lookup
  ├─ config.py           # paths, constants (port, cache dir, time-fit constants)
  ├─ pipeline/
  │   ├─ __init__.py
  │   ├─ orchestrator.py  # runs the full pipeline, emits progress
  │   ├─ download.py      # yt-dlp wrapper
  │   ├─ asr.py           # faster-whisper wrapper
  │   ├─ separate.py      # Demucs wrapper
  │   ├─ segments.py      # PURE: merge/split segments (TDD)
  │   ├─ translate.py     # Gemini + Google fallback (parse logic TDD)
  │   ├─ tts.py           # Edge-TTS wrapper
  │   ├─ timefit.py       # PURE: target-duration + stretch math (TDD) + ffmpeg apply
  │   └─ mix.py           # build voice track + sidechain-duck mix (ffmpeg/pydub)
  ├─ tests/
  │   ├─ test_segments.py
  │   ├─ test_translate.py
  │   └─ test_timefit.py
  ├─ requirements.txt
  ├─ install.ps1          # create venv, install deps, check ffmpeg/CUDA
  ├─ run.ps1              # start uvicorn
  └─ README.md
extension/
  ├─ manifest.json
  ├─ background.js
  ├─ content.js
  ├─ popup.html
  ├─ popup.js
  ├─ styles.css
  └─ icons/               # copied from original repo
```

---

## Phase 0 — Scaffolding & install

### Task 1: Backend dependency manifest + install/run scripts

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/install.ps1`
- Create: `backend/run.ps1`
- Create: `backend/config.py`

- [ ] **Step 1: Write `backend/requirements.txt`**

```
fastapi==0.115.*
uvicorn[standard]==0.32.*
yt-dlp>=2024.10.0
faster-whisper==1.0.*
demucs==4.0.*
edge-tts==6.1.*
google-generativeai==0.8.*
pydub==0.25.*
requests==2.32.*
pytest==8.*
# PyTorch with CUDA is installed separately in install.ps1 (correct CUDA wheel)
```

- [ ] **Step 2: Write `backend/config.py`**

```python
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
CACHE_DIR = BACKEND_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

PORT = 8788
HOST = "127.0.0.1"

# ASR
WHISPER_MODEL = "large-v3"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE = "int8_float16"

# Demucs
DEMUCS_MODEL = "htdemucs"
DEMUCS_SEGMENT = 7  # seconds; keeps VRAM under ~6GB

# Time-fit constants
MAX_SPEEDUP = 1.4
GAP_BORROW_MAX = 1.2     # seconds a segment may borrow from the following silence
MERGE_MIN_DUR = 0.8      # merge segments shorter than this with neighbour
SPLIT_MAX_DUR = 12.0     # split segments longer than this at sentence boundaries
FIT_LOW = 0.9            # acceptable ratio band
FIT_HIGH = 1.15

# TTS voices per language code
TTS_VOICES = {
    "vi": "vi-VN-HoaiMyNeural",
    "en": "en-US-AriaNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "fr": "fr-FR-DeniseNeural",
    "es": "es-ES-ElviraNeural",
}
DEFAULT_VOICE = "vi-VN-HoaiMyNeural"

# Output
OUTPUT_EXT = "m4a"


def cache_key(video_id: str, lang: str) -> str:
    return f"{video_id}_{lang}"


def job_dir(video_id: str, lang: str) -> Path:
    d = CACHE_DIR / cache_key(video_id, lang)
    d.mkdir(parents=True, exist_ok=True)
    return d


def output_path(video_id: str, lang: str) -> Path:
    return job_dir(video_id, lang) / f"output.{OUTPUT_EXT}"
```

- [ ] **Step 3: Write `backend/install.ps1`**

```powershell
# Run from backend/ : powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
Write-Host "Creating virtualenv..."
python -m venv venv
& .\venv\Scripts\python.exe -m pip install --upgrade pip

Write-Host "Installing PyTorch (CUDA 12.1)..."
& .\venv\Scripts\pip.exe install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

Write-Host "Installing Python dependencies..."
& .\venv\Scripts\pip.exe install -r requirements.txt

Write-Host "Checking ffmpeg..."
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
  Write-Host "ffmpeg found."
} else {
  Write-Warning "ffmpeg NOT found on PATH. Install it (winget install Gyan.FFmpeg) and re-open the terminal."
}

Write-Host "Checking CUDA..."
& .\venv\Scripts\python.exe -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
Write-Host "Install complete."
```

- [ ] **Step 4: Write `backend/run.ps1`**

```powershell
# Run from backend/ : powershell -ExecutionPolicy Bypass -File run.ps1
& .\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8788
```

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/config.py backend/install.ps1 backend/run.ps1
git commit -m "chore: backend scaffolding, config, install/run scripts"
```

---

### Task 2: FastAPI skeleton with /health

**Files:**
- Create: `backend/main.py`
- Create: `backend/pipeline/__init__.py` (empty)

- [ ] **Step 1: Write `backend/pipeline/__init__.py`** (empty file)

```python
```

- [ ] **Step 2: Write minimal `backend/main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="YouTube AI Dubbing Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.youtube.com"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    info = {"status": "ok", "cuda": False, "ffmpeg": False, "device": "cpu"}
    try:
        import torch
        info["cuda"] = torch.cuda.is_available()
        if info["cuda"]:
            info["device"] = torch.cuda.get_device_name(0)
    except Exception:
        pass
    import shutil
    info["ffmpeg"] = shutil.which("ffmpeg") is not None
    return info
```

- [ ] **Step 3: Start server and verify /health**

Run (from `backend/`):
```
.\venv\Scripts\python.exe -m uvicorn main:app --port 8788
```
Then in another terminal:
```
curl http://127.0.0.1:8788/health
```
Expected: JSON with `"status":"ok"`, `"cuda":true`, `"ffmpeg":true`, device name `NVIDIA GeForce RTX 4050 Laptop GPU`. Stop the server (Ctrl+C) after verifying.

- [ ] **Step 4: Commit**

```bash
git add backend/main.py backend/pipeline/__init__.py
git commit -m "feat: FastAPI skeleton with /health diagnostics"
```

---

## Phase 1 — Pure-logic modules (TDD)

### Task 3: Segment merge/split (pure logic)

**Files:**
- Create: `backend/pipeline/segments.py`
- Test: `backend/tests/test_segments.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_segments.py
from pipeline.segments import merge_and_split

def seg(start, end, text):
    return {"start": start, "end": end, "text": text}

def test_merges_short_adjacent_segments():
    segs = [seg(0.0, 0.4, "Hi"), seg(0.4, 0.7, "there"), seg(0.7, 3.0, "how are you doing today")]
    out = merge_and_split(segs, merge_min_dur=0.8, split_max_dur=12.0)
    # the two short fragments get merged into one segment
    assert out[0]["text"] == "Hi there"
    assert out[0]["start"] == 0.0
    assert out[0]["end"] == 0.7

def test_keeps_long_enough_segments_untouched():
    segs = [seg(0.0, 2.0, "A full sentence here."), seg(2.0, 4.0, "Another full sentence.")]
    out = merge_and_split(segs, merge_min_dur=0.8, split_max_dur=12.0)
    assert len(out) == 2

def test_splits_overlong_segment_at_sentence_boundary():
    segs = [seg(0.0, 20.0, "First sentence. Second sentence. Third sentence.")]
    out = merge_and_split(segs, merge_min_dur=0.8, split_max_dur=12.0)
    assert len(out) >= 2
    # time is divided proportionally and stays within original window
    assert out[0]["start"] == 0.0
    assert out[-1]["end"] == 20.0
    for s in out:
        assert s["end"] > s["start"]
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `.\venv\Scripts\python.exe -m pytest tests/test_segments.py -v`
Expected: FAIL (ModuleNotFoundError / `merge_and_split` not defined).

- [ ] **Step 3: Write `backend/pipeline/segments.py`**

```python
import re

_SENT_SPLIT = re.compile(r'(?<=[.!?…])\s+')


def _split_sentences(text):
    parts = [p.strip() for p in _SENT_SPLIT.split(text.strip()) if p.strip()]
    return parts or [text.strip()]


def merge_and_split(segments, merge_min_dur=0.8, split_max_dur=12.0):
    """Merge too-short segments into the next one; split too-long segments at
    sentence boundaries, distributing time proportionally to character count."""
    if not segments:
        return []

    # --- merge short fragments forward ---
    merged = []
    buf = None
    for s in segments:
        cur = {"start": s["start"], "end": s["end"], "text": s["text"].strip()}
        if buf is None:
            buf = cur
            continue
        if (buf["end"] - buf["start"]) < merge_min_dur:
            buf = {
                "start": buf["start"],
                "end": cur["end"],
                "text": (buf["text"] + " " + cur["text"]).strip(),
            }
        else:
            merged.append(buf)
            buf = cur
    if buf is not None:
        merged.append(buf)

    # --- split overlong segments ---
    out = []
    for s in merged:
        dur = s["end"] - s["start"]
        if dur <= split_max_dur:
            out.append(s)
            continue
        sentences = _split_sentences(s["text"])
        if len(sentences) == 1:
            out.append(s)
            continue
        total_chars = sum(len(x) for x in sentences) or 1
        t = s["start"]
        for i, sent in enumerate(sentences):
            frac = len(sent) / total_chars
            seg_dur = dur * frac
            start = t
            end = s["end"] if i == len(sentences) - 1 else t + seg_dur
            out.append({"start": round(start, 3), "end": round(end, 3), "text": sent})
            t = end
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_segments.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/segments.py backend/tests/test_segments.py
git commit -m "feat: segment merge/split pure logic (TDD)"
```

---

### Task 4: Time-fit math (pure logic)

**Files:**
- Create: `backend/pipeline/timefit.py`
- Test: `backend/tests/test_timefit.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_timefit.py
from pipeline.timefit import target_duration, compute_fit

def test_target_duration_borrows_capped_gap():
    seg = {"start": 1.0, "end": 3.0}
    # gap to next is 5s but capped at 1.2
    assert target_duration(seg, next_start=8.0, gap_borrow_max=1.2) == 3.2

def test_target_duration_no_next():
    seg = {"start": 1.0, "end": 3.0}
    assert target_duration(seg, next_start=None, gap_borrow_max=1.2) == 2.0

def test_fit_within_band_pads_when_short():
    # actual 1.0s into a 2.0s window -> accept, pad 1.0s, no speedup
    fit = compute_fit(actual=1.0, target=2.0, max_speedup=1.4)
    assert fit["atempo"] == 1.0
    assert abs(fit["pad"] - 1.0) < 1e-6

def test_fit_too_long_speeds_up_capped():
    # actual 3.0s into 2.0s window -> ratio 1.5, capped at 1.4
    fit = compute_fit(actual=3.0, target=2.0, max_speedup=1.4)
    assert fit["atempo"] == 1.4
    assert fit["pad"] == 0.0

def test_fit_slightly_long_within_band_no_change():
    # ratio 1.1 is within band -> accept as-is
    fit = compute_fit(actual=2.2, target=2.0, max_speedup=1.4)
    assert fit["atempo"] == 1.0
    assert fit["pad"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_timefit.py -v`
Expected: FAIL (module/functions not defined).

- [ ] **Step 3: Write the pure-logic part of `backend/pipeline/timefit.py`**

```python
import subprocess
from pathlib import Path


def target_duration(seg, next_start, gap_borrow_max=1.2):
    base = seg["end"] - seg["start"]
    if next_start is None:
        return round(base, 6)
    gap = max(0.0, next_start - seg["end"])
    return round(base + min(gap, gap_borrow_max), 6)


def compute_fit(actual, target, max_speedup=1.4, fit_low=0.9, fit_high=1.15):
    """Return {atempo, pad} describing how to fit `actual` seconds of speech
    into a `target`-second window. atempo>1 speeds up (pitch preserved);
    pad is trailing silence in seconds."""
    if target <= 0:
        target = actual
    ratio = actual / target if target else 1.0

    if fit_low <= ratio <= fit_high:
        return {"atempo": 1.0, "pad": max(0.0, target - actual)}
    if ratio > fit_high:
        return {"atempo": min(ratio, max_speedup), "pad": 0.0}
    # ratio < fit_low -> speech too short for window: pad with silence
    return {"atempo": 1.0, "pad": target - actual}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_timefit.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Append the ffmpeg-apply helper to `backend/pipeline/timefit.py`**

```python
def apply_fit(in_path: Path, out_path: Path, atempo: float, pad: float) -> Path:
    """Apply pitch-preserving tempo change + trailing silence using ffmpeg.
    atempo accepts 0.5..2.0 per filter; we stay within 1.0..1.4 so one stage is fine."""
    filters = []
    if abs(atempo - 1.0) > 1e-3:
        filters.append(f"atempo={atempo:.4f}")
    if pad and pad > 0.01:
        pad_ms = int(pad * 1000)
        filters.append(f"apad=pad_dur={pad:.3f}")
    fchain = ",".join(filters) if filters else "anull"
    cmd = [
        "ffmpeg", "-y", "-i", str(in_path),
        "-filter:a", fchain,
        "-ar", "48000", "-ac", "2",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out_path
```

- [ ] **Step 6: Commit**

```bash
git add backend/pipeline/timefit.py backend/tests/test_timefit.py
git commit -m "feat: time-fit math (TDD) + ffmpeg apply helper"
```

---

### Task 5: Translation parse logic + Gemini/Google (mixed)

**Files:**
- Create: `backend/pipeline/translate.py`
- Test: `backend/tests/test_translate.py`

- [ ] **Step 1: Write the failing test (parse logic only — no network)**

```python
# backend/tests/test_translate.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_translate.py -v`
Expected: FAIL (module/functions not defined).

- [ ] **Step 3: Write `backend/pipeline/translate.py`**

```python
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
        # take content of the first fenced block
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
                pass  # leave gaps; filled by Google fallback below
            if progress:
                progress(min(1.0, (c + CHUNK_SIZE) / max(1, len(indexed))))
            time.sleep(0.3)

    # Fill any missing translations with Google free
    for i, s in enumerate(segments):
        txt = translations.get(i)
        if not txt:
            try:
                txt = _google_free(s["text"], target_lang)
            except Exception:
                txt = s["text"]
        s["translatedText"] = txt
    return segments
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_translate.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/translate.py backend/tests/test_translate.py
git commit -m "feat: translation (Gemini + Google fallback), parse logic TDD"
```

---

## Phase 2 — ML/IO wrapper modules (implement + smoke test)

> These call ML models / external processes and are not deterministically unit-testable. Each task implements the module and includes a manual smoke step. Run smoke steps only when a GPU + network are available.

### Task 6: Audio download (yt-dlp)

**Files:**
- Create: `backend/pipeline/download.py`

- [ ] **Step 1: Write `backend/pipeline/download.py`**

```python
import subprocess
from pathlib import Path


def download_audio(video_id: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = list(out_dir.glob("source.*"))
    if existing:
        return existing[0]
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        "yt-dlp",
        "-f", "bestaudio/best",
        "-x", "--audio-format", "m4a",
        "--no-playlist",
        "-o", str(out_dir / "source.%(ext)s"),
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {proc.stderr[-500:]}")
    produced = list(out_dir.glob("source.*"))
    if not produced:
        raise FileNotFoundError("yt-dlp produced no audio file")
    return produced[0]
```

- [ ] **Step 2: Smoke test**

Run (from `backend/`):
```
.\venv\Scripts\python.exe -c "from pathlib import Path; from pipeline.download import download_audio; print(download_audio('dQw4w9WgXcQ', Path('cache/smoke')))"
```
Expected: prints a path to `cache/smoke/source.m4a` and the file exists.

- [ ] **Step 3: Commit**

```bash
git add backend/pipeline/download.py
git commit -m "feat: yt-dlp audio download"
```

---

### Task 7: ASR (faster-whisper)

**Files:**
- Create: `backend/pipeline/asr.py`

- [ ] **Step 1: Write `backend/pipeline/asr.py`**

```python
from pathlib import Path

import config

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE,
        )
    return _model


def unload():
    """Free VRAM before the Demucs stage."""
    global _model
    _model = None
    try:
        import torch, gc
        gc.collect()
        torch.cuda.empty_cache()
    except Exception:
        pass


def transcribe(audio_path: Path):
    model = _get_model()
    segments, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )
    out = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        out.append({"start": float(seg.start), "end": float(seg.end), "text": text})
    return {"language": info.language, "segments": out}
```

- [ ] **Step 2: Smoke test**

Run (after Task 6 smoke produced `cache/smoke/source.m4a`):
```
.\venv\Scripts\python.exe -c "from pathlib import Path; from pipeline.asr import transcribe; r=transcribe(Path('cache/smoke/source.m4a')); print(r['language'], len(r['segments']), r['segments'][0] if r['segments'] else None)"
```
Expected: prints detected language, a segment count > 0, and a first segment with `start`/`end`/`text`.

- [ ] **Step 3: Commit**

```bash
git add backend/pipeline/asr.py
git commit -m "feat: faster-whisper ASR with VRAM unload"
```

---

### Task 8: Source separation (Demucs)

**Files:**
- Create: `backend/pipeline/separate.py`

- [ ] **Step 1: Write `backend/pipeline/separate.py`**

```python
import subprocess
import sys
from pathlib import Path

import config


def separate_background(audio_path: Path, out_dir: Path) -> Path:
    """Run Demucs two-stem separation, return the no_vocals (music+SFX) wav."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "demucs",
        "--two-stems", "vocals",
        "-n", config.DEMUCS_MODEL,
        "--segment", str(config.DEMUCS_SEGMENT),
        "-o", str(out_dir),
        str(audio_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"demucs failed: {proc.stderr[-800:]}")
    stem = audio_path.stem
    no_vocals = out_dir / config.DEMUCS_MODEL / stem / "no_vocals.wav"
    if not no_vocals.exists():
        raise FileNotFoundError(f"Demucs output not found: {no_vocals}")
    return no_vocals
```

- [ ] **Step 2: Smoke test**

Run:
```
.\venv\Scripts\python.exe -c "from pathlib import Path; from pipeline.separate import separate_background; print(separate_background(Path('cache/smoke/source.m4a'), Path('cache/smoke/sep')))"
```
Expected: prints path to `no_vocals.wav` and the file exists. Watch VRAM stays under 6GB (Task Manager → Performance → GPU). If OOM, lower `DEMUCS_SEGMENT` in config to 5.

- [ ] **Step 3: Commit**

```bash
git add backend/pipeline/separate.py
git commit -m "feat: Demucs two-stem background separation"
```

---

### Task 9: TTS (Edge-TTS) + per-segment synth

**Files:**
- Create: `backend/pipeline/tts.py`

- [ ] **Step 1: Write `backend/pipeline/tts.py`**

```python
import asyncio
from pathlib import Path

import edge_tts

import config


def voice_for_lang(lang: str) -> str:
    return config.TTS_VOICES.get(lang, config.DEFAULT_VOICE)


async def _synth_one(text: str, voice: str, out_path: Path):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))


def synth_segment(text: str, lang: str, out_path: Path) -> Path:
    """Synthesize one segment to mp3 (edge-tts native), return path."""
    voice = voice_for_lang(lang)
    asyncio.run(_synth_one(text, voice, out_path))
    return out_path


def measure_duration(path: Path) -> float:
    """Duration in seconds via pydub."""
    from pydub import AudioSegment
    return len(AudioSegment.from_file(path)) / 1000.0
```

- [ ] **Step 2: Smoke test**

Run:
```
.\venv\Scripts\python.exe -c "from pathlib import Path; from pipeline.tts import synth_segment, measure_duration; p=synth_segment('Xin chào, đây là bản lồng tiếng thử nghiệm.', 'vi', Path('cache/smoke/tts.mp3')); print(p, measure_duration(p))"
```
Expected: creates `tts.mp3`, prints path + a duration > 0. Play the file to confirm a natural Vietnamese voice.

- [ ] **Step 3: Commit**

```bash
git add backend/pipeline/tts.py
git commit -m "feat: Edge-TTS per-segment synthesis + duration measure"
```

---

### Task 10: Mixing (voice track + sidechain ducking)

**Files:**
- Create: `backend/pipeline/mix.py`

- [ ] **Step 1: Write `backend/pipeline/mix.py`**

```python
import subprocess
from pathlib import Path

from pydub import AudioSegment

import config


def build_voice_track(clips, total_duration_s: float, out_path: Path) -> Path:
    """clips: list of (clip_path, start_seconds). Overlays each onto a silent
    track of length total_duration_s, exports a wav."""
    total_ms = int(total_duration_s * 1000) + 500
    track = AudioSegment.silent(duration=total_ms, frame_rate=48000)
    for clip_path, start_s in clips:
        seg = AudioSegment.from_file(clip_path).set_frame_rate(48000).set_channels(2)
        track = track.overlay(seg, position=int(start_s * 1000))
    track.export(out_path, format="wav")
    return out_path


def mix_with_ducking(background_path: Path, voice_path: Path, out_path: Path) -> Path:
    """Sidechain-compress the background under the voice, then mix to AAC m4a.
    Background ducks when voice is present so dialogue stays clear."""
    filter_complex = (
        "[1:a]asplit=2[vmix][vkey];"
        "[0:a][vkey]sidechaincompress=threshold=0.05:ratio=8:attack=15:release=300[bg];"
        "[bg][vmix]amix=inputs=2:duration=longest:normalize=0[out]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(background_path),
        "-i", str(voice_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg mix failed: {proc.stderr[-800:]}")
    return out_path
```

- [ ] **Step 2: Smoke test**

Run (uses Task 8 background + Task 9 tts clip):
```
.\venv\Scripts\python.exe -c "from pathlib import Path; from pipeline.mix import build_voice_track, mix_with_ducking; v=build_voice_track([('cache/smoke/tts.mp3', 2.0)], 10.0, Path('cache/smoke/voice.wav')); m=mix_with_ducking(Path('cache/smoke/sep/htdemucs/source/no_vocals.wav'), v, Path('cache/smoke/out.m4a')); print(m)"
```
Expected: creates `out.m4a`. Play it: music plays, ducks down at 2s where the voice clip speaks.

- [ ] **Step 3: Commit**

```bash
git add backend/pipeline/mix.py
git commit -m "feat: voice-track build + sidechain-duck mix"
```

---

## Phase 3 — Orchestration & API

### Task 11: Job registry + progress queue

**Files:**
- Create: `backend/jobs.py`

- [ ] **Step 1: Write `backend/jobs.py`**

```python
import queue
import threading

import config


class Job:
    def __init__(self, video_id, lang):
        self.video_id = video_id
        self.lang = lang
        self.key = config.cache_key(video_id, lang)
        self.queue = queue.Queue()
        self.status = "pending"   # pending | running | done | error
        self.error = None
        self.thread = None

    def emit(self, stage, percent, message=""):
        self.queue.put({"stage": stage, "percent": percent, "message": message})

    def finish(self, status, error=None):
        self.status = status
        self.error = error
        self.queue.put({"status": status, "error": error})


_jobs = {}
_lock = threading.Lock()


def get_or_create(video_id, lang):
    key = config.cache_key(video_id, lang)
    with _lock:
        job = _jobs.get(key)
        if job and job.status in ("pending", "running"):
            return job, False
        job = Job(video_id, lang)
        _jobs[key] = job
        return job, True


def get(video_id, lang):
    return _jobs.get(config.cache_key(video_id, lang))
```

- [ ] **Step 2: Commit**

```bash
git add backend/jobs.py
git commit -m "feat: in-memory job registry with progress queue"
```

---

### Task 12: Pipeline orchestrator

**Files:**
- Create: `backend/pipeline/orchestrator.py`

- [ ] **Step 1: Write `backend/pipeline/orchestrator.py`**

```python
from pathlib import Path

import config
from pipeline import asr, download, mix, segments, separate, timefit, translate, tts


def run_pipeline(job, api_key=None):
    """Full dubbing pipeline. Emits progress on the job. Writes output.m4a."""
    job.status = "running"
    vid, lang = job.video_id, job.lang
    jd = config.job_dir(vid, lang)
    out = config.output_path(vid, lang)

    if out.exists():
        job.finish("done")
        return

    try:
        job.emit("download", 5, "Đang tải audio...")
        source = download.download_audio(vid, jd)

        job.emit("asr", 20, "Đang nhận dạng giọng nói (Whisper)...")
        tr = asr.transcribe(source)
        segs = tr["segments"]
        if not segs:
            raise RuntimeError("Không nhận dạng được lời thoại trong video.")
        asr.unload()  # free VRAM before Demucs

        job.emit("separate", 40, "Đang tách nhạc nền (Demucs)...")
        background = separate.separate_background(source, jd / "sep")

        job.emit("segments", 45, "Đang chuẩn hoá câu...")
        segs = segments.merge_and_split(
            segs, config.MERGE_MIN_DUR, config.SPLIT_MAX_DUR
        )

        job.emit("translate", 55, "Đang dịch (Gemini)...")
        segs = translate.translate_segments(
            segs, lang, api_key,
            progress=lambda p: job.emit("translate", 55 + int(p * 15),
                                        "Đang dịch (Gemini)..."),
        )

        job.emit("tts", 72, "Đang tạo giọng đọc (Edge-TTS)...")
        clips_dir = jd / "clips"
        clips_dir.mkdir(exist_ok=True)
        fitted_clips = []  # (path, start_s)
        n = len(segs)
        for i, s in enumerate(segs):
            text = (s.get("translatedText") or "").strip()
            if not text:
                continue
            raw = clips_dir / f"{i}.mp3"
            tts.synth_segment(text, lang, raw)
            actual = tts.measure_duration(raw)
            next_start = segs[i + 1]["start"] if i + 1 < n else None
            target = timefit.target_duration(s, next_start, config.GAP_BORROW_MAX)
            fit = timefit.compute_fit(actual, target, config.MAX_SPEEDUP,
                                      config.FIT_LOW, config.FIT_HIGH)
            fitted = clips_dir / f"{i}_fit.wav"
            timefit.apply_fit(raw, fitted, fit["atempo"], fit["pad"])
            fitted_clips.append((fitted, s["start"]))
            if i % 5 == 0:
                job.emit("tts", 72 + int((i / max(1, n)) * 16),
                         f"Đang tạo giọng đọc {i+1}/{n}...")

        job.emit("mix", 90, "Đang trộn nhạc nền + giọng...")
        total = max((s["end"] for s in segs), default=0.0)
        voice_track = mix.build_voice_track(fitted_clips, total, jd / "voice.wav")
        mix.mix_with_ducking(background, voice_track, out)

        job.emit("done", 100, "Hoàn tất!")
        job.finish("done")
    except Exception as e:
        job.finish("error", str(e))
```

- [ ] **Step 2: Verify imports resolve**

Run (from `backend/`): `.\venv\Scripts\python.exe -c "from pipeline import orchestrator; print('ok')"`
Expected: prints `ok` (no ImportError).

- [ ] **Step 3: Commit**

```bash
git add backend/pipeline/orchestrator.py
git commit -m "feat: full pipeline orchestrator with progress"
```

---

### Task 13: API endpoints (/dub, /progress SSE, /audio)

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Replace `backend/main.py` with full API**

```python
import json
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import config
import jobs
from pipeline.orchestrator import run_pipeline

app = FastAPI(title="YouTube AI Dubbing Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.youtube.com"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class DubRequest(BaseModel):
    videoId: str
    lang: str = "vi"
    geminiApiKey: str | None = None


@app.get("/health")
def health():
    info = {"status": "ok", "cuda": False, "ffmpeg": False, "device": "cpu"}
    try:
        import torch
        info["cuda"] = torch.cuda.is_available()
        if info["cuda"]:
            info["device"] = torch.cuda.get_device_name(0)
    except Exception:
        pass
    import shutil
    info["ffmpeg"] = shutil.which("ffmpeg") is not None
    return info


@app.post("/dub")
def dub(req: DubRequest):
    out = config.output_path(req.videoId, req.lang)
    if out.exists():
        return {"status": "done", "cached": True}
    job, created = jobs.get_or_create(req.videoId, req.lang)
    if created:
        job.thread = threading.Thread(
            target=run_pipeline, args=(job, req.geminiApiKey), daemon=True
        )
        job.thread.start()
    return {"status": "running", "cached": False}


@app.get("/progress/{video_id}/{lang}")
def progress(video_id: str, lang: str):
    job = jobs.get(video_id, lang)

    def stream():
        if job is None:
            out = config.output_path(video_id, lang)
            status = "done" if out.exists() else "error"
            yield f"data: {json.dumps({'status': status})}\n\n"
            return
        while True:
            item = job.queue.get()
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            if "status" in item:
                break

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/audio/{video_id}/{lang}")
def audio(video_id: str, lang: str):
    out = config.output_path(video_id, lang)
    if not out.exists():
        return {"error": "not ready"}
    return FileResponse(
        str(out),
        media_type="audio/mp4",
        headers={"Accept-Ranges": "bytes"},
    )
```

- [ ] **Step 2: Manual end-to-end backend test**

Start server: `.\venv\Scripts\python.exe -m uvicorn main:app --port 8788`
In another terminal:
```
curl -X POST http://127.0.0.1:8788/dub -H "Content-Type: application/json" -d "{\"videoId\":\"SHORT_VIDEO_ID\",\"lang\":\"vi\"}"
curl http://127.0.0.1:8788/progress/SHORT_VIDEO_ID/vi
```
Expected: `/dub` returns `running`; `/progress` streams `data:` lines through stages ending with `{"status":"done"}`. Then `cache/SHORT_VIDEO_ID_vi/output.m4a` exists and plays correctly (Vietnamese dub over music). Use a short (<2 min) video with speech.

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: /dub, /progress (SSE), /audio endpoints"
```

---

## Phase 4 — Chrome extension (rewrite)

> No JS test harness exists; extension tasks are implement + manual verification. Copy `icons/` from the original repo into `extension/icons/`.

### Task 14: manifest.json

**Files:**
- Create: `extension/manifest.json`

- [ ] **Step 1: Write `extension/manifest.json`**

```json
{
  "manifest_version": 3,
  "name": "YouTube AI Dubbing (Local)",
  "version": "2.0.0",
  "description": "Lồng tiếng video YouTube bằng pipeline AI local (Whisper + Demucs + Edge-TTS).",
  "permissions": ["storage", "activeTab"],
  "host_permissions": [
    "https://www.youtube.com/*",
    "http://localhost:8788/*",
    "http://127.0.0.1:8788/*"
  ],
  "background": { "service_worker": "background.js" },
  "content_scripts": [
    {
      "matches": ["https://www.youtube.com/*"],
      "js": ["content.js"],
      "css": ["styles.css"]
    }
  ],
  "action": {
    "default_popup": "popup.html",
    "default_icon": { "16": "icons/icon16.png", "48": "icons/icon48.png", "128": "icons/icon128.png" }
  },
  "icons": { "16": "icons/icon16.png", "48": "icons/icon48.png", "128": "icons/icon128.png" }
}
```

- [ ] **Step 2: Copy icons**

```bash
mkdir -p extension/icons && cp YouTube-AI-Translator/YouTube-AI-Translator---Dubbing-main/icons/* extension/icons/
```

- [ ] **Step 3: Commit**

```bash
git add extension/manifest.json extension/icons
git commit -m "feat: extension manifest v2 + icons"
```

---

### Task 15: background.js + popup

**Files:**
- Create: `extension/background.js`
- Create: `extension/popup.html`
- Create: `extension/popup.js`

- [ ] **Step 1: Write `extension/background.js`**

```javascript
// Minimal service worker: defaults + health relay (avoids page CORS edge cases).
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.storage.sync.set({ targetLang: "vi", backendUrl: "http://localhost:8788" });
  }
});
```

- [ ] **Step 2: Write `extension/popup.html`**

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    body { width: 300px; font-family: system-ui, sans-serif; padding: 14px; }
    label { display: block; margin: 10px 0 4px; font-size: 13px; }
    input, select { width: 100%; box-sizing: border-box; padding: 6px; }
    button { margin-top: 12px; width: 100%; padding: 8px; cursor: pointer; }
    #status { margin-top: 10px; font-size: 12px; min-height: 16px; }
    .ok { color: #0a7d28; } .err { color: #c0392b; }
  </style>
</head>
<body>
  <h3>YouTube AI Dubbing</h3>
  <label>Ngôn ngữ đích</label>
  <select id="targetLang">
    <option value="vi">Tiếng Việt</option>
    <option value="en">English</option>
    <option value="ja">日本語</option>
    <option value="ko">한국어</option>
    <option value="zh">中文</option>
    <option value="fr">Français</option>
    <option value="es">Español</option>
  </select>
  <label>Gemini API key (tuỳ chọn)</label>
  <input id="apiKey" type="password" placeholder="Để trống = dùng Google free" />
  <label>Địa chỉ backend</label>
  <input id="backendUrl" type="text" placeholder="http://localhost:8788" />
  <button id="save">Lưu</button>
  <button id="check">Kiểm tra backend</button>
  <div id="status"></div>
  <script src="popup.js"></script>
</body>
</html>
```

- [ ] **Step 3: Write `extension/popup.js`**

```javascript
const $ = (id) => document.getElementById(id);

chrome.storage.sync.get(["targetLang", "geminiApiKey", "backendUrl"], (d) => {
  if (d.targetLang) $("targetLang").value = d.targetLang;
  if (d.geminiApiKey) $("apiKey").value = d.geminiApiKey;
  $("backendUrl").value = d.backendUrl || "http://localhost:8788";
});

$("save").addEventListener("click", () => {
  chrome.storage.sync.set({
    targetLang: $("targetLang").value,
    geminiApiKey: $("apiKey").value.trim(),
    backendUrl: ($("backendUrl").value.trim() || "http://localhost:8788").replace(/\/$/, ""),
  }, () => setStatus("Đã lưu.", "ok"));
});

$("check").addEventListener("click", async () => {
  const url = ($("backendUrl").value.trim() || "http://localhost:8788").replace(/\/$/, "");
  setStatus("Đang kiểm tra...", "");
  try {
    const r = await fetch(`${url}/health`);
    const j = await r.json();
    setStatus(`OK • GPU: ${j.cuda ? j.device : "CPU"} • ffmpeg: ${j.ffmpeg ? "có" : "thiếu"}`, j.cuda && j.ffmpeg ? "ok" : "err");
  } catch {
    setStatus("Không kết nối được backend. Hãy chạy run.ps1.", "err");
  }
});

function setStatus(msg, cls) {
  const el = $("status");
  el.textContent = msg;
  el.className = cls;
}
```

- [ ] **Step 4: Manual verify**

Load `extension/` as unpacked in `chrome://extensions` (Developer mode). Open popup, set language, click "Kiểm tra backend" with the server running.
Expected: shows `OK • GPU: NVIDIA GeForce RTX 4050 ... • ffmpeg: có`.

- [ ] **Step 5: Commit**

```bash
git add extension/background.js extension/popup.html extension/popup.js
git commit -m "feat: extension background + popup (settings + health check)"
```

---

### Task 16: content.js — overlay UI + dub trigger + audio sync

**Files:**
- Create: `extension/content.js`
- Create: `extension/styles.css`

- [ ] **Step 1: Write `extension/styles.css`**

```css
#yt-dub-overlay {
  position: fixed; top: 80px; right: 20px; z-index: 99999;
  width: 280px; background: rgba(20,20,20,0.95); color: #fff;
  border-radius: 10px; padding: 14px; font-family: system-ui, sans-serif;
  box-shadow: 0 6px 24px rgba(0,0,0,0.4);
}
#yt-dub-overlay h4 { margin: 0 0 8px; font-size: 14px; }
#yt-dub-overlay .row { display: flex; align-items: center; justify-content: space-between; margin: 8px 0; font-size: 13px; }
#yt-dub-overlay button { width: 100%; padding: 8px; margin-top: 6px; border: 0; border-radius: 6px; background: #ff0000; color: #fff; cursor: pointer; font-size: 13px; }
#yt-dub-overlay button:disabled { background: #555; cursor: default; }
#yt-dub-overlay .bar { height: 6px; background: #333; border-radius: 4px; overflow: hidden; margin-top: 8px; }
#yt-dub-overlay .bar > div { height: 100%; width: 0%; background: #ff0000; transition: width 0.3s; }
#yt-dub-overlay .status { font-size: 12px; margin-top: 6px; min-height: 16px; }
#yt-dub-overlay input[type=range] { width: 120px; accent-color: #ff0000; }
#yt-dub-overlay .close { position: absolute; top: 8px; right: 10px; cursor: pointer; background: none; width: auto; padding: 0; font-size: 16px; }
```

- [ ] **Step 2: Write `extension/content.js`**

```javascript
// ===== YouTube AI Dubbing — content script =====
let cfg = { targetLang: "vi", geminiApiKey: "", backendUrl: "http://localhost:8788" };
let dubAudio = null;            // <audio> element playing the dubbed track
let syncRaf = null;             // drift-correction interval id
let currentVideoId = null;
let isDubActive = false;

function getVideoId() {
  return new URLSearchParams(location.search).get("v");
}

function getVideo() {
  return document.querySelector("video");
}

function loadConfig() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["targetLang", "geminiApiKey", "backendUrl"], (d) => {
      cfg.targetLang = d.targetLang || "vi";
      cfg.geminiApiKey = d.geminiApiKey || "";
      cfg.backendUrl = (d.backendUrl || "http://localhost:8788").replace(/\/$/, "");
      resolve(cfg);
    });
  });
}

// ---------- UI ----------
function createOverlay() {
  let el = document.getElementById("yt-dub-overlay");
  if (el) return el;
  el = document.createElement("div");
  el.id = "yt-dub-overlay";
  el.innerHTML = `
    <button class="close" title="Đóng">×</button>
    <h4>🎙️ AI Lồng tiếng</h4>
    <button id="ytd-start">Lồng tiếng video này</button>
    <div class="bar"><div id="ytd-fill"></div></div>
    <div class="status" id="ytd-status">Sẵn sàng</div>
    <div class="row"><span>Âm lượng lồng tiếng</span><input type="range" id="ytd-vol" min="0" max="1" step="0.05" value="1"></div>
    <div class="row"><span>Giữ tiếng gốc</span><input type="range" id="ytd-orig" min="0" max="1" step="0.05" value="0"></div>
  `;
  document.body.appendChild(el);
  el.querySelector(".close").addEventListener("click", () => (el.style.display = "none"));
  el.querySelector("#ytd-start").addEventListener("click", startDubbing);
  el.querySelector("#ytd-vol").addEventListener("input", (e) => {
    if (dubAudio) dubAudio.volume = parseFloat(e.target.value);
  });
  el.querySelector("#ytd-orig").addEventListener("input", (e) => {
    const v = getVideo();
    if (v) { v.volume = parseFloat(e.target.value); v.muted = parseFloat(e.target.value) === 0; }
  });
  return el;
}

function setStatus(msg, pct) {
  const s = document.getElementById("ytd-status");
  const f = document.getElementById("ytd-fill");
  if (s) s.textContent = msg;
  if (f && typeof pct === "number") f.style.width = `${pct}%`;
}

// ---------- Dub trigger ----------
async function startDubbing() {
  const videoId = getVideoId();
  if (!videoId) { setStatus("Không tìm thấy video.", 0); return; }
  const startBtn = document.getElementById("ytd-start");
  startBtn.disabled = true;
  currentVideoId = videoId;

  try {
    const r = await fetch(`${cfg.backendUrl}/dub`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videoId, lang: cfg.targetLang, geminiApiKey: cfg.geminiApiKey || null }),
    });
    const j = await r.json();
    if (j.status === "done") {
      setStatus("Đã có bản lồng tiếng (cache).", 100);
      attachDubAudio(videoId);
    } else {
      listenProgress(videoId);
    }
  } catch {
    setStatus("Không kết nối được backend. Hãy chạy run.ps1.", 0);
    startBtn.disabled = false;
  }
}

function listenProgress(videoId) {
  const es = new EventSource(`${cfg.backendUrl}/progress/${videoId}/${cfg.targetLang}`);
  es.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    if (d.status) {
      es.close();
      if (d.status === "done") {
        setStatus("Hoàn tất! Đang phát lồng tiếng...", 100);
        attachDubAudio(videoId);
      } else {
        setStatus("Lỗi: " + (d.error || "không rõ"), 0);
        document.getElementById("ytd-start").disabled = false;
      }
      return;
    }
    setStatus(d.message || d.stage, d.percent);
  };
  es.onerror = () => {
    es.close();
    setStatus("Mất kết nối tiến trình.", 0);
    document.getElementById("ytd-start").disabled = false;
  };
}

// ---------- Audio overlay + sync ----------
function attachDubAudio(videoId) {
  const video = getVideo();
  if (!video) return;
  detachDubAudio();

  dubAudio = new Audio(`${cfg.backendUrl}/audio/${videoId}/${cfg.targetLang}`);
  dubAudio.preload = "auto";
  const volEl = document.getElementById("ytd-vol");
  dubAudio.volume = volEl ? parseFloat(volEl.value) : 1.0;

  video.muted = true;          // silence original (vocals removed track plays instead)
  isDubActive = true;

  const syncNow = () => { try { dubAudio.currentTime = video.currentTime; } catch {} };
  dubAudio.addEventListener("loadedmetadata", () => {
    syncNow();
    if (!video.paused) dubAudio.play().catch(() => {});
  });

  // Event-driven sync
  video.addEventListener("play", onPlay);
  video.addEventListener("pause", onPause);
  video.addEventListener("seeking", onSeek);
  video.addEventListener("seeked", onSeek);
  video.addEventListener("ratechange", onRate);

  // Drift correction every 500ms
  syncRaf = setInterval(() => {
    if (!isDubActive || !dubAudio || video.paused) return;
    if (Math.abs(dubAudio.currentTime - video.currentTime) > 0.25) syncNow();
  }, 500);
}

function onPlay() { if (dubAudio) { dubAudio.currentTime = getVideo().currentTime; dubAudio.play().catch(() => {}); } }
function onPause() { if (dubAudio) dubAudio.pause(); }
function onSeek() { if (dubAudio) { try { dubAudio.currentTime = getVideo().currentTime; } catch {} } }
function onRate() { if (dubAudio) dubAudio.playbackRate = getVideo().playbackRate; }

function detachDubAudio() {
  const video = getVideo();
  if (video) {
    video.removeEventListener("play", onPlay);
    video.removeEventListener("pause", onPause);
    video.removeEventListener("seeking", onSeek);
    video.removeEventListener("seeked", onSeek);
    video.removeEventListener("ratechange", onRate);
  }
  if (syncRaf) { clearInterval(syncRaf); syncRaf = null; }
  if (dubAudio) { dubAudio.pause(); dubAudio.src = ""; dubAudio = null; }
  isDubActive = false;
}

// ---------- SPA navigation ----------
function onNavigate() {
  const vid = getVideoId();
  if (vid !== currentVideoId) {
    detachDubAudio();
    const btn = document.getElementById("ytd-start");
    if (btn) btn.disabled = false;
    setStatus("Sẵn sàng", 0);
    currentVideoId = vid;
  }
}
window.addEventListener("yt-navigate-finish", onNavigate);

// ---------- Init ----------
(async function init() {
  await loadConfig();
  if (location.pathname === "/watch") createOverlay();
  window.addEventListener("yt-navigate-finish", async () => {
    await loadConfig();
    if (location.pathname === "/watch") createOverlay();
  });
})();
```

- [ ] **Step 3: Manual end-to-end verify**

Start backend (`run.ps1`). Reload the unpacked extension. Open a short YouTube video with speech. Click "Lồng tiếng video này".
Expected:
1. Progress bar advances through stages (download → ASR → separate → translate → TTS → mix).
2. On completion, original audio mutes and the dubbed Vietnamese track plays in sync with the picture, with music/SFX audible underneath the voice.
3. Pause/play and seeking keep the dub in sync (within ~0.25s).
4. Re-clicking on the same video plays instantly from cache.

- [ ] **Step 4: Commit**

```bash
git add extension/content.js extension/styles.css
git commit -m "feat: content script — overlay UI, dub trigger, audio overlay sync"
```

---

### Task 17: Backend README

**Files:**
- Create: `backend/README.md`

- [ ] **Step 1: Write `backend/README.md`**

```markdown
# YouTube AI Dubbing — Local Backend

## Yêu cầu
- Windows 11, Python 3.10+, NVIDIA GPU (CUDA) khuyến nghị.
- ffmpeg trên PATH: `winget install Gyan.FFmpeg` (mở lại terminal sau khi cài).

## Cài đặt
```powershell
cd backend
powershell -ExecutionPolicy Bypass -File install.ps1
```
Script tạo venv, cài PyTorch CUDA 12.1, cài dependencies, kiểm tra ffmpeg + CUDA.

## Chạy
```powershell
powershell -ExecutionPolicy Bypass -File run.ps1
```
Backend lắng nghe tại http://localhost:8788. Kiểm tra: mở http://localhost:8788/health

## Extension
Vào `chrome://extensions`, bật Developer mode, "Load unpacked" → chọn thư mục `extension/`.
Mở popup, (tuỳ chọn) nhập Gemini API key, bấm "Kiểm tra backend".

## Ghi chú
- Lần chạy đầu tải model Whisper large-v3 (~3GB) và Demucs (~1GB).
- Nếu GPU hết VRAM ở bước Demucs: giảm `DEMUCS_SEGMENT` trong `config.py` xuống 5.
- Kết quả được cache tại `backend/cache/{videoId}_{lang}/output.m4a`.
```

- [ ] **Step 2: Commit**

```bash
git add backend/README.md
git commit -m "docs: backend setup README"
```

---

## Phase 5 — Final verification

### Task 18: Full test-suite + end-to-end checklist

- [ ] **Step 1: Run all unit tests**

Run (from `backend/`): `.\venv\Scripts\python.exe -m pytest -v`
Expected: all tests in `test_segments.py`, `test_timefit.py`, `test_translate.py` PASS.

- [ ] **Step 2: End-to-end acceptance (manual)**

Verify against the spec's success criteria:
- [ ] A video **without** captions still gets dubbed (Whisper ASR works).
- [ ] Voice sounds natural (Edge-TTS neural), not sped-up/robotic.
- [ ] Dialogue stays time-aligned across play/pause/seek/speed-change (drift < 0.25s).
- [ ] Background music/SFX audible under the dub (Demucs + ducking).
- [ ] Re-watching a processed video plays instantly (cache hit).

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: final verification pass"
```

---

## Self-Review notes (resolved)
- **Spec coverage:** download→ASR→separate→segments→translate→TTS→timefit→mix all have tasks; API (Task 13), extension sync (Task 16), cache (config + orchestrator early-return), health (Task 2), install script (Task 1) covered.
- **Type consistency:** segment dict shape `{start, end, text}` (+`translatedText` after translate) is consistent across `segments.py`, `timefit.py`, `translate.py`, `orchestrator.py`. `compute_fit` returns `{atempo, pad}` consumed by `apply_fit` and orchestrator. Cache/path helpers (`cache_key`, `job_dir`, `output_path`) defined once in `config.py` and reused.
- **Out of scope (per spec §11):** diarization/multi-voice, voice cloning, video-file export — intentionally excluded.
```
