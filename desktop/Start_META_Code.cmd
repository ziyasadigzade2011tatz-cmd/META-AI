@echo off
cd /d "%~dp0"
set "PY=D:\META\Core\.venv\Scripts\python.exe"
if not exist "%PY%" (echo META Core Python not found & pause & exit /b 1)
"%PY%" -m pip install rich prompt_toolkit
"%PY%" -m metacode.cli "D:\META\Projects"
pause
