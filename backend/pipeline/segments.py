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
    # A segment is "short" if its own duration < merge_min_dur.
    # Short segments get merged into the following segment.
    merged = []
    i = 0
    while i < len(segments):
        cur = {"start": segments[i]["start"], "end": segments[i]["end"],
               "text": segments[i]["text"].strip()}
        dur = cur["end"] - cur["start"]
        if dur < merge_min_dur and i + 1 < len(segments):
            nxt = segments[i + 1]
            cur = {
                "start": cur["start"],
                "end": nxt["end"],
                "text": (cur["text"] + " " + nxt["text"].strip()).strip(),
            }
            i += 2
        else:
            i += 1
        merged.append(cur)

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
