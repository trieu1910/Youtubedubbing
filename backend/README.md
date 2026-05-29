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

## Cách hoạt động (chế độ streaming nhanh)
1. Lấy transcript: ưu tiên **phụ đề YouTube có sẵn** (nhanh, không cần GPU). Chỉ khi
   không có phụ đề mới tải audio + chạy **Whisper** (ASR).
2. Dịch (Gemini, fallback Google free) + tạo giọng **Edge-TTS** theo từng cụm câu,
   bắt đầu từ vị trí đang xem. Mỗi câu được co giãn cho khớp khung thời gian.
3. Extension **hạ nhỏ tiếng gốc** (~12%) và phát từng clip lồng tiếng đúng mốc thời gian.
   → Bắt đầu nghe gần như tức thì, vừa xem vừa nạp.

Không dùng Demucs (không tách nhạc nền) để đạt tốc độ tối đa. Bạn nghe lồng tiếng
đè lên audio gốc đã được hạ nhỏ (vẫn còn nhạc nền). Chỉnh "Âm lượng gốc" / "Âm lượng
lồng tiếng" trong bảng điều khiển trên trang video.

## Ghi chú
- Chỉ video **không có phụ đề** mới cần Whisper (lần đầu tải model large-v3 ~3GB).
- Kết quả được cache theo câu tại `backend/cache/{videoId}_{lang}/` (clips + segments.json),
  xem lại là phát ngay.
- `separate.py` / `mix.py` (Demucs + trộn nhạc nền) còn lại để dành cho chế độ
  "chất lượng cao" sau này, hiện không dùng trong luồng mặc định.
