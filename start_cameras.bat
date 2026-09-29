@echo off
title Local Camera Hub + Native P2P Gateway
echo ===================================================
echo Starting YI IoT Native P2P Gateway (Port 8084)...
echo ===================================================
start "YI P2P Gateway" /min "C:\Users\CHRISTOPHER\Downloads\python32\python.exe" "C:\Users\CHRISTOPHER\Downloads\LocalCameraHub\yi_p2p_bridge.py"

timeout /t 3 /nobreak >nul

echo ===================================================
echo Starting Local Camera Hub (Port 5000)...
echo ===================================================
start "Local Camera Hub" /min "python" "C:\Users\CHRISTOPHER\Downloads\LocalCameraHub\app.py"

timeout /t 2 /nobreak >nul
echo All services running!
echo Dashboard available at: http://localhost:5000
start http://localhost:5000
