#!/bin/bash
set -e

echo "[LocalCameraHub] Starting Wine YI P2P Bridge on :8084..."
wine /app/python32/python.exe -u /app/yi_p2p_bridge_linux.py &
P2P_PID=$!

echo "[LocalCameraHub] Starting ONVIF PTZ Bridge on :8898 (cam3) & :8897 (cam4)..."
python3 -u /app/onvif_bridge.py &
ONVIF_PID=$!

echo "[LocalCameraHub] Starting Flask Surveillance Dashboard on :8080..."
python3 -u /app/app.py &
APP_PID=$!

echo "[LocalCameraHub] Starting native FFmpeg stream forwarders to MediaMTX..."

# Stream forwarder for Cam3
(
  while true; do
    ffmpeg -nostdin -loglevel warning -fflags nobuffer -flags low_delay \
      -f h264 -i tcp://127.0.0.1:19003 \
      -map 0:v -c:v copy -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam3 \
      -map 0:v -vf fps=1 -update 1 -y /tmp/cam3_snapshot.jpg 2>/dev/null || true
    sleep 2
  done
) &

# Stream forwarder for Cam4
(
  while true; do
    ffmpeg -nostdin -loglevel warning -fflags nobuffer -flags low_delay \
      -f h264 -i tcp://127.0.0.1:19004 \
      -map 0:v -c:v copy -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam4 \
      -map 0:v -vf fps=1 -update 1 -y /tmp/cam4_snapshot.jpg 2>/dev/null || true
    sleep 2
  done
) &

wait $P2P_PID $ONVIF_PID $APP_PID
