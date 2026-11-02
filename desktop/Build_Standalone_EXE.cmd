@echo off
setlocal
cd /d "%~dp0"
set "PY=D:\META\Core\.venv\Scripts\python.exe"
"%PY%" -m pip install "PySide6==6.12.0" "PySide6-WebEngine==6.12.0.140" pyinstaller
if errorlevel 1 (pause & exit /b 1)
"%PY%" -m PyInstaller --clean --noconfirm --windowed --name META_Desktop_1_3 --icon "assets\meta.ico" --collect-all PySide6 --collect-all PySide6_WebEngine --add-data "assets;assets" meta_desktop.py
if errorlevel 1 (pause & exit /b 1)
echo The distributable application is in dist\META_Desktop_1_3\
echo Ollama and META Core are still separate services.
pause
