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
