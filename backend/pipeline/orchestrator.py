from pathlib import Path

import config
from pipeline import asr, download, mix, segments, separate, timefit, translate, tts


def run_pipeline(job, api_key=None):
    """Full dubbing pipeline. Emits progress on the job. Writes output.m4a."""
    job.status = "running"
    vid, lang = job.video_id, job.lang
    jd = config.job_dir(vid, lang)
    out = config.output_path(vid, lang)

    if out.exists():
        job.finish("done")
        return

    try:
        job.emit("download", 5, "Đang tải audio...")
        source = download.download_audio(vid, jd)

        job.emit("asr", 20, "Đang nhận dạng giọng nói (Whisper)...")
        tr = asr.transcribe(source)
        segs = tr["segments"]
        if not segs:
            raise RuntimeError("Không nhận dạng được lời thoại trong video.")
        asr.unload()  # free VRAM before Demucs

        job.emit("separate", 40, "Đang tách nhạc nền (Demucs)...")
        background = separate.separate_background(source, jd / "sep")

        job.emit("segments", 45, "Đang chuẩn hoá câu...")
        segs = segments.merge_and_split(
            segs, config.MERGE_MIN_DUR, config.SPLIT_MAX_DUR
        )

        job.emit("translate", 55, "Đang dịch (Gemini)...")
        segs = translate.translate_segments(
            segs, lang, api_key,
            progress=lambda p: job.emit("translate", 55 + int(p * 15),
                                        "Đang dịch (Gemini)..."),
        )

        job.emit("tts", 72, "Đang tạo giọng đọc (Edge-TTS)...")
        clips_dir = jd / "clips"
        clips_dir.mkdir(exist_ok=True)
        fitted_clips = []  # (path, start_s)
        n = len(segs)
        for i, s in enumerate(segs):
            text = (s.get("translatedText") or "").strip()
            if not text:
                continue
            raw = clips_dir / f"{i}.mp3"
            tts.synth_segment(text, lang, raw)
            actual = tts.measure_duration(raw)
            next_start = segs[i + 1]["start"] if i + 1 < n else None
            target = timefit.target_duration(s, next_start, config.GAP_BORROW_MAX)
            fit = timefit.compute_fit(actual, target, config.MAX_SPEEDUP,
                                      config.FIT_LOW, config.FIT_HIGH)
            fitted = clips_dir / f"{i}_fit.wav"
            timefit.apply_fit(raw, fitted, fit["atempo"], fit["pad"])
            fitted_clips.append((fitted, s["start"]))
            if i % 5 == 0:
                job.emit("tts", 72 + int((i / max(1, n)) * 16),
                         f"Đang tạo giọng đọc {i+1}/{n}...")

        job.emit("mix", 90, "Đang trộn nhạc nền + giọng...")
        total = max((s["end"] for s in segs), default=0.0)
        voice_track = mix.build_voice_track(fitted_clips, total, jd / "voice.wav")
        mix.mix_with_ducking(background, voice_track, out)

        job.emit("done", 100, "Hoàn tất!")
        job.finish("done")
    except Exception as e:
        job.finish("error", str(e))
