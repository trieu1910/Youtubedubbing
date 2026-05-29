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
