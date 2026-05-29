@echo off
chcp 65001 >nul
title YouTube AI Long Tieng - Backend
cd /d "%~dp0backend"

echo ============================================================
echo            YOUTUBE AI LONG TIENG  -  KHOI DONG
echo ============================================================
echo.

rem --- Kiem tra moi truong + thu vien nang; thieu thi tu dong cai ---
set NEED_INSTALL=0
if not exist "venv\Scripts\python.exe" set NEED_INSTALL=1
if "%NEED_INSTALL%"=="0" (
  venv\Scripts\python.exe -c "import torch, demucs, faster_whisper, yt_dlp, edge_tts, pydub" 1>nul 2>nul
  if errorlevel 1 set NEED_INSTALL=1
)
if "%NEED_INSTALL%"=="1" (
  echo [CAI DAT] Dang cai cac thu vien can thiet, co the mat vai phut...
  echo Vui long doi, KHONG dong cua so.
  echo.
  powershell -ExecutionPolicy Bypass -File "%~dp0backend\install.ps1"
  echo.
  venv\Scripts\python.exe -c "import torch, demucs, faster_whisper, yt_dlp, edge_tts, pydub" 1>nul 2>nul
  if errorlevel 1 (
    echo [LOI] Van con thieu thu vien sau khi cai. Hay chay backend\install.ps1 thu cong de xem loi.
    pause
    exit /b 1
  )
)

rem --- Kiem tra ffmpeg ---
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [CANH BAO] Chua thay ffmpeg trong PATH.
  echo   Hay cai:  winget install Gyan.FFmpeg   roi MO LAI file nay.
  echo   (Khong co ffmpeg thi tai audio va tron tieng se loi.)
  echo.
)

echo ------------------------------------------------------------
echo  Backend dang chay tai:  http://localhost:8788
echo.
echo  - GIU CUA SO NAY MO trong luc xem video.
echo  - Mo YouTube, bam nut "Long tieng video nay".
echo  - DONG cua so nay de TAT backend.
echo ------------------------------------------------------------
echo.

venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8788

echo.
echo Backend da dung. Nhan phim bat ky de dong.
pause >nul
