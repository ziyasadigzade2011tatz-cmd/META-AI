@echo off
setlocal
cd /d "%~dp0"
set "PY=D:\META\Core\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Cannot find META Core Python: %PY%
  echo Set up META Core first.
  pause
  exit /b 1
)
echo Installing native Qt WebEngine for META 1.3...
"%PY%" -m pip install "PySide6==6.12.0" "PySide6-WebEngine==6.12.0.140"
if errorlevel 1 (
  echo Installation failed. Copy the output and share it.
  pause
  exit /b 1
)
echo Done! Open META.exe in this folder.
pause
