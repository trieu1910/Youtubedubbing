@echo off
chcp 65001 >nul
title YouTube AI Long Tieng - Backend
cd /d "%~dp0backend"

echo ============================================================
echo            YOUTUBE AI LONG TIENG  -  KHOI DONG
echo ============================================================
echo.

rem --- Lan dau chua co moi truong thi tu dong cai dat ---
if not exist "venv\Scripts\python.exe" (
  echo [LAN DAU] Chua co moi truong Python. Dang cai dat...
  echo Buoc nay chi chay 1 lan, co the mat vai phut. Vui long doi.
  echo.
  powershell -ExecutionPolicy Bypass -File "%~dp0backend\install.ps1"
  echo.
  if not exist "venv\Scripts\python.exe" (
    echo [LOI] Cai dat that bai. Hay chay backend\install.ps1 thu cong de xem loi.
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
