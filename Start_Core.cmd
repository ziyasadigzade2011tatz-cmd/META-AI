@echo off
cd /d "%~dp0"
set "META_DATA_DIR=%~dp0local\data"
set "META5_STATE=%~dp0local\data\core_state"
set "META_CORE_CONFIG_DIR=%~dp0local\data\core_config"
"%~dp0.venv\Scripts\python.exe" -B -m uvicorn main:app --app-dir studio\core --host 127.0.0.1 --port 8000
