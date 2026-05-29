"""Fetch existing YouTube captions (manual or auto-generated) so we can skip ASR.

Strategy:
  1. `yt-dlp -J` to read the video's metadata (original language + caption track URLs).
  2. Pick the best track: manual subtitles first; auto-captions only when we know
     the original language (so we don't accidentally grab an auto-translated track).
  3. Download the json3 (preferred) or vtt caption and parse it into
     {start, end, text} segments — the same shape ASR produces.

Returns None when no usable caption exists, so the caller falls back to Whisper.
"""

import json
import re
import subprocess
import sys

import requests


def _yt_dlp_info(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [sys.executable, "-m", "yt_dlp", "-J", "--skip-download", "--no-playlist", url]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp info failed: {(proc.stderr or '')[-400:]}")
    return json.loads(proc.stdout)


def _find_lang(track_dict, lang):
    """Find a caption track for `lang` in a {lang_code: [formats]} dict."""
    if not lang or not track_dict:
        return None
    base = lang.split("-")[0]
    for key in (lang, base, f"{base}-orig"):
        if key in track_dict:
            return track_dict[key]
    for key, val in track_dict.items():
        if key.split("-")[0] == base:
            return val
    return None


def pick_track(info):
    """Choose a caption track from yt-dlp info. Returns the list of formats or None."""
    orig = info.get("language") or ""
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}

    # 1) Manual subtitles — clean. Prefer original language, else any.
    track = _find_lang(subs, orig)
    if track is None and subs:
        track = next(iter(subs.values()))
    # 2) Auto-captions — only when we know the original language, to avoid
    #    picking an auto-translated track (which would cause double translation).
    if track is None and orig:
        track = _find_lang(auto, orig)
    return track


def pick_format_url(track):
    """Pick a caption format URL, preferring json3 (cleanest for auto-captions)."""
    by_ext = {}
    for fmt in track:
        ext = fmt.get("ext")
        url = fmt.get("url")
        if ext and url and ext not in by_ext:
            by_ext[ext] = url
    for ext in ("json3", "srv3", "srv1", "vtt", "ttml"):
        if ext in by_ext:
            return ext, by_ext[ext]
    if track:
        return track[0].get("ext"), track[0].get("url")
    return None, None


def _normalize(s):
    return " ".join((s or "").split()).strip()


def parse_json3(data):
    """Parse YouTube json3 captions into sentence-level segments, handling both
    word-append (aAppend) and cumulative-refresh (rolling auto-caption) formats."""
    result = []
    cur_text = ""
    cur_start = None

    def flush(end_ms):
        nonlocal cur_text, cur_start
        text = _normalize(cur_text)
        if text and cur_start is not None:
            result.append({"text": text, "start": cur_start / 1000.0, "end": end_ms / 1000.0})
        cur_text = ""
        cur_start = None

    for ev in data.get("events", []) or []:
        segs = ev.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs)
        tstart = ev.get("tStartMs") or 0
        if text == "\n" or text.strip() == "":
            flush(tstart)
            continue
        if ev.get("aAppend"):
            if cur_start is None:
                cur_start = tstart
            cur_text += text
        else:
            norm_existing = _normalize(cur_text)
            norm_new = _normalize(text)
            if norm_existing and norm_new.startswith(norm_existing):
                cur_text = text  # cumulative update in place
            else:
                flush(tstart)
                cur_start = tstart
                cur_text = text

    if _normalize(cur_text) and cur_start is not None:
        flush(cur_start + 2000)
    return result


def _vtt_time(t):
    parts = t.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(parts[0])


_VTT_TIME = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}\.\d{3}|\d{1,2}:\d{2}\.\d{3})\s*-->\s*"
    r"(\d{1,2}:\d{2}:\d{2}\.\d{3}|\d{1,2}:\d{2}\.\d{3})"
)


def parse_vtt(text):
    """Parse WEBVTT, dropping inline tags and consecutive duplicate lines."""
    text = (text or "").replace("\r", "")
    segments = []
    last = None
    for block in re.split(r"\n\s*\n", text):
        m = _VTT_TIME.search(block)
        if not m:
            continue
        start = _vtt_time(m.group(1))
        end = _vtt_time(m.group(2))
        lines = []
        for ln in block.split("\n"):
            if "-->" in ln or not ln.strip() or ln.strip().isdigit():
                continue
            if ln.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
                continue
            cleaned = re.sub(r"<[^>]+>", "", ln).strip()
            if cleaned:
                lines.append(cleaned)
        txt = _normalize(" ".join(lines))
        if not txt or txt == last:
            continue
        last = txt
        segments.append({"start": start, "end": end, "text": txt})
    return segments


def get_captions(video_id):
    """Return [{start,end,text}] from existing YouTube captions, or None."""
    try:
        info = _yt_dlp_info(video_id)
    except Exception:
        return None

    track = pick_track(info)
    if not track:
        return None

    ext, url = pick_format_url(track)
    if not url:
        return None

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except Exception:
        return None

    try:
        if ext == "json3":
            segs = parse_json3(resp.json())
        elif ext == "vtt":
            segs = parse_vtt(resp.text)
        else:
            # srv1/srv3/ttml are XML variants; json3 is requested first, so this
            # is a rare fallback — try json3 parse then vtt parse defensively.
            try:
                segs = parse_json3(resp.json())
            except Exception:
                segs = parse_vtt(resp.text)
    except Exception:
        return None

    return segs or None
