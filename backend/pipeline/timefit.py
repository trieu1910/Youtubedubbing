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
    return {"atempo": 1.0, "pad": target - actual}


def apply_fit(in_path: Path, out_path: Path, atempo: float, pad: float) -> Path:
    """Apply pitch-preserving tempo change + trailing silence using ffmpeg.
    atempo accepts 0.5..2.0 per filter; we stay within 1.0..1.4 so one stage is fine."""
    filters = []
    if abs(atempo - 1.0) > 1e-3:
        filters.append(f"atempo={atempo:.4f}")
    if pad and pad > 0.01:
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
