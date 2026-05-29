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
