# Run from backend/ : powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
Write-Host "Creating virtualenv..."
python -m venv venv
& .\venv\Scripts\python.exe -m pip install --upgrade pip

Write-Host "Installing PyTorch (CUDA 12.1)..."
& .\venv\Scripts\pip.exe install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

Write-Host "Installing Python dependencies..."
& .\venv\Scripts\pip.exe install -r requirements.txt

Write-Host "Checking ffmpeg..."
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
  Write-Host "ffmpeg found."
} else {
  Write-Warning "ffmpeg NOT found on PATH. Install it (winget install Gyan.FFmpeg) and re-open the terminal."
}

Write-Host "Checking CUDA..."
& .\venv\Scripts\python.exe -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
Write-Host "Install complete."
