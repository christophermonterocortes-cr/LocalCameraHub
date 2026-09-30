import os
import ctypes
import json
import time
import struct
import random
import hashlib
import hmac
import base64
import subprocess
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

DLL_PATH = r'C:\Users\CHRISTOPHER\Downloads\YI_IOT_APP\PPPP_API.dll'
CRYPTO_PATH = r'C:\Users\CHRISTOPHER\Downloads\YI_IOT_APP\libcrypto-1_1.dll'
FFMPEG_PATH = r'C:\Users\CHRISTOPHER\Downloads\ffmpeg.exe'
CONFIG_PATH = r'C:\Users\CHRISTOPHER\Downloads\cameras_p2p_config.json'
PLACEHOLDER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "placeholder.jpg")

cdll = ctypes.CDLL(DLL_PATH)
crypto = ctypes.CDLL(CRYPTO_PATH)

class AES_KEY(ctypes.Structure):
    _fields_ = [("rd_key", ctypes.c_uint32 * 60), ("rounds", ctypes.c_int)]

crypto.AES_set_decrypt_key.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(AES_KEY)]
crypto.AES_set_decrypt_key.restype = ctypes.c_int
crypto.AES_ecb_encrypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(AES_KEY), ctypes.c_int]
crypto.AES_ecb_encrypt.restype = None

cdll.PPPP_Initialize.argtypes = [ctypes.c_char_p, ctypes.c_int]
cdll.PPPP_Initialize.restype = ctypes.c_int
cdll.PPPP_WakeUp_And_Connect.argtypes = [ctypes.c_char_p, ctypes.c_byte, ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p]
cdll.PPPP_WakeUp_And_Connect.restype = ctypes.c_int
cdll.PPPP_Read.argtypes = [ctypes.c_int, ctypes.c_byte, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int), ctypes.c_int]
cdll.PPPP_Read.restype = ctypes.c_int
cdll.PPPP_Write.argtypes = [ctypes.c_int, ctypes.c_byte, ctypes.c_char_p, ctypes.c_int]
cdll.PPPP_Write.restype = ctypes.c_int
cdll.PPPP_Close.argtypes = [ctypes.c_int]
cdll.PPPP_Close.restype = ctypes.c_int
cdll.PPPP_DeInitialize.argtypes = []
cdll.PPPP_DeInitialize.restype = ctypes.c_int

cdll.PPPP_Initialize(b'\x00', 12)

class YiCameraStreamer:
    def __init__(self, cam_id, config):
        self.cam_id = cam_id
        self.config = config
        self.name = config.get("name", cam_id)
        self.uid = config["uid"]
        self.pwd = config["password"]
        self.init_str = config["init_string"]
        self.license = config["license"]
        self.running = True
        self.online = False
        self.latest_frame = None
        self.frame_count = 0
        self.fps = 0.0
        self.last_frame_time = 0
        self.sid = -1
        self.auth_bytes = None
        self.cond = threading.Condition()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        buf = ctypes.create_string_buffer(1048576)
        aes_key = AES_KEY()
        crypto.AES_set_decrypt_key((self.pwd + "0").encode('ascii'), 128, ctypes.byref(aes_key))
        dec_buf = ctypes.create_string_buffer(16)

        while self.running:
            self.online = False
            sid = -1
            print(f"[{self.cam_id}] Connecting to {self.name} ({self.uid})...")
            for attempt in range(5):
                if not self.running:
                    return
                sid = cdll.PPPP_WakeUp_And_Connect(
                    self.uid.encode('ascii'),
                    ctypes.c_byte(75),
                    0,
                    self.init_str.encode('ascii'),
                    self.license.encode('ascii')
                )
                if sid >= 0:
                    break
                wait_time = 8 if sid == -3006 else 3
                print(f"[{self.cam_id}] Connect attempt {attempt+1} got sid {sid}, retrying in {wait_time}s...")
                time.sleep(wait_time)

            if sid < 0:
                cooldown = 12 if sid == -3006 else 5
                print(f"[{self.cam_id}] Connection failed. Retrying in {cooldown}s...")
                time.sleep(cooldown)
                continue

            print(f"[{self.cam_id}] Session established (SID={sid}). Starting video...")
            self.sid = sid

            chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
            nonce = "".join(random.choice(chars) for _ in range(15))
            str_to_hash = f"user=xiaoyiuser&nonce={nonce}"
            sig = base64.b64encode(hmac.new(self.pwd.encode('utf-8'), str_to_hash.encode('utf-8'), hashlib.sha1).digest()).decode('ascii')
            if len(sig) > 15:
                sig = sig[:15]
            auth_str = f"{nonce},{sig}"
            auth_bytes = auth_str.encode('ascii').ljust(32, b'\x00')
            self.auth_bytes = auth_bytes

            payload = bytes([1, 1, 1, 0])
            hdr = struct.pack('>BBHI', 1, 3, 0, 40 + len(payload))
            cmd_hdr = struct.pack('>HHHH', 9029, 1, 0, len(payload)) + auth_bytes
            full_packet = hdr + cmd_hdr + payload
            cdll.PPPP_Write(sid, ctypes.c_byte(0), full_packet, len(full_packet))

            ffmpeg_cmd = [
                FFMPEG_PATH,
                '-y',
                '-loglevel', 'error',
                '-fflags', 'nobuffer',
                '-flags', 'low_delay',
                '-probesize', '32',
                '-analyzeduration', '0',
                '-f', 'h264',
                '-i', 'pipe:0',
                '-f', 'image2pipe',
                '-vcodec', 'mjpeg',
                '-q:v', '5',
                'pipe:1'
            ]
            try:
                proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except Exception as e:
                print(f"[{self.cam_id}] Failed to start FFmpeg: {e}")
                cdll.PPPP_Close(sid)
                time.sleep(3)
                continue

            def ffmpeg_reader():
                f_buf = b''
                last_fps_calc = time.time()
                frames_in_period = 0
                while self.running and proc.poll() is None:
                    try:
                        chunk = proc.stdout.read(4096)
                        if not chunk:
                            break
                        f_buf += chunk
                        while True:
                            s = f_buf.find(b'\xff\xd8')
                            if s == -1:
                                f_buf = b''
                                break
                            e = f_buf.find(b'\xff\xd9', s + 2)
                            if e == -1:
                                f_buf = f_buf[s:]
                                break
                            jpg = f_buf[s:e+2]
                            f_buf = f_buf[e+2:]
                            
                            with self.cond:
                                self.latest_frame = jpg
                                self.frame_count += 1
                                self.last_frame_time = time.time()
                                self.online = True
                                self.cond.notify_all()

                            frames_in_period += 1
                            now = time.time()
                            if now - last_fps_calc >= 2.0:
                                self.fps = round(frames_in_period / (now - last_fps_calc), 1)
                                frames_in_period = 0
                                last_fps_calc = now
                    except Exception:
                        break

            reader_thread = threading.Thread(target=ffmpeg_reader, daemon=True)
            reader_thread.start()

            ffmpeg_lock = threading.Lock()
            session_active = threading.Event()
            session_active.set()
            last_frame_rx = [time.time()]

            def channel_reader(ch_num):
                ch_buf = ctypes.create_string_buffer(1048576)
                ch_dec = ctypes.create_string_buffer(16)
                while self.running and session_active.is_set():
                    hdr_len = ctypes.c_int(8)
                    ret = cdll.PPPP_Read(sid, ctypes.c_byte(ch_num), ch_buf, ctypes.byref(hdr_len), 1500)
                    if ret >= 0 and hdr_len.value >= 8:
                        body_len = struct.unpack_from('>I', ch_buf.raw, 4)[0]
                        if 0 < body_len <= 1048576:
                            b_len = ctypes.c_int(body_len)
                            ret2 = cdll.PPPP_Read(sid, ctypes.c_byte(ch_num), ch_buf, ctypes.byref(b_len), 1500)
                            if ret2 >= 0 and b_len.value > 24:
                                raw_frame = bytearray(ch_buf.raw[:b_len.value])
                                if raw_frame[2] & 1:
                                    crypto.AES_ecb_encrypt(bytes(raw_frame[28:44]), ch_dec, ctypes.byref(aes_key), 0)
                                    raw_frame[28:44] = ch_dec.raw
                                    crypto.AES_ecb_encrypt(bytes(raw_frame[44:60]), ch_dec, ctypes.byref(aes_key), 0)
                                    raw_frame[44:60] = ch_dec.raw
                                
                                h264_nal = bytes(raw_frame[24:])
                                try:
                                    with ffmpeg_lock:
                                        proc.stdin.write(h264_nal)
                                        proc.stdin.flush()
                                    last_frame_rx[0] = time.time()
                                except (BrokenPipeError, OSError):
                                    session_active.clear()
                                    break
                    elif ret < 0 and ret != -3003:
                        if ret in (-3012, -3006, -3001):
                            session_active.clear()
                            break

            ch2_t = threading.Thread(target=channel_reader, args=(2,), daemon=True)
            ch3_t = threading.Thread(target=channel_reader, args=(3,), daemon=True)
            ch2_t.start()
            ch3_t.start()

            try:
                while self.running and session_active.is_set():
                    if time.time() - last_frame_rx[0] > 12.0:
                        print(f"[{self.cam_id}] Stream stalled. Reconnecting...")
                        break
                    time.sleep(0.2)
            except Exception as e:
                print(f"[{self.cam_id}] Exception in session monitor: {e}")
            finally:
                session_active.clear()
                self.online = False
                self.sid = -1
                try:
                    proc.stdin.close()
                    proc.terminate()
                    proc.wait(timeout=1)
                except:
                    pass
                cdll.PPPP_Close(sid)
                print(f"[{self.cam_id}] Session closed. Waiting 2s before retry...")
                time.sleep(2)

    def send_ptz(self, direction, speed=50):
        """Send PTZ motor command via P2P channel 0.
        
        Uses command 9030 (motor control) with direction payload.
        Direction mapping: up=0, down=1, left=2, right=3, stop=4
        Also tries direction byte values 1-4 for up/down/left/right (variant B).
        """
        if self.sid < 0 or not self.auth_bytes:
            return False, "Camera not connected"
        
        dir_map_a = {"up": 0, "down": 1, "left": 2, "right": 3, "stop": 4}
        dir_map_b = {"up": 1, "down": 2, "left": 3, "right": 4, "stop": 0}
        
        dir_val = dir_map_a.get(direction)
        if dir_val is None:
            return False, f"Unknown direction: {direction}"
        
        # Try command 9030 with 4-byte payload: [direction, speed, 0, 0]
        payload = struct.pack('>BBBB', dir_val, min(speed, 255), 0, 0)
        hdr = struct.pack('>BBHI', 1, 3, 0, 40 + len(payload))
        cmd_hdr = struct.pack('>HHHH', 9030, 1, 0, len(payload)) + self.auth_bytes
        packet = hdr + cmd_hdr + payload
        ret = cdll.PPPP_Write(self.sid, ctypes.c_byte(0), packet, len(packet))
        
        print(f"[{self.cam_id}] PTZ {direction} cmd=9030 payload={payload.hex()} => ret={ret}")
        return ret >= 0, f"PTZ {direction} sent (ret={ret})"

CAMERA_MANAGERS = {}

class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        from urllib.parse import urlparse
        parsed_url = urlparse(self.path)
        parts = parsed_url.path.strip("/").split("/")
        if not parts or parts[0] == "":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "running", "cameras": list(CAMERA_MANAGERS.keys())}).encode())
            return

        if parts[0] == "status":
            st = {}
            for cid, mgr in CAMERA_MANAGERS.items():
                st[cid] = {
                    "name": mgr.name,
                    "online": mgr.online,
                    "fps": mgr.fps,
                    "frames": mgr.frame_count,
                    "last_frame_age": round(time.time() - mgr.last_frame_time, 2) if mgr.last_frame_time > 0 else 999
                }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(st, indent=2).encode())
            return

        cam_id = parts[0]
        action = parts[1] if len(parts) > 1 else "video"

        mgr = CAMERA_MANAGERS.get(cam_id)
        if not mgr:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Camera not found")
            return

        if action == "snapshot":
            frame = mgr.latest_frame
            if not frame:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b"No frame available yet")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(frame)
            return

        if action == "ptz":
            # Parse query string for direction
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            direction = params.get("dir", ["stop"])[0].lower()
            speed = int(float(params.get("speed", ["50"])[0]))
            
            success, msg = mgr.send_ptz(direction, speed)
            
            # Auto-stop after duration
            duration = float(params.get("duration", ["0.35"])[0])
            if direction != "stop" and duration > 0:
                def auto_stop():
                    time.sleep(duration)
                    mgr.send_ptz("stop")
                threading.Thread(target=auto_stop, daemon=True).start()
            
            resp = json.dumps({"success": success, "message": msg, "direction": direction})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(resp.encode())
            return

        if action == "video":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            placeholder_frame = None
            if os.path.exists(PLACEHOLDER_PATH):
                try:
                    with open(PLACEHOLDER_PATH, "rb") as f:
                        placeholder_frame = f.read()
                except:
                    pass

            last_sent_count = -1
            while True:
                try:
                    frame = None
                    with mgr.cond:
                        if mgr.frame_count == last_sent_count or not mgr.latest_frame:
                            mgr.cond.wait(timeout=1.0)
                        frame = mgr.latest_frame
                        last_sent_count = mgr.frame_count

                    if not frame and placeholder_frame:
                        frame = placeholder_frame

                    if frame:
                        header = (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                        )
                        self.wfile.write(header + frame + b"\r\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
            return

        self.send_response(404)
        self.end_headers()

def main():
    with open(CONFIG_PATH, 'r') as f:
        cams = json.load(f)

    for cam in cams:
        if "663868" in cam["uid"]:
            CAMERA_MANAGERS["cam3"] = YiCameraStreamer("cam3", cam)
        elif "671576" in cam["uid"]:
            CAMERA_MANAGERS["cam4"] = YiCameraStreamer("cam4", cam)

    server = ThreadingHTTPServer(("127.0.0.1", 8084), BridgeHandler)
    print("="*60)
    print("YI IoT P2P Bridge running on http://127.0.0.1:8084")
    print("Routes: /cam3/video, /cam3/snapshot, /cam4/video, /cam4/snapshot, /status")
    print("="*60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for mgr in CAMERA_MANAGERS.values():
            mgr.running = False
        server.server_close()
        cdll.PPPP_DeInitialize()
        print("Bridge stopped.")

if __name__ == "__main__":
    main()
