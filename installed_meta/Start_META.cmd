@echo off
cd /d D:\META\Core
start "META Core" /min ".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
echo META Core launch requested.
echo You can close this launcher window.
timeout /t 3 >nul
