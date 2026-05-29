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
