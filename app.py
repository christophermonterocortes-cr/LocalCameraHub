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
PLACEHOLDER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "placeholder.jpg")

def proxy_p2p_mjpeg(cam_id):
    """Proxies multipart MJPEG stream from the native Windows P2P bridge."""
    url = f"{P2P_BRIDGE_URL}/{cam_id}/video"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            while True:
                chunk = r.read(32768)
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
        "rtsp": "rtsp://192.168.0.245:8554/cam1",
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
        "rtsp": "rtsp://192.168.0.245:8554/cam2",
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
        "rtsp": "rtsp://192.168.0.245:8554/cam3",
        "ptz_profile": None,
        "resolution": "1280x720 HD",
        "codec": "H.264 (P2P -> RTSP)",
        "status": "Online",
        "has_ptz": True,
        "type": "yi_p2p"
    },
    "cam4": {
        "id": "cam4",
        "name": "Camera 4 (Cámara2 - YI IoT)",
        "ip": "192.168.0.135",
        "rtsp": "rtsp://192.168.0.245:8554/cam4",
        "ptz_profile": None,
        "resolution": "1280x720 HD",
        "codec": "H.264 (P2P -> RTSP)",
        "status": "Online",
        "has_ptz": True,
        "type": "yi_p2p"
    }
}


def generate_mjpeg(rtsp_url):
    """Pipes RTSP to multipart MJPEG stream for in-browser playback."""
    if os.path.exists(PLACEHOLDER_PATH):
        try:
            with open(PLACEHOLDER_PATH, "rb") as f:
                p_jpg = f.read()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(p_jpg)).encode() + b"\r\n\r\n" + p_jpg + b"\r\n\r\n"
            )
        except:
            pass

    cmd = [
        "ffmpeg",
        "-rtsp_transport", "tcp",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-analyzeduration", "1000000",
        "-probesize", "1000000",
        "-i", rtsp_url,
        "-f", "image2pipe",
        "-pix_fmt", "yuvj420p",
        "-vcodec", "mjpeg",
        "-q:v", "2",
        "-r", "25",
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

def _send_onvif_stop(ip, profile):
    url = f"http://{ip}:8899/onvif/PTZ"
    # cam1 (.238) supports <tptz:Stop>
    # cam2 (.11) rejects Stop (ActionNotSupported), requires ContinuousMove(0.0, 0.0)
    if "238" in ip or "stream0_0" in profile:
        soap_stop = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl">
  <soap:Body>
    <tptz:Stop>
      <tptz:ProfileToken>{profile}</tptz:ProfileToken>
      <tptz:PanTilt>true</tptz:PanTilt>
    </tptz:Stop>
  </soap:Body>
</soap:Envelope>"""
        headers = {
            "Content-Type": "application/soap+xml; charset=utf-8; action=\"http://www.onvif.org/ver20/ptz/wsdl/Stop\""
        }
    else:
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
        headers = {
            "Content-Type": "application/soap+xml; charset=utf-8; action=\"http://www.onvif.org/ver20/ptz/wsdl/ContinuousMove\""
        }
    try:
        req = urllib.request.Request(url, data=soap_stop.encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=3):
            return True, "Stopped"
    except Exception as e:
        return False, str(e)

def send_onvif_ptz(ip, profile, x, y, duration=0.25):
    """Sends ONVIF ContinuousMove and auto-stops after duration."""
    if x == 0.0 and y == 0.0:
        return _send_onvif_stop(ip, profile)

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
            _send_onvif_stop(ip, profile)
        threading.Thread(target=stop_later, daemon=True).start()

    return True, "Success"

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE, cameras=CAMERAS)

@app.route("/stream/<cam_id>")
@app.route("/video_feed/<cam_id>")
def stream(cam_id):
    cam = CAMERAS.get(cam_id)
    if not cam:
        return "Camera not found", 404
    
    if cam.get("type") == "yi_p2p":
        resp = Response(
            proxy_p2p_mjpeg(cam_id),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            direct_passthrough=True
        )
    else:
        ip = cam["ip"]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.6)
        res = s.connect_ex((ip, 554))
        s.close()

        if res != 0:
            return Response("RTSP stream is not currently available for this camera.", status=503)

        resp = Response(
            generate_mjpeg(cam["rtsp"]),
            mimetype="multipart/x-mixed-replace; boundary=frame"
        )

    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

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
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        if os.path.exists(snap_path) and os.path.getsize(snap_path) > 1000:
            return send_file(snap_path, mimetype="image/jpeg", as_attachment=False)
    except:
        pass
    return "Failed to capture snapshot from RTSP feed", 500

@app.route("/api/bridge_status")
def bridge_status():
    """Proxies status from the P2P bridge for the dashboard to poll."""
    try:
        req = urllib.request.Request(f"{P2P_BRIDGE_URL}/status")
        with urllib.request.urlopen(req, timeout=3) as r:
            return Response(r.read(), mimetype="application/json")
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/ptz/<cam_id>")
@app.route("/api/ptz/<cam_id>/<direction>")
def ptz_control(cam_id, direction=None):
    cam = CAMERAS.get(cam_id)
    if not cam or not cam.get("has_ptz"):
        return jsonify({"success": False, "error": "PTZ not supported on this camera"})

    if direction is None:
        direction = request.args.get("dir", "stop").lower()
    else:
        direction = direction.lower()
    speed = float(request.args.get("speed", 0.25))
    duration = float(request.args.get("duration", 0.25))

    if cam.get("type") == "yi_p2p":
        # Proxy PTZ command to P2P bridge
        try:
            ptz_url = f"{P2P_BRIDGE_URL}/{cam_id}/ptz?dir={direction}&speed={speed}&duration={duration}"
            req = urllib.request.Request(ptz_url)
            with urllib.request.urlopen(req, timeout=5) as r:
                result = json.loads(r.read().decode("utf-8"))
                return jsonify(result)
        except Exception as e:
            return jsonify({"success": False, "error": f"P2P PTZ error: {e}"})

    # ONVIF cameras
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
    <title>Surveillance Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-base: #0a0e1a;
            --bg-card: rgba(15, 23, 42, 0.8);
            --accent: #38bdf8;
            --accent-hover: #0284c7;
            --success: #22c55e;
            --warning: #f59e0b;
            --danger: #ef4444;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --border-color: rgba(56, 189, 248, 0.08);
            --radius-card: 16px;
            --radius-btn: 12px;
            --radius-badge: 8px;
            --sidebar-width: 200px;
            --mobile-nav-height: 70px;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }

        body {
            background-color: var(--bg-base);
            color: var(--text-main);
            display: flex;
            height: 100vh;
            overflow: hidden;
        }

        /* SVG Icons */
        .icon {
            width: 24px;
            height: 24px;
            fill: none;
            stroke: currentColor;
            stroke-width: 2;
            stroke-linecap: round;
            stroke-linejoin: round;
        }

        /* Sidebar Desktop */
        .sidebar {
            width: var(--sidebar-width);
            background: var(--bg-card);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border-right: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            padding: 24px 16px;
            gap: 16px;
            z-index: 50;
        }

        .brand {
            font-weight: 700;
            font-size: 1.25rem;
            color: var(--text-main);
            margin-bottom: 24px;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .nav-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 16px;
            border-radius: var(--radius-btn);
            color: var(--text-muted);
            text-decoration: none;
            font-weight: 500;
            transition: all 0.2s;
            cursor: pointer;
            border: 1px solid transparent;
        }

        .nav-item:hover, .nav-item.active {
            background: rgba(56, 189, 248, 0.1);
            color: var(--accent);
            border: 1px solid var(--border-color);
            box-shadow: 0 0 15px rgba(56, 189, 248, 0.15);
        }

        /* Mobile Bottom Nav */
        .mobile-nav {
            display: none;
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            height: var(--mobile-nav-height);
            background: var(--bg-card);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border-top: 1px solid var(--border-color);
            z-index: 100;
            justify-content: space-around;
            align-items: center;
        }

        .mobile-nav-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 4px;
            color: var(--text-muted);
            min-width: 44px;
            min-height: 44px;
            justify-content: center;
            font-size: 0.75rem;
            cursor: pointer;
        }

        .mobile-nav-item.active {
            color: var(--accent);
        }

        /* Main Content */
        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            position: relative;
            scroll-behavior: smooth;
        }

        /* Top Bar */
        .top-bar {
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(10, 14, 26, 0.8);
            backdrop-filter: blur(8px);
            border-bottom: 1px solid var(--border-color);
            position: sticky;
            top: 0;
            z-index: 40;
        }

        .top-title {
            font-size: 1.5rem;
            font-weight: 600;
        }

        .sensitivity-control {
            display: flex;
            align-items: center;
            background: rgba(15, 23, 42, 0.7);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-sm);
            padding: 3px 6px;
            gap: 4px;
        }

        .sens-label {
            font-size: 0.75rem;
            color: var(--text-muted);
            font-weight: 600;
            margin-right: 4px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .sens-btn {
            background: transparent;
            border: 1px solid transparent;
            color: var(--text-muted);
            font-size: 0.75rem;
            font-weight: 500;
            padding: 4px 8px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .sens-btn:hover {
            color: var(--text-main);
            background: rgba(255, 255, 255, 0.05);
        }

        .sens-btn.active {
            color: var(--accent);
            background: rgba(56, 189, 248, 0.12);
            border-color: rgba(56, 189, 248, 0.3);
            font-weight: 600;
        }

        .bridge-status {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.875rem;
            background: rgba(15, 23, 42, 0.6);
            padding: 6px 12px;
            border-radius: var(--radius-badge);
            border: 1px solid var(--border-color);
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--success);
            box-shadow: 0 0 8px var(--success);
        }

        @keyframes pulse {
            0% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.5); opacity: 0.5; }
            100% { transform: scale(1); opacity: 1; }
        }

        .status-dot.pulsing {
            animation: pulse 2s infinite;
        }

        .status-dot.offline {
            background: var(--danger);
            box-shadow: 0 0 8px var(--danger);
            animation: none;
        }

        /* Camera Grid */
        .grid-container {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 24px;
            padding: 24px;
            max-width: 1600px;
            margin: 0 auto;
            width: 100%;
        }

        .cam-card {
            background: var(--bg-card);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-card);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            transition: all 0.3s;
            position: relative;
        }

        .cam-card:hover {
            box-shadow: 0 8px 32px rgba(56, 189, 248, 0.1);
            border-color: rgba(56, 189, 248, 0.2);
        }

        .cam-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 16px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }

        .cam-title {
            font-weight: 600;
            font-size: 1rem;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .badge {
            font-size: 0.75rem;
            padding: 4px 8px;
            border-radius: var(--radius-badge);
            background: rgba(34, 197, 94, 0.1);
            color: var(--success);
            border: 1px solid rgba(34, 197, 94, 0.2);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .cam-video-wrapper {
            position: relative;
            width: 100%;
            aspect-ratio: 16 / 9;
            background: #0a0e1a;
            overflow: hidden;
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .cam-video-wrapper img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            background: #000;
            image-rendering: -webkit-optimize-contrast;
            image-rendering: high-quality;
            display: block;
            position: relative;
            z-index: 2;
        }

        .skeleton-loader {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(90deg, #0a0e1a 25%, #152238 50%, #0a0e1a 75%);
            background-size: 200% 100%;
            animation: skeleton-loading 1.5s infinite;
            z-index: 1;
            display: flex;
            justify-content: center;
            align-items: center;
            flex-direction: column;
            gap: 12px;
            color: var(--text-muted);
            pointer-events: none;
            transition: opacity 0.3s;
        }

        @keyframes skeleton-loading {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }

        .cam-footer {
            padding: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
        }
        
        .cam-actions {
            display: flex;
            gap: 8px;
        }

        .btn-icon {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: var(--text-main);
            border-radius: var(--radius-btn);
            width: 40px;
            height: 40px;
            display: flex;
            justify-content: center;
            align-items: center;
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-icon:hover {
            background: rgba(56, 189, 248, 0.1);
            color: var(--accent);
            border-color: var(--accent);
        }

        /* PTZ Controls */
        .ptz-container {
            position: relative;
            width: 90px;
            height: 90px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border-color);
        }

        .ptz-btn {
            position: absolute;
            background: transparent;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            width: 30px;
            height: 30px;
            display: flex;
            justify-content: center;
            align-items: center;
            transition: all 0.2s;
            border-radius: 50%;
        }

        .ptz-btn:hover {
            color: var(--accent);
            background: rgba(56, 189, 248, 0.1);
        }

        .ptz-btn svg {
            width: 16px;
            height: 16px;
            pointer-events: none;
        }

        .ptz-btn:active, .ptz-btn.active-ptz {
            color: var(--accent);
            background: rgba(56, 189, 248, 0.25);
            transform: scale(0.9);
        }

        .ptz-up { top: 0; left: 30px; }
        .ptz-down { bottom: 0; left: 30px; }
        .ptz-left { top: 30px; left: 0; }
        .ptz-right { top: 30px; right: 0; }
        .ptz-stop {
            top: 30px;
            left: 30px;
            background: rgba(255, 255, 255, 0.1);
        }
        .ptz-stop:hover {
            background: rgba(239, 68, 68, 0.2);
            color: var(--danger);
        }
        .ptz-stop svg {
            width: 12px;
            height: 12px;
            fill: currentColor;
            stroke: none;
        }

        /* Recordings Section */
        .recordings-section {
            padding: 24px;
            max-width: 1600px;
            margin: 0 auto;
            width: 100%;
        }

        .recordings-panel {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-card);
            padding: 24px;
            backdrop-filter: blur(12px);
        }

        .recordings-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }

        .select-styled {
            background: rgba(10, 14, 26, 0.8);
            color: var(--text-main);
            border: 1px solid var(--border-color);
            padding: 10px 16px;
            border-radius: var(--radius-btn);
            font-size: 0.9rem;
            outline: none;
            cursor: pointer;
            appearance: none;
            min-width: 150px;
        }

        .btn {
            background: var(--accent);
            color: #000;
            border: none;
            padding: 10px 20px;
            border-radius: var(--radius-btn);
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .btn:hover {
            background: var(--accent-hover);
            transform: translateY(-1px);
        }

        .btn-outline {
            background: transparent;
            color: var(--text-main);
            border: 1px solid var(--border-color);
        }

        .btn-outline:hover {
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-main);
        }

        .rec-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 24px;
        }

        .video-player-container {
            background: #000;
            border-radius: var(--radius-btn);
            overflow: hidden;
            aspect-ratio: 16/9;
            border: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
        }

        video {
            width: 100%;
            height: 100%;
            background: #000;
        }

        .clips-list {
            background: rgba(0,0,0,0.2);
            border-radius: var(--radius-btn);
            border: 1px solid var(--border-color);
            overflow-y: auto;
            max-height: 500px;
        }

        .clip-item {
            padding: 12px 16px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            cursor: pointer;
            transition: background 0.2s;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .clip-item:hover, .clip-item.active {
            background: rgba(56, 189, 248, 0.1);
        }

        /* Toast Notifications */
        .toast-container {
            position: fixed;
            bottom: 24px;
            right: 24px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            z-index: 9999;
        }

        .toast {
            background: var(--bg-card);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 16px 20px;
            border-radius: var(--radius-btn);
            box-shadow: 0 10px 40px rgba(0,0,0,0.5);
            display: flex;
            align-items: center;
            gap: 12px;
            transform: translateY(100%);
            opacity: 0;
            transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }

        .toast.show {
            transform: translateY(0);
            opacity: 1;
        }

        .toast-icon {
            color: var(--accent);
        }

        /* Responsive */
        @media (max-width: 768px) {
            .sidebar { display: none; }
            .mobile-nav { display: flex; }
            .main-content { margin-bottom: var(--mobile-nav-height); }
            .grid-container { grid-template-columns: 1fr; padding: 16px; }
            .rec-grid { grid-template-columns: 1fr; }
            .clips-list { max-height: 300px; }
        }

        /* Fullscreen Video Fixes */
        .cam-card:-webkit-full-screen {
            width: 100vw;
            height: 100vh;
            border: none;
            border-radius: 0;
            display: flex;
            flex-direction: column;
            justify-content: center;
            background: #000;
        }
        .cam-card:fullscreen {
            width: 100vw;
            height: 100vh;
            border: none;
            border-radius: 0;
            display: flex;
            flex-direction: column;
            justify-content: center;
            background: #000;
        }
        .cam-card:fullscreen .cam-video-wrapper {
            height: 100%;
        }
        .cam-card:fullscreen .cam-header,
        .cam-card:fullscreen .cam-footer {
            position: absolute;
            z-index: 10;
            width: 100%;
            background: rgba(0,0,0,0.5);
            opacity: 0;
            transition: opacity 0.3s;
        }
        .cam-card:fullscreen:hover .cam-header,
        .cam-card:fullscreen:hover .cam-footer {
            opacity: 1;
        }
        .cam-card:fullscreen .cam-footer {
            bottom: 0;
        }
    </style>
</head>
<body>
    <!-- Desktop Sidebar -->
    <aside class="sidebar">
        <div class="brand">
            <svg class="icon" viewBox="0 0 24 24"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg>
            Surveillance
        </div>
        <a href="#live" class="nav-item active" onclick="switchTab('live')">
            <svg class="icon" viewBox="0 0 24 24"><path d="M15.6 11.6L22 7v10l-6.4-4.5v-1zM4 5h9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7c0-1.1.9-2 2-2z"></path></svg>
            Live View
        </a>
        <a href="#recordings" class="nav-item" onclick="switchTab('recordings')">
            <svg class="icon" viewBox="0 0 24 24"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg>
            Recordings
        </a>
        <a href="#settings" class="nav-item" onclick="switchTab('settings')">
            <svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
            Settings
        </a>
    </aside>

    <!-- Mobile Bottom Nav -->
    <nav class="mobile-nav">
        <div class="mobile-nav-item active" onclick="switchTab('live')" id="mob-live">
            <svg class="icon" viewBox="0 0 24 24"><path d="M15.6 11.6L22 7v10l-6.4-4.5v-1zM4 5h9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7c0-1.1.9-2 2-2z"></path></svg>
            <span>Live</span>
        </div>
        <div class="mobile-nav-item" onclick="switchTab('recordings')" id="mob-recordings">
            <svg class="icon" viewBox="0 0 24 24"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg>
            <span>Clips</span>
        </div>
        <div class="mobile-nav-item" onclick="switchTab('settings')" id="mob-settings">
            <svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
            <span>Config</span>
        </div>
    </nav>

    <main class="main-content">
        <div class="top-bar">
            <div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap;">
                <div class="top-title" id="page-title">Live Overview</div>
                <div class="sensitivity-control" title="PTZ Step Sensitivity">
                    <span class="sens-label">PTZ Step:</span>
                    <button type="button" class="sens-btn active" id="sens-micro" onclick="setSensitivity('micro')">Micro (Nudge)</button>
                    <button type="button" class="sens-btn" id="sens-normal" onclick="setSensitivity('normal')">Normal</button>
                    <button type="button" class="sens-btn" id="sens-sweep" onclick="setSensitivity('sweep')">Sweep</button>
                </div>
            </div>
            <div class="bridge-status" id="bridge-status" title="P2P Bridge Status">
                <div class="status-dot pulsing" id="bridge-dot"></div>
                <span id="bridge-text">Checking P2P Bridge...</span>
            </div>
        </div>

        <!-- Live View Section -->
        <div id="live-section" class="grid-container">
            {% for cam_id, cam in cameras.items() %}
            <div class="cam-card" id="card-{{ cam_id }}">
                <div class="cam-header">
                    <div class="cam-title">
                        <svg class="icon" viewBox="0 0 24 24" style="width:18px;height:18px;color:var(--accent);"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg>
                        {{ cam.name }}
                    </div>
                    <div class="badge">ONLINE</div>
                </div>
                
                <div class="cam-video-wrapper">
                    <div class="skeleton-loader" id="loader-{{ cam_id }}">
                        <svg class="icon" viewBox="0 0 24 24" style="width:32px;height:32px;animation: pulse 2s infinite;"><path d="M15.6 11.6L22 7v10l-6.4-4.5v-1zM4 5h9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7c0-1.1.9-2 2-2z"></path></svg>
                        <span id="loader-txt-{{ cam_id }}">Connecting feed...</span>
                    </div>
                    <img src="/stream/{{ cam_id }}" id="feed-{{ cam_id }}" onload="onFeedLoaded('{{ cam_id }}')" onerror="onFeedError('{{ cam_id }}')" alt="Feed {{ cam.name }}">
                </div>

                <div class="cam-footer">
                    {% if cam.has_ptz %}
                    <div class="ptz-container">
                        <button class="ptz-btn ptz-up" onclick="movePTZ('{{ cam_id }}', 'up')" aria-label="Pan Up">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"></polyline></svg>
                        </button>
                        <button class="ptz-btn ptz-down" onclick="movePTZ('{{ cam_id }}', 'down')" aria-label="Pan Down">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                        </button>
                        <button class="ptz-btn ptz-left" onclick="movePTZ('{{ cam_id }}', 'left')" aria-label="Pan Left">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>
                        </button>
                        <button class="ptz-btn ptz-right" onclick="movePTZ('{{ cam_id }}', 'right')" aria-label="Pan Right">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
                        </button>
                        <button class="ptz-btn ptz-stop" onclick="movePTZ('{{ cam_id }}', 'stop')" aria-label="Stop PTZ">
                            <svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12"></rect></svg>
                        </button>
                    </div>
                    {% else %}
                    <div style="width: 90px; color: var(--text-muted); font-size: 0.8rem; text-align: center;">Fixed Lens</div>
                    {% endif %}

                    <div class="cam-actions">
                        <button class="btn-icon" onclick="launch('{{ cam_id }}')" title="Open Native Stream" aria-label="Open Stream">
                            <svg class="icon" viewBox="0 0 24 24"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                        </button>
                        <a href="/snapshot/{{ cam_id }}" download="snapshot_{{ cam_id }}.jpg" class="btn-icon" title="Save Snapshot" aria-label="Save Snapshot">
                            <svg class="icon" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                        </a>
                        <button class="btn-icon" onclick="toggleFullscreen('card-{{ cam_id }}')" title="Fullscreen" aria-label="Toggle Fullscreen">
                            <svg class="icon" viewBox="0 0 24 24"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg>
                        </button>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>

        <!-- Recordings Section -->
        <div id="recordings-section" class="recordings-section" style="display: none;">
            <div class="recordings-panel">
                <div class="recordings-header">
                    <h2 style="font-size: 1.25rem; font-weight: 600;">SD Card Archives</h2>
                    <div style="display: flex; gap: 12px; align-items: center;">
                        <select id="rec-cam-select" class="select-styled" onchange="loadRecordings()">
                            <option value="">-- All Cameras --</option>
                            {% for cam_id, cam in cameras.items() %}
                                <option value="{{ cam_id }}">{{ cam.name }}</option>
                            {% endfor %}
                        </select>
                        <button class="btn btn-outline" onclick="loadRecordings()">
                            <svg class="icon" viewBox="0 0 24 24" style="width: 16px; height: 16px;"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>
                            Refresh
                        </button>
                        <button class="btn" onclick="openSelectedInVLC()" id="btn-vlc" disabled>
                            <svg class="icon" viewBox="0 0 24 24" style="width: 16px; height: 16px;"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                            Play in VLC
                        </button>
                    </div>
                </div>
                
                <div class="rec-grid">
                    <div class="video-player-container">
                        <video id="web-player" controls preload="none">
                            <source src="" type="video/mp4">
                            Your browser does not support HTML5 video.
                        </video>
                    </div>
                    <div class="clips-list" id="clips-list">
                        <div style="padding: 24px; text-align: center; color: var(--text-muted);">
                            Loading clips...
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Settings Section -->
        <div id="settings-section" class="recordings-section" style="display: none;">
            <div class="recordings-panel">
                <h2 style="font-size: 1.25rem; font-weight: 600; margin-bottom: 20px;">System Configuration</h2>
                <p style="color: var(--text-muted);">Configuration options and system diagnostics will appear here.</p>
                <div style="margin-top: 24px; padding: 16px; background: rgba(0,0,0,0.2); border-radius: 8px; border: 1px solid var(--border-color);">
                    <h3 style="font-size: 1rem; margin-bottom: 12px; color: var(--text-main);">Keyboard Shortcuts</h3>
                    <ul style="color: var(--text-muted); list-style: none; display: flex; flex-direction: column; gap: 8px;">
                        <li><kbd style="background: var(--bg-primary); padding: 2px 6px; border-radius: 4px; border: 1px solid var(--border-color);">1-4</kbd> : Focus/Fullscreen Camera 1-4</li>
                        <li><kbd style="background: var(--bg-primary); padding: 2px 6px; border-radius: 4px; border: 1px solid var(--border-color);">Arrow Keys</kbd> : PTZ Control for hovered camera</li>
                        <li><kbd style="background: var(--bg-primary); padding: 2px 6px; border-radius: 4px; border: 1px solid var(--border-color);">Esc</kbd> : Exit Fullscreen</li>
                    </ul>
                </div>
            </div>
        </div>
    </main>

    <!-- Toasts -->
    <div class="toast-container" id="toast-container"></div>

    <script>
        let selectedClipUrl = "";
        let selectedClipPath = "";
        
        // Navigation
        function switchTab(tabId) {
            document.getElementById('live-section').style.display = 'none';
            document.getElementById('recordings-section').style.display = 'none';
            document.getElementById('settings-section').style.display = 'none';
            
            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.mobile-nav-item').forEach(el => el.classList.remove('active'));
            
            document.getElementById(tabId + '-section').style.display = tabId === 'live' ? 'grid' : 'block';
            
            // Update active states based on href matching
            const dnav = document.querySelector(`.nav-item[href="#${tabId}"]`);
            if(dnav) dnav.classList.add('active');
            
            const mnav = document.getElementById(`mob-${tabId}`);
            if(mnav) mnav.classList.add('active');

            const titles = {
                'live': 'Live Overview',
                'recordings': 'Video Archives',
                'settings': 'System Settings'
            };
            document.getElementById('page-title').innerText = titles[tabId];
            
            if(tabId === 'recordings' && !document.getElementById('clips-list').querySelector('.clip-item')) {
                loadRecordings();
            }
        }

        function showToast(message, type="info") {
            const container = document.getElementById("toast-container");
            const toast = document.createElement("div");
            toast.className = "toast";
            
            let iconSvg = '<svg class="icon toast-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';
            if(type === "error") {
                iconSvg = '<svg class="icon toast-icon" style="color:var(--danger)" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>';
            } else if (type === "success") {
                iconSvg = '<svg class="icon toast-icon" style="color:var(--success)" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>';
            }
            
            toast.innerHTML = iconSvg + `<span>${message}</span>`;
            container.appendChild(toast);
            
            // trigger reflow
            void toast.offsetWidth;
            toast.classList.add("show");
            
            setTimeout(() => {
                toast.classList.remove("show");
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        }

        // Feed Lifecycle & Auto-Reconnect
        function onFeedLoaded(cam_id) {
            const loader = document.getElementById('loader-' + cam_id);
            if (loader) loader.style.display = 'none';
        }

        function monitorFeeds() {
            ['cam1', 'cam2', 'cam3', 'cam4'].forEach(id => {
                const img = document.getElementById('feed-' + id);
                const loader = document.getElementById('loader-' + id);
                if (img && loader) {
                    if (img.naturalWidth > 0 && loader.style.display !== 'none') {
                        loader.style.display = 'none';
                    }
                }
            });
        }
        setInterval(monitorFeeds, 300);

        function onFeedError(cam_id) {
            const loader = document.getElementById('loader-' + cam_id);
            const txt = document.getElementById('loader-txt-' + cam_id);
            if (loader) {
                loader.style.display = 'flex';
                if (txt) txt.textContent = 'Connecting...';
            }
            setTimeout(() => {
                const img = document.getElementById('feed-' + cam_id);
                if (img) {
                    img.src = '/stream/' + cam_id + '?t=' + Date.now();
                }
            }, 3000);
        }

        let ptzSensitivity = localStorage.getItem('ptzSensitivity') || 'micro';

        function setSensitivity(level) {
            ptzSensitivity = level;
            try { localStorage.setItem('ptzSensitivity', level); } catch(e) {}
            document.querySelectorAll('.sens-btn').forEach(btn => btn.classList.remove('active'));
            const activeBtn = document.getElementById('sens-' + level);
            if (activeBtn) activeBtn.classList.add('active');
            showToast('PTZ Step: ' + level.toUpperCase(), 'info');
        }

        document.addEventListener('DOMContentLoaded', () => {
            const activeBtn = document.getElementById('sens-' + ptzSensitivity);
            if (activeBtn) {
                document.querySelectorAll('.sens-btn').forEach(btn => btn.classList.remove('active'));
                activeBtn.classList.add('active');
            }
        });

        // PTZ and Streams
        function movePTZ(cam_id, direction) {
            const isP2P = (cam_id === 'cam3' || cam_id === 'cam4');
            let speed, duration;

            if (direction === 'stop') {
                speed = 0.0;
                duration = 0.0;
            } else if (isP2P) {
                // P2P cameras (cam3, cam4): speed=0 (calibrated default), duration controls the step
                speed = 0;
                if (ptzSensitivity === 'micro') {
                    duration = 0.50;
                } else if (ptzSensitivity === 'sweep') {
                    duration = 1.60;
                } else {
                    duration = 0.90;
                }
            } else {
                // Calibrated ONVIF sensitivity (cam1, cam2): micro-nudge by default
                if (ptzSensitivity === 'micro') {
                    speed = 0.18;
                    duration = 0.20;
                } else if (ptzSensitivity === 'sweep') {
                    speed = 0.50;
                    duration = 0.60;
                } else {
                    speed = 0.25;
                    duration = 0.30;
                }
            }

            // Highlight clicked button
            const card = document.getElementById('card-' + cam_id);
            if (card) {
                const btn = card.querySelector('.ptz-' + direction);
                if (btn) {
                    btn.classList.add('active-ptz');
                    setTimeout(() => btn.classList.remove('active-ptz'), 400);
                }
            }

            fetch('/api/ptz/' + cam_id + '?dir=' + direction + '&speed=' + speed + '&duration=' + duration)
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        const dirLabel = direction.toUpperCase();
                        showToast(cam_id.toUpperCase() + ': ' + dirLabel, 'success');
                    } else {
                        showToast(data.error || 'PTZ Error', 'error');
                    }
                })
                .catch(err => showToast('PTZ Network error: ' + err, 'error'));
        }

        function launch(cam_id) {
            fetch(`/api/launch_player?cam_id=${cam_id}&player=vlc`)
                .then(res => res.json())
                .then(data => {
                    if(data.success) {
                        showToast(`Opened ${cam_id} stream in VLC`, "success");
                    } else {
                        showToast(`Failed: ${data.error}`, "error");
                    }
                })
                .catch(err => showToast("Network error: " + err, "error"));
        }

        // Fullscreen API
        function toggleFullscreen(cardId) {
            const el = document.getElementById(cardId);
            if (!document.fullscreenElement) {
                if (el.requestFullscreen) {
                    el.requestFullscreen().catch(err => showToast(`Fullscreen error: ${err.message}`, "error"));
                } else if (el.webkitRequestFullscreen) {
                    el.webkitRequestFullscreen();
                } else if (el.msRequestFullscreen) {
                    el.msRequestFullscreen();
                }
            } else {
                if (document.exitFullscreen) {
                    document.exitFullscreen();
                } else if (document.webkitExitFullscreen) {
                    document.webkitExitFullscreen();
                } else if (document.msExitFullscreen) {
                    document.msExitFullscreen();
                }
            }
        }

        // Recordings
        let loadedClips = [];

        function loadRecordings() {
            const listContainer = document.getElementById("clips-list");
            listContainer.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-muted);">Loading recordings...</div>';
            
            fetch('/api/records')
                .then(res => res.json())
                .then(data => {
                    if(!data.success) {
                        listContainer.innerHTML = `<div style="padding: 24px; color: var(--danger);">${data.error || 'Failed to load'}</div>`;
                        return;
                    }
                    
                    if(!data.clips || data.clips.length === 0) {
                        listContainer.innerHTML = `<div style="padding: 24px; text-align: center; color: var(--text-muted);">No recordings found on local drives</div>`;
                        return;
                    }

                    loadedClips = data.clips;
                    let html = '';
                    data.clips.forEach((clip, index) => {
                        html += `
                        <div class="clip-item" id="clip-${index}" onclick="selectClip(${index})">
                            <svg class="icon" viewBox="0 0 24 24" style="min-width: 24px;"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                            <div style="overflow: hidden;">
                                <div style="font-weight: 500; font-size: 0.9rem; text-overflow: ellipsis; white-space: nowrap; overflow: hidden;">${clip.filename}</div>
                                <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 2px;">
                                    ${clip.size_mb} MB &bull; ${clip.date}
                                </div>
                            </div>
                        </div>`;
                    });
                    listContainer.innerHTML = html;
                })
                .catch(err => {
                    listContainer.innerHTML = `<div style="padding: 24px; color: var(--danger);">Failed to load clips</div>`;
                    showToast("Error loading recordings", "error");
                });
        }

        function selectClip(index) {
            const clip = loadedClips[index];
            if (!clip) return;
            document.querySelectorAll('.clip-item').forEach(el => el.classList.remove('active'));
            const item = document.getElementById(`clip-${index}`);
            if (item) item.classList.add('active');
            
            selectedClipUrl = `/api/records/play?file=${encodeURIComponent(clip.path)}`;
            selectedClipPath = clip.path;
            const btnVlc = document.getElementById("btn-vlc");
            if (btnVlc) btnVlc.disabled = false;
            
            const player = document.getElementById("web-player");
            if (player) {
                player.src = selectedClipUrl;
                player.play().catch(e => {
                    showToast("Browser playback format unsupported; click 'Play in VLC'", "warning");
                });
            }
        }

        function openSelectedInVLC() {
            if(!selectedClipPath) return;
            fetch(`/api/records/open_vlc?file=${encodeURIComponent(selectedClipPath)}`)
                .then(res => res.json())
                .then(data => {
                    if(data.success) {
                        showToast("Clip opened in VLC", "success");
                    } else {
                        showToast("Failed to open VLC: " + data.error, "error");
                    }
                })
                .catch(err => showToast("Network error", "error"));
        }

        // Bridge Status Polling
        function checkBridgeStatus() {
            fetch('/api/bridge_status')
                .then(res => {
                    if(!res.ok) throw new Error("HTTP error");
                    return res.json();
                })
                .then(data => {
                    const dot = document.getElementById('bridge-dot');
                    const txt = document.getElementById('bridge-text');
                    let anyOnline = false;
                    for (const [camId, info] of Object.entries(data)) {
                        const card = document.getElementById(`card-${camId}`);
                        if (card) {
                            const badge = card.querySelector('.badge');
                            if (badge) {
                                if (info.online) {
                                    badge.textContent = info.fps > 0 ? `ONLINE (${info.fps.toFixed(1)} FPS)` : 'CONNECTED (P2P)';
                                    badge.style.color = 'var(--success)';
                                    badge.style.borderColor = 'rgba(34, 197, 94, 0.3)';
                                } else {
                                    badge.textContent = 'CONNECTING';
                                    badge.style.color = 'var(--warning)';
                                    badge.style.borderColor = 'rgba(245, 158, 11, 0.3)';
                                }
                            }
                        }
                        if (info.online) anyOnline = true;
                    }
                    if (anyOnline) {
                        if (dot) dot.className = 'status-dot pulsing';
                        if (txt) txt.innerText = 'P2P Bridge Active';
                    } else if (Object.keys(data).length > 0) {
                        if (dot) dot.className = 'status-dot';
                        if (txt) txt.innerText = 'P2P Bridge Connecting...';
                    } else {
                        if (dot) dot.className = 'status-dot offline';
                        if (txt) txt.innerText = 'P2P Bridge Offline';
                    }
                })
                .catch(err => {
                    const dot = document.getElementById('bridge-dot');
                    const txt = document.getElementById('bridge-text');
                    if (dot) dot.className = 'status-dot offline';
                    if (txt) txt.innerText = 'Bridge Unreachable';
                });
        }
        
        setInterval(checkBridgeStatus, 5000);
        setTimeout(checkBridgeStatus, 1000);
        setTimeout(checkBridgeStatus, 1000); // Initial check

        // Keyboard Shortcuts
        document.addEventListener('keydown', function(e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
            
            // 1-4 for camera focus
            if (e.key >= '1' && e.key <= '4') {
                const camId = `cam${e.key}`;
                const card = document.getElementById(`card-${camId}`);
                if (card) {
                    toggleFullscreen(`card-${camId}`);
                }
            }
        });
        
        // Track hovered camera for PTZ keyboard control
        let hoveredCam = null;
        document.querySelectorAll('.cam-card').forEach(card => {
            card.addEventListener('mouseenter', () => {
                hoveredCam = card.id.replace('card-', '');
            });
            card.addEventListener('mouseleave', () => {
                hoveredCam = null;
            });
        });

        document.addEventListener('keydown', function(e) {
            if(!hoveredCam) return;
            const arrows = {
                'ArrowUp': 'up',
                'ArrowDown': 'down',
                'ArrowLeft': 'left',
                'ArrowRight': 'right'
            };
            
            if(arrows[e.key]) {
                e.preventDefault();
                movePTZ(hoveredCam, arrows[e.key]);
            }
        });
        
        // Auto-resync video streams on tab visibility to eliminate lag
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                ['cam1', 'cam2', 'cam3', 'cam4'].forEach(id => {
                    const img = document.getElementById('feed-' + id);
                    if (img) {
                        const base = img.src.split('?')[0];
                        img.src = base + '?t=' + Date.now();
                    }
                });
            }
        });

    </script>
</body>
</html>
"""

MEDIAMTX_DIR = r'C:\Users\CHRISTOPHER\Downloads\mediamtx'
MEDIAMTX_EXE = os.path.join(MEDIAMTX_DIR, 'mediamtx.exe')

def ensure_mediamtx():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(('127.0.0.1', 8554))
        s.close()
        return
    except:
        pass
    if os.path.exists(MEDIAMTX_EXE):
        print("[MediaMTX] Starting RTSP server on :8554...")
        subprocess.Popen([MEDIAMTX_EXE], cwd=MEDIAMTX_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)

if __name__ == "__main__":
    ensure_mediamtx()
    try:
        import onvif_bridge
        onvif_bridge.start_onvif_bridge("cam3", 8898)
        onvif_bridge.start_onvif_bridge("cam4", 8897)
        print("[ONVIF Bridge] Native ONVIF PTZ bridges started on ports 8898 (cam3) and 8897 (cam4)")
    except Exception as e:
        print(f"[ONVIF Bridge] Could not start ONVIF bridge: {e}")

    port = int(os.environ.get("PORT", 8080))
    print("=" * 60)
    print(f"Local Camera Hub starting on port {port}")
    print("Direct RTSP feeds + PTZ Motors + SD Card Video Browser")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


