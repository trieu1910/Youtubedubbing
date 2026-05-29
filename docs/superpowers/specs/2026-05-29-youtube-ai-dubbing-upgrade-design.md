# YouTube AI Dubbing — Nâng cấp toàn diện (Design Spec)

**Ngày:** 2026-05-29
**Mục tiêu:** Nâng cấp extension "YouTube AI Translator & Dubber" để dịch + lồng tiếng đạt chất lượng như các video lồng tiếng chuyên nghiệp trên YouTube.

---

## 1. Bối cảnh & vấn đề của bản gốc

Bản gốc là Chrome extension thuần (MV3) chạy mọi thứ trong trình duyệt. Các hạn chế cốt lõi:

1. **TTS trình duyệt** (`speechSynthesis`, `rate=3`): giọng máy móc, đọc nhanh, phụ thuộc giọng cài trên máy.
2. **Không khớp thời lượng (no time-fit)**: bắn TTS rời từng câu theo timestamp → trôi lệch dần, bị cắt câu.
3. **Không tách nhạc nền**: phải tắt hẳn tiếng gốc, mất nhạc/hiệu ứng.
4. **Phụ thuộc phụ đề có sẵn**: video không có caption → bó tay (không có ASR).
5. **Dịch rời từng câu**: mất ngữ cảnh, không nhất quán.

**Kết luận:** Không thể đạt mục tiêu bằng extension thuần. Whisper (ASR), Demucs (tách nhạc), TTS chất lượng cao cần Python + GPU + truy cập audio thô, và phải **xử lý trước (pre-render)** chứ không real-time.

## 2. Lựa chọn đã chốt

| Thành phần | Quyết định | Lý do |
|---|---|---|
| Kiến trúc | Chrome Extension (UI) + Local Python Backend (xử lý) | Bắt buộc để chạy Whisper/Demucs/TTS chất lượng |
| Phần cứng đích | NVIDIA RTX 4050 Laptop, 6GB VRAM, CUDA | Của người dùng |
| ASR | `faster-whisper` large-v3 (CUDA, int8_float16), local | Chạy nhanh trên GPU, tự tạo transcript kể cả video không sub |
| Tách nhạc nền | Demucs (htdemucs), giữ track `no_vocals` | Giữ nhạc + SFX, bỏ giọng gốc |
| Dịch | Gemini API (free tier) theo đoạn + fallback Google free | Giữ ngữ cảnh, tự nhiên |
| TTS | Edge-TTS (vi-VN neural, free) | Free, chất lượng cao, không tốn VRAM |
| Khớp thời gian | Edge-TTS rate + time-stretch giữ cao độ (atempo/rubberband) + mượn khoảng lặng | Khớp khung, không méo giọng |
| Số giọng | 1 giọng | Đơn giản (kiến trúc vẫn mở để thêm đa giọng sau) |
| Cách xem | Phát đè real-time trên YouTube | Xem ngay trên trang, như bản gốc |
| Đồng bộ | 1 file audio hoàn chỉnh, khóa `audio.currentTime = video.currentTime` | Không trôi, tua/đổi tốc độ vẫn khớp |
| Ngôn ngữ đích mặc định | Tiếng Việt (`vi`) | Có thể đổi trong popup |
| Cổng backend | `localhost:8788` (cấu hình được trong popup) | — |

## 3. Kiến trúc tổng thể

```
Chrome Extension (UI trên YouTube)          Local Backend (FastAPI, localhost:8788)
─────────────────────────────────          ──────────────────────────────────────
[Nút: Lồng tiếng video này] ──POST /dub──►  1. yt-dlp tải audio theo videoId
[Thanh tiến trình] ◄──SSE /progress──────   2. faster-whisper → transcript + timestamp (word-level)
                                            3. Demucs → tách vocals / no_vocals(nhạc+SFX)
                                            4. Gemini dịch theo đoạn (giữ ngữ cảnh)
                                            5. Edge-TTS đọc từng câu
                                            6. Khớp thời gian: stretch mỗi câu vừa khung
                                            7. Mix: nhạc nền + giọng dịch (sidechain ducking)
[<audio> phát đè] ◄──GET /audio/{id}─────   8. Xuất 1 file audio + cache theo videoId+lang
[khóa currentTime theo video]
```

Backend chạy các stage **tuần tự** → Whisper xong giải phóng VRAM rồi mới chạy Demucs → 6GB VRAM thoải mái.

## 4. Backend — chi tiết pipeline

### 4.1 Tech stack
- Python 3.10+, FastAPI + uvicorn (async, hỗ trợ SSE cho tiến trình).
- ffmpeg (bắt buộc, cho time-stretch + mix).
- Thư viện: `yt-dlp`, `faster-whisper`, `demucs`, `edge-tts`, `google-generativeai`, `pydub`/`ffmpeg-python`, `pyrubberband` (tùy chọn, nếu không có dùng `atempo`).

### 4.2 Các stage
1. **download.py** — `yt-dlp` tải audio tốt nhất theo `videoId` → `cache/{videoId}/source.m4a`.
2. **asr.py** — `faster-whisper` (large-v3, device=cuda, compute_type=int8_float16, word_timestamps=True) → danh sách segment `{start, end, text, words[]}`. Tự phát hiện ngôn ngữ nguồn.
3. **separate.py** — Demucs (htdemucs, `--two-stems=vocals`, `--segment` để vừa 6GB VRAM) → `no_vocals.wav` (nền) + `vocals.wav`.
4. **translate.py** — Gemini (`gemini-2.x-flash` hoặc mới nhất khả dụng) dịch **theo cụm nhiều câu** kèm ngữ cảnh (truyền cả đoạn, yêu cầu giữ id/timestamp). Fallback Google free khi lỗi/hết quota. Trả mỗi segment kèm `translatedText`.
5. **tts.py** — Edge-TTS đọc từng `translatedText` (giọng theo `lang`) → file wav tạm + đo độ dài thực.
6. **timefit.py** — khớp thời gian (mục 5).
7. **mix.py** — ghép nền + giọng + ducking (mục 6) → 1 file audio đầu ra.

### 4.3 API
- `POST /dub` body `{videoId, lang, geminiApiKey?}` → trả `{jobId}` (nếu đã có cache → trả luôn `{status:"done"}`).
- `GET /progress/{jobId}` (SSE) → stream `{stage, percent, message}`; kết thúc `{status:"done"|"error"}`.
- `GET /audio/{videoId}_{lang}` → trả file audio, hỗ trợ `Accept-Ranges` (để tua).
- `GET /health` → kiểm tra backend sống + GPU khả dụng.

## 5. Khớp khung thời gian (time-fit) — phần cốt lõi

Tiền xử lý segment: gộp câu quá ngắn, tách câu quá dài tại ranh giới câu (dùng word timestamps) để prosody tự nhiên.

Cho mỗi câu có khung `[start, end]`:
1. Edge-TTS đọc → đo `actual_duration`.
2. `gap` = khoảng lặng tới câu kế (start câu sau − end câu này). `target = (end - start) + min(gap, GAP_BORROW_MAX)`.
3. `ratio = actual / target`:
   - `0.9 ≤ ratio ≤ 1.15`: chấp nhận, chỉnh nhẹ nếu cần.
   - `ratio > 1.15` (quá dài): time-stretch nhanh lại, **giữ cao độ** (`rubberband` ưu tiên, fallback ffmpeg `atempo`), cap tốc độ ~1.4x. Nếu vẫn dư → cho tràn vào `gap`; nếu hết gap → chấp nhận tràn nhẹ sang câu sau.
   - `ratio < 0.9` (quá ngắn): chèn im lặng cuối (không kéo chậm để tránh méo).
4. Đặt audio mỗi câu vào đúng `start` trên một track im lặng dài bằng video.

Hằng số (cấu hình được): `MAX_SPEEDUP=1.4`, `GAP_BORROW_MAX=1.2s`, `MERGE_MIN_DUR=0.8s`, `SPLIT_MAX_DUR=12s`.

## 6. Mixing
- Nền = `no_vocals.wav` (Demucs).
- Voice track = các đoạn giọng dịch đặt đúng vị trí, phần còn lại im lặng.
- **Sidechain ducking**: hạ âm lượng nền (~ -8 đến -12 dB) khi có giọng nói để rõ lời; trả lại khi im lặng.
- Trộn → 1 file (`.m4a` AAC hoặc `.opus`), độ dài đúng bằng video, `Accept-Ranges` bật.
- Lưu `cache/{videoId}_{lang}/output.m4a` + metadata `{duration, createdAt}`.

## 7. Extension — đồng bộ phát đè

### 7.1 manifest.json
- Giữ MV3. Thêm `host_permissions`: `http://localhost:8788/*` (và cho phép đổi cổng).
- Giữ content script trên `youtube.com/*`.

### 7.2 content.js (viết lại)
- UI overlay: nút "Lồng tiếng video này", thanh tiến trình (đọc từ SSE), thanh chỉnh âm lượng giọng lồng + nền, nút giữ/tắt tiếng gốc.
- Khi bấm: gọi `POST /dub`, lắng nghe SSE tiến trình, khi `done` → tạo `<audio src="GET /audio/...">`.
- **Đồng bộ:**
  - `video.muted = true` (tắt tiếng gốc). Tùy chọn giữ tiếng gốc ở mức nhỏ.
  - Sự kiện: `play`→`audio.play()`, `pause`→`audio.pause()`, `seeking/seeked`→`audio.currentTime = video.currentTime`, `ratechange`→`audio.playbackRate = video.playbackRate`.
  - Vòng kiểm tra trôi mỗi 500ms: nếu `|audio.currentTime − video.currentTime| > 0.25s` → resync.
- Xử lý SPA navigation của YouTube (đổi video → reset).

### 7.3 popup.html/js
- Chọn ngôn ngữ đích, nhập Gemini API key (lưu `chrome.storage`), nhập địa chỉ backend (mặc định `localhost:8788`), nút kiểm tra kết nối backend.

## 8. Caching
- Khóa cache: `{videoId}_{lang}`. Có cache → phát ngay, bỏ qua pipeline.
- Lưu source audio, các track trung gian (tùy chọn xóa để tiết kiệm đĩa), output cuối + metadata.

## 9. Xử lý lỗi
- Backend chưa bật → extension báo "Hãy khởi động backend local" kèm hướng dẫn.
- Video không sub → vẫn chạy (Whisper tự nghe ra transcript) — lợi thế lớn so với bản gốc.
- Hết quota Gemini → tự fallback Google free.
- Lỗi từng stage → SSE trả thông báo cụ thể; cleanup file tạm.
- Thiếu ffmpeg / CUDA → `/health` cảnh báo sớm.

## 10. Cấu trúc thư mục
```
backend/
  ├─ main.py
  ├─ pipeline/
  │   ├─ download.py
  │   ├─ asr.py
  │   ├─ separate.py
  │   ├─ translate.py
  │   ├─ tts.py
  │   ├─ timefit.py
  │   └─ mix.py
  ├─ cache/
  ├─ requirements.txt
  └─ README.md   # hướng dẫn cài đặt + chạy
extension/
  ├─ manifest.json
  ├─ background.js
  ├─ content.js
  ├─ popup.html
  ├─ popup.js
  └─ styles.css
```

## 11. Ngoài phạm vi (YAGNI — để dành sau)
- Đa giọng theo người nói (speaker diarization / pyannote).
- Voice cloning giọng gốc (Coqui XTTS).
- Xuất file video đã lồng tiếng để tải về.
- Hỗ trợ video > ~1 giờ tối ưu riêng (vẫn chạy được, chỉ lâu hơn).

## 12. Tiêu chí thành công
- Video không sub vẫn lồng tiếng được.
- Giọng dịch tự nhiên (Edge-TTS neural), không bị đọc nhanh/méo.
- Lời thoại khớp khung thời gian, không trôi khi xem/tua/đổi tốc độ.
- Nghe được nhạc nền + hiệu ứng gốc dưới giọng lồng (không phải nền câm).
- Xem lại video đã xử lý là phát ngay (cache).
