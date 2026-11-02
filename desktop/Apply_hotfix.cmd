@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install_hotfix_in_existing_1_3.ps1"
if errorlevel 1 (echo Update failed; original META was not modified if validation failed.)
pause
