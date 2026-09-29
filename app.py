import os
import sys
import time
import socket
import subprocess
import threading
import ssl
import json
import urllib.request
from flask import Flask, Response, render_template_string, jsonify, request, send_file

app = Flask(__name__)

P2P_BRIDGE_URL = "http://127.0.0.1:8084"

def proxy_p2p_mjpeg(cam_id):
    """Proxies multipart MJPEG stream from the native Windows P2P bridge."""
    url = f"{P2P_BRIDGE_URL}/{cam_id}/video"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            while True:
                chunk = r.read(4096)
                if not chunk:
                    break
                yield chunk
    except Exception as e:
        print(f"P2P bridge stream error for {cam_id}: {e}")

CAMERAS = {
    "cam1": {
        "id": "cam1",
        "name": "Camera 1 (Macro-Video)",
        "ip": "192.168.0.238",
        "rtsp": "rtsp://192.168.0.238/live/ch00_1",
        "ptz_profile": "stream0_0",
        "resolution": "1280x720 HD",
        "codec": "H.264",
        "status": "Online",
        "has_ptz": True,
        "type": "onvif"
    },
    "cam2": {
        "id": "cam2",
        "name": "Camera 2 (Macro-Video)",
        "ip": "192.168.0.11",
        "rtsp": "rtsp://192.168.0.11/live/ch00_0",
        "ptz_profile": "PROFILE_000",
        "resolution": "1280x720 HD",
        "codec": "H.264",
        "status": "Online",
        "has_ptz": True,
        "type": "onvif"
    },
    "cam3": {
        "id": "cam3",
        "name": "Camera 3 (Storage - YI IoT)",
        "ip": "192.168.0.4",
        "rtsp": "Direct P2P",
        "ptz_profile": None,
        "resolution": "1280x720 HD",
        "codec": "Direct P2P H.264 -> MJPEG",
        "status": "Online",
        "has_ptz": False,
        "type": "yi_p2p"
    },
    "cam4": {
        "id": "cam4",
        "name": "Camera 4 (Cámara2 - YI IoT)",
        "ip": "192.168.0.135",
        "rtsp": "Direct P2P",
        "ptz_profile": None,
        "resolution": "1280x720 HD",
        "codec": "Direct P2P H.264 -> MJPEG",
        "status": "Online",
        "has_ptz": False,
        "type": "yi_p2p"
    }
}

def generate_mjpeg(rtsp_url):
    """Pipes RTSP to multipart MJPEG stream for in-browser playback."""
    cmd = [
        "ffmpeg",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-f", "image2pipe",
        "-pix_fmt", "yuvj420p",
        "-vcodec", "mjpeg",
        "-q:v", "5",
        "-r", "15",
        "-"
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=10**6
    )
    buf = b""
    try:
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            start = buf.find(b"\xff\xd8")
            end = buf.find(b"\xff\xd9", start + 2) if start != -1 else -1
            if start != -1 and end != -1:
                jpg = buf[start:end+2]
                buf = buf[end+2:]
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n\r\n"
                )
    except GeneratorExit:
        pass
    finally:
        try:
            proc.terminate()
            proc.kill()
        except:
            pass

def send_onvif_ptz(ip, profile, x, y, duration=0.4):
    """Sends ONVIF ContinuousMove and auto-stops after duration."""
    url = f"http://{ip}:8899/onvif/PTZ"
    soap_move = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"
               xmlns:tt="http://www.onvif.org/ver10/schema">
  <soap:Body>
    <tptz:ContinuousMove>
      <tptz:ProfileToken>{profile}</tptz:ProfileToken>
      <tptz:Velocity>
        <tt:PanTilt x="{x}" y="{y}"/>
      </tptz:Velocity>
    </tptz:ContinuousMove>
  </soap:Body>
</soap:Envelope>"""

    headers = {
        "Content-Type": "application/soap+xml; charset=utf-8; action=\"http://www.onvif.org/ver20/ptz/wsdl/ContinuousMove\""
    }

    try:
        req = urllib.request.Request(url, data=soap_move.encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=3):
            pass
    except Exception as e:
        return False, str(e)

    if duration > 0:
        def stop_later():
            time.sleep(duration)
            soap_stop = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"
               xmlns:tt="http://www.onvif.org/ver10/schema">
  <soap:Body>
    <tptz:ContinuousMove>
      <tptz:ProfileToken>{profile}</tptz:ProfileToken>
      <tptz:Velocity>
        <tt:PanTilt x="0.0" y="0.0"/>
      </tptz:Velocity>
    </tptz:ContinuousMove>
  </soap:Body>
</soap:Envelope>"""
            try:
                r_stop = urllib.request.Request(url, data=soap_stop.encode("utf-8"), headers=headers)
                with urllib.request.urlopen(r_stop, timeout=2):
                    pass
            except:
                pass
        threading.Thread(target=stop_later, daemon=True).start()

    return True, "Success"

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE, cameras=CAMERAS)

@app.route("/stream/<cam_id>")
def stream(cam_id):
    cam = CAMERAS.get(cam_id)
    if not cam:
        return "Camera not found", 404
    
    if cam.get("type") == "yi_p2p":
        return Response(
            proxy_p2p_mjpeg(cam_id),
            mimetype="multipart/x-mixed-replace; boundary=frame"
        )
    
    ip = cam["ip"]
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.6)
    res = s.connect_ex((ip, 554))
    s.close()

    if res != 0:
        return Response("RTSP stream is not currently available for this camera.", status=503)

    return Response(
        generate_mjpeg(cam["rtsp"]),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

@app.route("/snapshot/<cam_id>")
def snapshot(cam_id):
    cam = CAMERAS.get(cam_id)
    if not cam:
        return "Camera not found", 404
    
    if cam.get("type") == "yi_p2p":
        try:
            req = urllib.request.Request(f"{P2P_BRIDGE_URL}/{cam_id}/snapshot")
            with urllib.request.urlopen(req, timeout=5) as r:
                return Response(r.read(), mimetype="image/jpeg")
        except Exception as e:
            return f"Failed to capture snapshot: {e}", 500

    snap_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"snap_{cam_id}.jpg")
    cmd = [
        "ffmpeg", "-y",
        "-rtsp_transport", "tcp",
        "-i", cam["rtsp"],
        "-frames:v", "1",
        "-q:v", "2",
        snap_path
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        if os.path.exists(snap_path) and os.path.getsize(snap_path) > 1000:
            return send_file(snap_path, mimetype="image/jpeg", as_attachment=False)
    except:
        pass
    return "Failed to capture snapshot from RTSP feed", 500

@app.route("/api/ptz/<cam_id>")
def ptz_control(cam_id):
    cam = CAMERAS.get(cam_id)
    if not cam or not cam.get("has_ptz"):
        return jsonify({"success": False, "error": "PTZ not supported on this camera"})

    direction = request.args.get("dir", "stop").lower()
    speed = float(request.args.get("speed", 0.25))
    duration = float(request.args.get("duration", 0.35))

    x, y = 0.0, 0.0
    if direction == "left":
        x = -speed
    elif direction == "right":
        x = speed
    elif direction == "up":
        y = speed
    elif direction == "down":
        y = -speed
    elif direction == "stop":
        duration = 0.0

    if cam.get("type") == "tinycam":
        success, msg = send_tinycam_ptz(cam["tinycam_id"], x, y, duration)
    else:
        success, msg = send_onvif_ptz(cam["ip"], cam["ptz_profile"], x, y, duration)
    return jsonify({"success": success, "message": msg, "direction": direction})

@app.route("/api/launch_player")
def launch_player():
    player = request.args.get("player", "vlc")
    cam_id = request.args.get("cam_id", "cam1")
    cam = CAMERAS.get(cam_id)
    if not cam:
        return jsonify({"success": False, "error": "Camera not found"})

    url = cam["rtsp"]
    try:
        if player == "vlc":
            vlc_path = r"C:\Program Files\VideoLAN\VLC\vlc.exe"
            if not os.path.exists(vlc_path):
                vlc_path = r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"
            subprocess.Popen([vlc_path, "--network-caching=300", url])
            return jsonify({"success": True, "message": f"Launched VLC for {cam['name']}"})
        elif player == "ffplay":
            subprocess.Popen([
                "ffplay", "-rtsp_transport", "tcp",
                "-fflags", "nobuffer", "-flags", "low_delay",
                "-window_title", f"{cam['name']} Live Feed",
                url
            ])
            return jsonify({"success": True, "message": f"Launched ffplay for {cam['name']}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

    return jsonify({"success": False, "error": "Unknown player"})

@app.route("/api/records")
def list_records():
    """Scans all drives for camera 'record' directories and returns list of MP4 files."""
    clips = []
    # Check all potential drive letters
    drives = [f"{d}:\\" for d in "EDFGHIJKLMNOPQRSTUVWXYZ"]
    for root_drive in drives:
        rec_dir = os.path.join(root_drive, "record")
        if os.path.exists(rec_dir):
            for dirpath, _, filenames in os.walk(rec_dir):
                for f in filenames:
                    if f.lower().endswith(".mp4"):
                        full_p = os.path.join(dirpath, f)
                        try:
                            stat = os.stat(full_p)
                            size_mb = round(stat.st_size / (1024 * 1024), 2)
                            mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
                            clips.append({
                                "filename": f,
                                "path": full_p,
                                "size_mb": size_mb,
                                "date": mtime
                            })
                        except:
                            pass
    clips.sort(key=lambda x: x["date"], reverse=True)
    return jsonify({"success": True, "count": len(clips), "clips": clips})

@app.route("/api/records/play")
def play_record():
    file_path = request.args.get("file")
    if not file_path or not os.path.exists(file_path):
        return "File not found", 404
    return send_file(file_path, mimetype="video/mp4")

@app.route("/api/records/open_vlc")
def open_record_vlc():
    file_path = request.args.get("file")
    if not file_path or not os.path.exists(file_path):
        return jsonify({"success": False, "error": "File not found"})
    try:
        vlc_path = r"C:\Program Files\VideoLAN\VLC\vlc.exe"
        if not os.path.exists(vlc_path):
            vlc_path = r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"
        subprocess.Popen([vlc_path, file_path])
        return jsonify({"success": True, "message": "Opened clip in VLC"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Local Camera Hub - Live Feeds &amp; SD Player</title>
    <style>
        :root {
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-card: #182234;
            --accent: #38bdf8;
            --accent-hover: #0ea5e9;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --border: #334155;
            --success: #22c55e;
            --warning: #f59e0b;
            --danger: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 24px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
        }
        .title-group h1 { font-size: 24px; font-weight: 700; color: var(--accent); }
        .title-group p { font-size: 14px; color: var(--text-secondary); margin-top: 4px; }
        .badge {
            display: inline-flex;
            align-items: center;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 600;
        }
        .badge-online { background-color: rgba(34, 197, 94, 0.15); color: var(--success); }
        .badge-warning { background-color: rgba(245, 158, 11, 0.15); color: var(--warning); }
        .dot { width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
        .dot-green { background-color: var(--success); box-shadow: 0 0 8px var(--success); }
        .dot-orange { background-color: var(--warning); box-shadow: 0 0 8px var(--warning); }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
            gap: 24px;
            margin-bottom: 32px;
        }
        .cam-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
        }
        .cam-header {
            padding: 14px 18px;
            background-color: var(--bg-secondary);
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
        }
        .cam-header h3 { font-size: 16px; font-weight: 600; }
        .video-container {
            width: 100%;
            aspect-ratio: 16 / 9;
            background-color: #000;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
            overflow: hidden;
        }
        .video-feed {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        .video-placeholder {
            text-align: center;
            padding: 24px;
            color: var(--text-secondary);
        }
        .video-placeholder svg { width: 44px; height: 44px; margin-bottom: 10px; stroke: var(--text-secondary); }
        
        /* PTZ Controls Bar */
        .ptz-section {
            background-color: #111a29;
            padding: 10px 18px;
            border-top: 1px solid var(--border);
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .ptz-label {
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--accent);
        }
        .dpad-container {
            display: grid;
            grid-template-columns: repeat(3, 34px);
            grid-template-rows: repeat(3, 34px);
            gap: 4px;
        }
        .dpad-btn {
            background-color: var(--bg-secondary);
            border: 1px solid var(--border);
            color: var(--text-primary);
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.1s ease;
        }
        .dpad-btn:hover {
            background-color: var(--accent);
            color: #0f172a;
            border-color: var(--accent);
        }
        .dpad-btn:active { transform: scale(0.92); }
        .dpad-btn svg { width: 16px; height: 16px; }
        .dpad-stop {
            background-color: rgba(239, 68, 68, 0.15);
            color: var(--danger);
            border-color: rgba(239, 68, 68, 0.3);
        }
        .dpad-stop:hover {
            background-color: var(--danger);
            color: #fff;
            border-color: var(--danger);
        }

        .cam-footer {
            padding: 14px 18px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            background-color: var(--bg-card);
        }
        .info-row {
            display: flex;
            justify-content: space-between;
            font-size: 13px;
            color: var(--text-secondary);
        }
        .info-value { color: var(--text-primary); font-family: monospace; font-size: 12px; }
        .btn-group {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        .btn {
            flex: 1;
            min-width: 80px;
            padding: 8px 12px;
            background-color: var(--bg-secondary);
            border: 1px solid var(--border);
            color: var(--text-primary);
            border-radius: 6px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s ease;
            text-align: center;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
        }
        .btn:hover { background-color: var(--border); }
        .btn-primary { background-color: var(--accent); color: #0f172a; border-color: var(--accent); font-weight: 600; }
        .btn-primary:hover { background-color: var(--accent-hover); }

        /* Recorded Footage Section */
        .records-section {
            background-color: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            margin-top: 24px;
        }
        .records-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        .records-header h2 { font-size: 18px; color: var(--accent); }
        .player-layout {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
        }
        @media (max-width: 900px) {
            .player-layout { grid-template-columns: 1fr; }
        }
        .video-player-wrapper {
            background-color: #000;
            border-radius: 8px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        .video-player-wrapper video {
            width: 100%;
            aspect-ratio: 16 / 9;
            background-color: #000;
        }
        .player-meta {
            padding: 12px;
            background-color: var(--bg-secondary);
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 13px;
        }
        .clips-list {
            background-color: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 8px;
            max-height: 420px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
        }
        .clip-item {
            padding: 12px 14px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            transition: background 0.15s ease;
        }
        .clip-item:hover { background-color: rgba(56, 189, 248, 0.1); }
        .clip-item.active { background-color: rgba(56, 189, 248, 0.2); border-left: 3px solid var(--accent); }
        .clip-name { font-family: monospace; font-size: 13px; font-weight: 600; }
        .clip-sub { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }

        /* Non-blocking Toast Container */
        #toast-container {
            position: fixed;
            bottom: 24px;
            right: 24px;
            z-index: 9999;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .toast {
            min-width: 280px;
            max-width: 400px;
            background-color: var(--bg-secondary);
            color: var(--text-primary);
            padding: 12px 18px;
            border-radius: 8px;
            border-left: 4px solid var(--accent);
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
            font-size: 14px;
            opacity: 0;
            transform: translateY(20px);
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        }
        .toast.show {
            opacity: 1;
            transform: translateY(0);
        }
        .toast-success { border-left-color: var(--success); }
        .toast-error { border-left-color: var(--danger); }
        .toast-warning { border-left-color: var(--warning); }
        .toast-info { border-left-color: var(--accent); }
    </style>
</head>
<body>
    <div id="toast-container"></div>

    <div class="header">
        <div class="title-group">
            <h1>Local Camera Hub</h1>
            <p>Live RTSP Feeds, Motorized PTZ Controls &amp; SD Card Video Browser</p>
        </div>
        <button class="btn btn-primary" onclick="location.reload()" aria-label="Refresh All Feeds">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
            Refresh Hub
        </button>
    </div>

    <!-- Live Cameras Grid -->
    <div class="grid">
        <!-- Camera 1: 192.168.0.238 -->
        <div class="cam-card">
            <div class="cam-header">
                <h3>{{ cameras.cam1.name }}</h3>
                <span class="badge badge-online"><span class="dot dot-green"></span> Live RTSP</span>
            </div>
            <div class="video-container">
                <img class="video-feed" src="/stream/cam1" alt="Camera 1 Live Stream" onerror="this.onerror=null; this.src=''; this.parentElement.innerHTML='<div class=\\'video-placeholder\\'>Stream reconnecting...</div>';">
            </div>
            
            <div class="ptz-section">
                <div>
                    <span class="ptz-label">Motor PTZ Control</span>
                    <p style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;">Pan / Tilt Controls</p>
                </div>
                <div class="dpad-container">
                    <div></div>
                    <button class="dpad-btn" onclick="movePTZ('cam1', 'up')" title="Pan Up" aria-label="Pan Up">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"></polyline></svg>
                    </button>
                    <div></div>
                    <button class="dpad-btn" onclick="movePTZ('cam1', 'left')" title="Pan Left" aria-label="Pan Left">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"></polyline></svg>
                    </button>
                    <button class="dpad-btn dpad-stop" onclick="movePTZ('cam1', 'stop')" title="Stop Motor" aria-label="Stop Motor">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="2"></rect></svg>
                    </button>
                    <button class="dpad-btn" onclick="movePTZ('cam1', 'right')" title="Pan Right" aria-label="Pan Right">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"></polyline></svg>
                    </button>
                    <div></div>
                    <button class="dpad-btn" onclick="movePTZ('cam1', 'down')" title="Pan Down" aria-label="Pan Down">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
                    </button>
                    <div></div>
                </div>
            </div>

            <div class="cam-footer">
                <div class="info-row">
                    <span>IP / Port:</span>
                    <span class="info-value">{{ cameras.cam1.ip }}:554</span>
                </div>
                <div class="info-row">
                    <span>Format:</span>
                    <span class="info-value">{{ cameras.cam1.resolution }} ({{ cameras.cam1.codec }})</span>
                </div>
                <div class="btn-group">
                    <button class="btn" onclick="launch('vlc', 'cam1')" aria-label="Open Camera 1 in VLC">Open in VLC</button>
                    <button class="btn" onclick="launch('ffplay', 'cam1')" aria-label="Open Camera 1 in ffplay">Open in ffplay</button>
                    <a class="btn" href="/snapshot/cam1" target="_blank" download="cam1_snapshot.jpg" aria-label="Download snapshot for Camera 1">Snapshot</a>
                </div>
            </div>
        </div>

        <!-- Camera 2: 192.168.0.11 -->
        <div class="cam-card">
            <div class="cam-header">
                <h3>{{ cameras.cam2.name }}</h3>
                <span class="badge badge-online"><span class="dot dot-green"></span> Live RTSP</span>
            </div>
            <div class="video-container">
                <img class="video-feed" src="/stream/cam2" alt="Camera 2 Live Stream" onerror="this.onerror=null; this.src=''; this.parentElement.innerHTML='<div class=\\'video-placeholder\\'>Stream reconnecting...</div>';">
            </div>

            <div class="ptz-section">
                <div>
                    <span class="ptz-label">Motor PTZ Control</span>
                    <p style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;">Pan / Tilt Controls</p>
                </div>
                <div class="dpad-container">
                    <div></div>
                    <button class="dpad-btn" onclick="movePTZ('cam2', 'up')" title="Pan Up" aria-label="Pan Up">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"></polyline></svg>
                    </button>
                    <div></div>
                    <button class="dpad-btn" onclick="movePTZ('cam2', 'left')" title="Pan Left" aria-label="Pan Left">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"></polyline></svg>
                    </button>
                    <button class="dpad-btn dpad-stop" onclick="movePTZ('cam2', 'stop')" title="Stop Motor" aria-label="Stop Motor">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="2"></rect></svg>
                    </button>
                    <button class="dpad-btn" onclick="movePTZ('cam2', 'right')" title="Pan Right" aria-label="Pan Right">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"></polyline></svg>
                    </button>
                    <div></div>
                    <button class="dpad-btn" onclick="movePTZ('cam2', 'down')" title="Pan Down" aria-label="Pan Down">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
                    </button>
                    <div></div>
                </div>
            </div>

            <div class="cam-footer">
                <div class="info-row">
                    <span>IP / Port:</span>
                    <span class="info-value">{{ cameras.cam2.ip }}:554</span>
                </div>
                <div class="info-row">
                    <span>Format:</span>
                    <span class="info-value">{{ cameras.cam2.resolution }} ({{ cameras.cam2.codec }})</span>
                </div>
                <div class="btn-group">
                    <button class="btn" onclick="launch('vlc', 'cam2')" aria-label="Open Camera 2 in VLC">Open in VLC</button>
                    <button class="btn" onclick="launch('ffplay', 'cam2')" aria-label="Open Camera 2 in ffplay">Open in ffplay</button>
                    <a class="btn" href="/snapshot/cam2" target="_blank" download="cam2_snapshot.jpg" aria-label="Download snapshot for Camera 2">Snapshot</a>
                </div>
            </div>
        </div>

        <!-- Camera 3: 192.168.0.4 (Temu Anyka / Yi IoT CB101) -->
        <div class="cam-card">
            <div class="cam-header">
                <h3>{{ cameras.cam3.name }}</h3>
                <span class="badge badge-online"><span class="dot dot-green"></span> Live Stream</span>
            </div>
            <div class="video-container">
                <img class="video-feed" src="/stream/cam3" alt="Camera 3 Live Stream" onerror="this.onerror=null; this.src=''; this.parentElement.innerHTML='<div class=\'video-placeholder\'>Stream reconnecting...</div>';">
            </div>

            <div class="ptz-section">
                <div>
                    <span class="ptz-label">Motor PTZ Control</span>
                    <p style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;">Pan / Tilt Controls</p>
                </div>
                <div class="dpad-container">
                    <div></div>
                    <button class="dpad-btn" onclick="movePTZ('cam3', 'up')" title="Pan Up" aria-label="Pan Up">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"></polyline></svg>
                    </button>
                    <div></div>
                    <button class="dpad-btn" onclick="movePTZ('cam3', 'left')" title="Pan Left" aria-label="Pan Left">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"></polyline></svg>
                    </button>
                    <button class="dpad-btn dpad-stop" onclick="movePTZ('cam3', 'stop')" title="Stop Motor" aria-label="Stop Motor">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="2"></rect></svg>
                    </button>
                    <button class="dpad-btn" onclick="movePTZ('cam3', 'right')" title="Pan Right" aria-label="Pan Right">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"></polyline></svg>
                    </button>
                    <div></div>
                    <button class="dpad-btn" onclick="movePTZ('cam3', 'down')" title="Pan Down" aria-label="Pan Down">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
                    </button>
                    <div></div>
                </div>
            </div>

            <div class="cam-footer">
                <div class="info-row">
                    <span>IP / Source:</span>
                    <span class="info-value">{{ cameras.cam3.ip }} (P2P Bridge)</span>
                </div>
                <div class="info-row">
                    <span>Format:</span>
                    <span class="info-value">{{ cameras.cam3.resolution }} ({{ cameras.cam3.codec }})</span>
                </div>
                <div class="btn-group">
                    <a class="btn" href="/snapshot/cam3" target="_blank" download="cam3_snapshot.jpg" aria-label="Download snapshot for Camera 3">Snapshot</a>
                </div>
            </div>
        </div>

        <!-- Camera 4: 192.168.0.135 (Temu Anyka / Yi IoT CB101) -->
        <div class="cam-card">
            <div class="cam-header">
                <h3>{{ cameras.cam4.name }}</h3>
                <span class="badge badge-online"><span class="dot dot-green"></span> Live Stream</span>
            </div>
            <div class="video-container">
                <img class="video-feed" src="/stream/cam4" alt="Camera 4 Live Stream" onerror="this.onerror=null; this.src=''; this.parentElement.innerHTML='<div class=\'video-placeholder\'>Stream reconnecting...</div>';">
            </div>

            <div class="ptz-section">
                <div>
                    <span class="ptz-label">Motor PTZ Control</span>
                    <p style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;">Pan / Tilt Controls</p>
                </div>
                <div class="dpad-container">
                    <div></div>
                    <button class="dpad-btn" onclick="movePTZ('cam4', 'up')" title="Pan Up" aria-label="Pan Up">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"></polyline></svg>
                    </button>
                    <div></div>
                    <button class="dpad-btn" onclick="movePTZ('cam4', 'left')" title="Pan Left" aria-label="Pan Left">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"></polyline></svg>
                    </button>
                    <button class="dpad-btn dpad-stop" onclick="movePTZ('cam4', 'stop')" title="Stop Motor" aria-label="Stop Motor">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="2"></rect></svg>
                    </button>
                    <button class="dpad-btn" onclick="movePTZ('cam4', 'right')" title="Pan Right" aria-label="Pan Right">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"></polyline></svg>
                    </button>
                    <div></div>
                    <button class="dpad-btn" onclick="movePTZ('cam4', 'down')" title="Pan Down" aria-label="Pan Down">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
                    </button>
                    <div></div>
                </div>
            </div>

            <div class="cam-footer">
                <div class="info-row">
                    <span>IP / Source:</span>
                    <span class="info-value">{{ cameras.cam4.ip }} (P2P Bridge)</span>
                </div>
                <div class="info-row">
                    <span>Format:</span>
                    <span class="info-value">{{ cameras.cam4.resolution }} ({{ cameras.cam4.codec }})</span>
                </div>
                <div class="btn-group">
                    <a class="btn" href="/snapshot/cam4" target="_blank" download="cam4_snapshot.jpg" aria-label="Download snapshot for Camera 4">Snapshot</a>
                </div>
            </div>
        </div>
    </div>

    <!-- Recorded Footage Player Section -->
    <div class="records-section">
        <div class="records-header">
            <div>
                <h2>Recorded Camera Footage (SD Card)</h2>
                <p style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;" id="records-status">
                    Scanning for SD card recordings...
                </p>
            </div>
            <button class="btn" onclick="loadRecordings()" aria-label="Refresh Clips">Refresh Clips</button>
        </div>

        <div class="player-layout">
            <div class="video-player-wrapper">
                <video id="record-player" controls preload="metadata">
                    Your browser does not support HTML5 video.
                </video>
                <div class="player-meta">
                    <span id="playing-title" style="font-weight: 600;">Select a recording to play</span>
                    <div style="display: flex; gap: 8px;">
                        <button class="btn" id="btn-vlc-clip" style="display: none;" onclick="openSelectedInVLC()">Open in VLC</button>
                        <a class="btn" id="btn-dl-clip" style="display: none;" download>Download MP4</a>
                    </div>
                </div>
            </div>

            <div class="clips-list" id="clips-list">
                <div style="padding: 24px; text-align: center; color: var(--text-secondary); font-size: 13px;">
                    No recordings loaded.
                </div>
            </div>
        </div>
    </div>

    <script>
        let currentClipPath = null;

        function showToast(message, type = "info") {
            const container = document.getElementById("toast-container");
            const toast = document.createElement("div");
            toast.className = `toast toast-${type}`;
            toast.innerText = message;
            container.appendChild(toast);
            
            setTimeout(() => { toast.classList.add("show"); }, 20);
            setTimeout(() => {
                toast.classList.remove("show");
                setTimeout(() => { toast.remove(); }, 300);
            }, 3500);
        }

        function movePTZ(camId, dir) {
            fetch(`/api/ptz/${camId}?dir=${dir}&speed=0.25&duration=0.35`)
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        showToast(`Moved ${camId} ${dir.toUpperCase()}`, "info");
                    } else {
                        showToast(`PTZ Error: ${data.error || data.message}`, "error");
                    }
                })
                .catch(e => showToast("PTZ request failed: " + e, "error"));
        }

        function launch(player, camId) {
            showToast(`Launching ${player.toUpperCase()} for ${camId}...`, "info");
            fetch(`/api/launch_player?player=${player}&cam_id=${camId}`)
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        showToast(data.message, "success");
                    } else {
                        showToast(data.error, "error");
                    }
                })
                .catch(e => showToast("Launch error: " + e, "error"));
        }

        function loadRecordings() {
            const statusEl = document.getElementById("records-status");
            const listEl = document.getElementById("clips-list");
            statusEl.innerText = "Scanning drives for SD card recordings...";

            fetch("/api/records")
                .then(r => r.json())
                .then(data => {
                    if (!data.success || data.clips.length === 0) {
                        statusEl.innerText = "No SD card plugged into PC. Plug your camera's SD card into USB to browse recorded clips.";
                        listEl.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-secondary); font-size: 13px;">No recorded clips found on connected drives.</div>';
                        return;
                    }

                    statusEl.innerText = `Detected ${data.clips.length} recording(s) from camera SD card.`;
                    listEl.innerHTML = "";

                    data.clips.forEach((clip, index) => {
                        const item = document.createElement("div");
                        item.className = "clip-item";
                        item.innerHTML = `
                            <div>
                                <div class="clip-name">${clip.filename}</div>
                                <div class="clip-sub">${clip.date} • ${clip.size_mb} MB</div>
                            </div>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                        `;
                        item.onclick = () => selectClip(clip, item);
                        listEl.appendChild(item);

                        // Auto select first clip
                        if (index === 0 && !currentClipPath) {
                            selectClip(clip, item);
                        }
                    });
                })
                .catch(e => {
                    statusEl.innerText = "Error scanning records: " + e;
                });
        }

        function selectClip(clip, itemEl) {
            document.querySelectorAll(".clip-item").forEach(el => el.classList.remove("active"));
            if (itemEl) itemEl.classList.add("active");

            currentClipPath = clip.path;
            const player = document.getElementById("record-player");
            player.src = `/api/records/play?file=${encodeURIComponent(clip.path)}`;
            player.load();
            player.play().catch(() => {});

            document.getElementById("playing-title").innerText = `${clip.filename} (${clip.date})`;
            
            const btnVlc = document.getElementById("btn-vlc-clip");
            btnVlc.style.display = "inline-flex";

            const btnDl = document.getElementById("btn-dl-clip");
            btnDl.style.display = "inline-flex";
            btnDl.href = `/api/records/play?file=${encodeURIComponent(clip.path)}`;
            btnDl.download = clip.filename;
        }

        function openSelectedInVLC() {
            if (!currentClipPath) return;
            fetch(`/api/records/open_vlc?file=${encodeURIComponent(currentClipPath)}`)
                .then(r => r.json())
                .then(data => {
                    if (data.success) showToast(data.message, "success");
                    else showToast(data.error, "error");
                });
        }

        // Auto load recordings on page load
        window.addEventListener("load", loadRecordings);
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    print("=" * 60)
    print("Local Camera Hub starting on http://localhost:5000")
    print("Direct RTSP feeds + PTZ Motors + SD Card Video Browser")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
