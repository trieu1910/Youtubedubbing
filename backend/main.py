import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import config
import jobs
from pipeline.orchestrator import run_pipeline
import threading

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
    out = config.output_path(req.videoId, req.lang)
    if out.exists():
        return {"status": "done", "cached": True}
    job, created = jobs.get_or_create(req.videoId, req.lang)
    if created:
        job.thread = threading.Thread(
            target=run_pipeline, args=(job, req.geminiApiKey), daemon=True
        )
        job.thread.start()
    return {"status": "running", "cached": False}


@app.get("/progress/{video_id}/{lang}")
def progress(video_id: str, lang: str):
    job = jobs.get(video_id, lang)

    def stream():
        if job is None:
            out = config.output_path(video_id, lang)
            status = "done" if out.exists() else "error"
            yield f"data: {json.dumps({'status': status})}\n\n"
            return
        while True:
            try:
                item = job.queue.get(timeout=120)
            except Exception:
                # No item within the window. If the job already terminated
                # (e.g. it crashed before emitting a terminal event, or a client
                # reconnected after the queue was drained), emit a terminal event
                # so the client never blocks forever; otherwise send a heartbeat.
                if job.status in ("done", "error"):
                    yield f"data: {json.dumps({'status': job.status, 'error': job.error}, ensure_ascii=False)}\n\n"
                    break
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            if "status" in item:
                break

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/audio/{video_id}/{lang}")
def audio(video_id: str, lang: str, request: Request):
    out = config.output_path(video_id, lang)
    if not out.exists():
        return {"error": "not ready"}

    file_size = out.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        # Parse "bytes=start-end"
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
            with open(out, "rb") as f:
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
            iter_range(), status_code=206, media_type="audio/mp4", headers=headers
        )

    return FileResponse(
        str(out),
        media_type="audio/mp4",
        headers={"Accept-Ranges": "bytes"},
    )
