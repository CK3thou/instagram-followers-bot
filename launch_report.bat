@echo off
cd /d "%~dp0"
start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8765/'"
".venv\Scripts\python.exe" "web_app.py"
pause
