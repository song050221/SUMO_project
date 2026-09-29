@echo off
cd /d "%~dp0"
echo SUMO CCTV 대시보드를 시작합니다...
start "SUMO CCTV Dashboard" cmd /k python scripts\dashboard_server.py
timeout /t 4 /nobreak >nul
start "" http://localhost:5000
