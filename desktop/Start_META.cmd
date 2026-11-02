@echo off
cd /d "%~dp0"
"D:\META\Core\.venv\Scripts\python.exe" meta_desktop.py
if errorlevel 1 pause
