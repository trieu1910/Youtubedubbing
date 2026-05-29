# Run from backend/ : powershell -ExecutionPolicy Bypass -File run.ps1
& .\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8788
