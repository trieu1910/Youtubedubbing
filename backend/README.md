# YouTube AI Dubbing — Local Backend

## Yêu cầu
- Windows 11, Python 3.10+, NVIDIA GPU (CUDA) khuyến nghị.
- ffmpeg trên PATH: `winget install Gyan.FFmpeg` (mở lại terminal sau khi cài).

## Cài đặt
```powershell
cd backend
powershell -ExecutionPolicy Bypass -File install.ps1
```
Script tạo venv, cài PyTorch CUDA 12.1, cài dependencies, kiểm tra ffmpeg + CUDA.

## Chạy
```powershell
powershell -ExecutionPolicy Bypass -File run.ps1
```
Backend lắng nghe tại http://localhost:8788. Kiểm tra: mở http://localhost:8788/health

## Extension
Vào `chrome://extensions`, bật Developer mode, "Load unpacked" → chọn thư mục `extension/`.
Mở popup, (tuỳ chọn) nhập Gemini API key, bấm "Kiểm tra backend".

## Ghi chú
- Lần chạy đầu tải model Whisper large-v3 (~3GB) và Demucs (~1GB).
- Nếu GPU hết VRAM ở bước Demucs: giảm `DEMUCS_SEGMENT` trong `config.py` xuống 5.
- Kết quả được cache tại `backend/cache/{videoId}_{lang}/output.m4a`.
