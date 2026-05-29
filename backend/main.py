import json
import threading

from fastapi import FastAPI
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
            item = job.queue.get()
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            if "status" in item:
                break

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/audio/{video_id}/{lang}")
def audio(video_id: str, lang: str):
    out = config.output_path(video_id, lang)
    if not out.exists():
        return {"error": "not ready"}
    return FileResponse(
        str(out),
        media_type="audio/mp4",
        headers={"Accept-Ranges": "bytes"},
    )
