import json
import threading

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import config
import jobs
from pipeline.orchestrator import run_pipeline

app = FastAPI(title="YouTube AI Dubbing Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.youtube.com"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class DubRequest(BaseModel):
    videoId: str
    lang: str = "vi"
    geminiApiKey: str | None = None
    startAt: float = 0.0


@app.get("/health")
def health():
    info = {"status": "ok", "cuda": False, "ffmpeg": False, "device": "cpu"}
    try:
        import torch
        info["cuda"] = torch.cuda.is_available()
        if info["cuda"]:
            info["device"] = torch.cuda.get_device_name(0)
    except Exception:
        pass
    import shutil
    info["ffmpeg"] = shutil.which("ffmpeg") is not None
    return info


@app.post("/dub")
def dub(req: DubRequest):
    # A previously completed job is always re-run through the pipeline, which
    # replays the cached segments instantly when present.
    job, created = jobs.get_or_create(req.videoId, req.lang)
    if created:
        job.thread = threading.Thread(
            target=run_pipeline, args=(job, req.geminiApiKey, req.startAt), daemon=True
        )
        job.thread.start()
    cached = config.segments_path(req.videoId, req.lang).exists()
    return {"status": "running", "cached": cached}


@app.get("/progress/{video_id}/{lang}")
def progress(video_id: str, lang: str):
    job = jobs.get(video_id, lang)

    def stream():
        if job is None:
            # No live job: replay cached segments if we have them, else error.
            sp = config.segments_path(video_id, lang)
            if sp.exists():
                try:
                    for meta in json.loads(sp.read_text(encoding="utf-8")):
                        yield f"data: {json.dumps({'type': 'segment', **meta}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'status': 'done'})}\n\n"
                    return
                except Exception:
                    pass
            yield f"data: {json.dumps({'status': 'error', 'error': 'no job'})}\n\n"
            return
        while True:
            try:
                item = job.queue.get(timeout=120)
            except Exception:
                if job.status in ("done", "error"):
                    yield f"data: {json.dumps({'status': job.status, 'error': job.error}, ensure_ascii=False)}\n\n"
                    break
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            if "status" in item:
                break

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/segments/{video_id}/{lang}")
def segments(video_id: str, lang: str):
    sp = config.segments_path(video_id, lang)
    if not sp.exists():
        return {"segments": []}
    try:
        return {"segments": json.loads(sp.read_text(encoding="utf-8"))}
    except Exception:
        return {"segments": []}


@app.get("/clip/{video_id}/{lang}/{index}")
def clip(video_id: str, lang: str, index: int, request: Request):
    path = config.clip_path(video_id, lang, index)
    if not path.exists():
        return {"error": "not ready"}

    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        start, end = 0, file_size - 1
        try:
            _units, rng = range_header.split("=", 1)
            start_s, end_s = rng.split("-", 1)
            if start_s:
                start = int(start_s)
            if end_s:
                end = int(end_s)
        except Exception:
            start, end = 0, file_size - 1
        start = max(0, start)
        end = min(end, file_size - 1)
        if start > end:
            start, end = 0, file_size - 1
        length = end - start + 1

        def iter_range():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                chunk_size = 64 * 1024
                while remaining > 0:
                    data = f.read(min(chunk_size, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        }
        return StreamingResponse(
            iter_range(), status_code=206, media_type="audio/mpeg", headers=headers
        )

    return FileResponse(str(path), media_type="audio/mpeg",
                        headers={"Accept-Ranges": "bytes"})
