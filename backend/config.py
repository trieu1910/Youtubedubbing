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
CLIP_EXT = "mp3"   # Edge-TTS native; played directly, no re-encode

# Consistent speaking rate (Edge-TTS prosody). A uniform mild speed-up keeps the
# Vietnamese (longer than English) on pace WITHOUT the choppy per-segment tempo
# changes that time-stretching caused.
TTS_RATE = "+15%"

# Group caption fragments into sentence-level clips up to this length (seconds)
# for natural, non-choppy delivery.
GROUP_MAX_DUR = 8.0

# Streaming: small first chunk for instant start, larger chunks afterwards.
FIRST_CHUNK = 3
NEXT_CHUNK = 16


def cache_key(video_id: str, lang: str) -> str:
    return f"{video_id}_{lang}"


def job_dir(video_id: str, lang: str) -> Path:
    d = CACHE_DIR / cache_key(video_id, lang)
    d.mkdir(parents=True, exist_ok=True)
    return d


def output_path(video_id: str, lang: str) -> Path:
    return job_dir(video_id, lang) / f"output.{OUTPUT_EXT}"


def segments_path(video_id: str, lang: str) -> Path:
    return job_dir(video_id, lang) / "segments.json"


def clips_dir(video_id: str, lang: str) -> Path:
    d = job_dir(video_id, lang) / "clips"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clip_path(video_id: str, lang: str, index: int) -> Path:
    return clips_dir(video_id, lang) / f"{index}.{CLIP_EXT}"
