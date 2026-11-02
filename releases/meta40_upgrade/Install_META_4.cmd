@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Close META Desktop and stop META Core before installing.
"D:\META\Core\.venv\Scripts\python.exe" "%~dp0install_meta40.py" --check
if errorlevel 1 goto failed
"D:\META\Core\.venv\Scripts\python.exe" "%~dp0install_meta40.py"
if errorlevel 1 goto failed
echo Done. Restart META Desktop. Open Agent 4.0 in the sidebar.
pause
exit /b 0
:failed
echo Installation failed. See error above.
pause
exit /b 1
