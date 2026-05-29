import json

import config
from pipeline import asr, captions, download, segments, translate, tts


def _build_clip(vid, lang, idx, seg, next_start):
    """TTS one segment at the natural consistent rate (no time-stretching — that
    is what caused choppiness). Save as clip {idx}.mp3. The extension plays clips
    sequentially over the ducked original. Returns metadata, or None if no text."""
    text = (seg.get("translatedText") or "").strip()
    if not text:
        return None
    tts.synth_segment(text, lang, config.clip_path(vid, lang, idx))
    return {
        "index": idx,
        "start": round(seg["start"], 3),
        "end": round(seg["end"], 3),
        "text": text,
        "clip": f"/clip/{vid}/{lang}/{idx}",
    }


def _replay_cache(job, vid, lang):
    """If this video+lang was already processed, re-emit all segments instantly."""
    sp = config.segments_path(vid, lang)
    if not sp.exists():
        return False
    try:
        cached = json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not cached:
        return False
    # Only trust the cache if the clip files are still present.
    if not config.clip_path(vid, lang, cached[0]["index"]).exists():
        return False
    job.emit("cache", 100, f"Dùng bản lồng tiếng đã lưu ({len(cached)} câu)")
    for meta in cached:
        job.emit_segment(meta)
    job.finish("done")
    return True


def run_pipeline(job, api_key=None, start_at=0.0):
    """Streaming dubbing pipeline. No Demucs: the extension lowers the original
    audio and plays per-segment TTS clips over it. Segments are translated and
    synthesized in small chunks and emitted as soon as each is ready, so playback
    can start almost immediately. Processing begins near `start_at` (the current
    playback position) so clicking mid-video is responsive."""
    job.status = "running"
    vid, lang = job.video_id, job.lang

    try:
        if _replay_cache(job, vid, lang):
            return

        # 1) Transcript: prefer existing YouTube captions; fall back to Whisper.
        job.emit("captions", 8, "Đang lấy phụ đề YouTube...")
        segs = captions.get_captions(vid)
        if segs:
            job.emit("captions", 18, f"Dùng phụ đề có sẵn ({len(segs)} câu)")
        else:
            job.emit("download", 10, "Không có phụ đề — đang tải audio cho nhận dạng...")
            source = download.download_audio(vid, config.job_dir(vid, lang))
            job.emit("asr", 18, "Đang nhận dạng giọng nói (Whisper)...")
            segs = asr.transcribe(source)["segments"]
            asr.unload()
            if not segs:
                raise RuntimeError("Không có phụ đề và không nhận dạng được lời thoại.")

        # 2) Group caption fragments into sentence-level clips for smooth delivery.
        segs = segments.group_sentences(segs, config.GROUP_MAX_DUR)
        n = len(segs)
        if n == 0:
            raise RuntimeError("Không có câu nào để lồng tiếng.")

        # 3) Stream: translate + TTS in chunks (small first chunk for fast start),
        #    emit each ready segment immediately. Process from the current playback
        #    position to the end first, then wrap around to the earlier part.
        order = list(range(n))
        if start_at and start_at > 0:
            si = next((k for k, s in enumerate(segs) if s["end"] >= start_at), 0)
            order = list(range(si, n)) + list(range(0, si))

        produced = []
        pos = 0
        first = True
        done = 0
        while pos < len(order):
            size = config.FIRST_CHUNK if first else config.NEXT_CHUNK
            first = False
            idxs = order[pos:pos + size]
            chunk = [segs[k] for k in idxs]
            translate.translate_segments(chunk, lang, api_key)
            for k, seg in zip(idxs, chunk):
                next_start = segs[k + 1]["start"] if k + 1 < n else None
                meta = _build_clip(vid, lang, k, seg, next_start)
                done += 1
                if meta is None:
                    continue
                produced.append(meta)
                job.emit_segment(meta)
                job.emit("tts", min(99, 20 + int(done / n * 79)),
                         f"Đang lồng tiếng {done}/{n}...")
            pos += size

        if not produced:
            raise RuntimeError("Không tạo được giọng lồng tiếng (transcript rỗng?).")

        produced.sort(key=lambda m: m["index"])
        config.segments_path(vid, lang).write_text(
            json.dumps(produced, ensure_ascii=False), encoding="utf-8"
        )
        job.finish("done")
    except Exception as e:
        job.finish("error", str(e))
