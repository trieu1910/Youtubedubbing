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
