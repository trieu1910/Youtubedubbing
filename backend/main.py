from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="YouTube AI Dubbing Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.youtube.com"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
