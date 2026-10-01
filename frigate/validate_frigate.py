import yaml
import socket
import urllib.request

CONFIG_PATH = r"C:\Users\CHRISTOPHER\Downloads\LocalCameraHub\frigate\config.yml"

print("=" * 60)
print("FRIGATE CONFIGURATION VALIDATION")
print("=" * 60)

with open(CONFIG_PATH, "r") as f:
    cfg = yaml.safe_load(f)

print("[OK] YAML Syntax: Valid")
print("[OK] Detectors:", cfg.get("detectors"))
print("[OK] go2rtc streams:", list(cfg.get("go2rtc", {}).get("streams", {}).keys()))

print("\n--- Verifying Camera Inputs & ONVIF PTZ Endpoints ---")
for cam, details in cfg.get("cameras", {}).items():
    stream_url = details.get("ffmpeg", {}).get("inputs", [{}])[0].get("path")
    onvif_cfg = details.get("onvif", {})
    onvif_host = onvif_cfg.get("host")
    onvif_port = onvif_cfg.get("port")

    # Test RTSP Port
    rtsp_host = stream_url.split("//")[1].split(":")[0]
    rtsp_port = int(stream_url.split(":")[2].split("/")[0])
    s = socket.socket()
    s.settimeout(1.5)
    rtsp_ok = (s.connect_ex((rtsp_host, rtsp_port)) == 0)
    s.close()

    # Test ONVIF Port
    s2 = socket.socket()
    s2.settimeout(1.5)
    onvif_ok = (s2.connect_ex((onvif_host, onvif_port)) == 0)
    s2.close()

    print(f"\nCamera: {cam}")
    print(f"  Stream: {stream_url} => Port {rtsp_port} {'[OPEN]' if rtsp_ok else '[FAILED]'}")
    print(f"  ONVIF : {onvif_host}:{onvif_port} => {'[OPEN - PTZ READY]' if onvif_ok else '[FAILED]'}")

print("\n" + "=" * 60)
