import os
import sys
import socket
import ctypes
import json
import time
import struct
import random
import hashlib
import hmac
import base64
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

DLL_PATH = os.environ.get('DLL_PATH', r'Z:\app\YI_IOT_APP\PPPP_API.dll')
CRYPTO_PATH = os.environ.get('CRYPTO_PATH', r'Z:\app\YI_IOT_APP\libcrypto-1_1.dll')
CONFIG_PATH = os.environ.get('CONFIG_PATH', r'Z:\app\cameras_p2p_config.json')
PLACEHOLDER_PATH = os.environ.get('PLACEHOLDER_PATH', r'Z:\app\placeholder.jpg')

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
cdll.PPPP_Check.argtypes = [ctypes.c_int, ctypes.c_char_p]
cdll.PPPP_Check.restype = ctypes.c_int
cdll.PPPP_Read.argtypes = [ctypes.c_int, ctypes.c_byte, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int), ctypes.c_int]
cdll.PPPP_Read.restype = ctypes.c_int
cdll.PPPP_Write.argtypes = [ctypes.c_int, ctypes.c_byte, ctypes.c_char_p, ctypes.c_int]
cdll.PPPP_Write.restype = ctypes.c_int
cdll.PPPP_Close.argtypes = [ctypes.c_int]
cdll.PPPP_Close.restype = ctypes.c_int
cdll.PPPP_DeInitialize.argtypes = []
cdll.PPPP_DeInitialize.restype = ctypes.c_int

cdll.PPPP_Initialize(b'\x00', 12)

class H264SocketBroadcaster:
    def __init__(self, port):
        self.port = port
        self.clients = []
        self.lock = threading.Lock()
        self.running = True
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(('0.0.0.0', port))
        self.server_sock.listen(5)
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while self.running:
            try:
                conn, addr = self.server_sock.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                with self.lock:
                    self.clients.append(conn)
                print(f"[TCP Server :{self.port}] Connected client: {addr}")
            except Exception:
                break

    def broadcast(self, data):
        with self.lock:
            dead = []
            for c in self.clients:
                try:
                    c.sendall(data)
                except Exception:
                    dead.append(c)
            for d in dead:
                self.clients.remove(d)
                try: d.close()
                except: pass

    def stop(self):
        self.running = False
        try: self.server_sock.close()
        except: pass

class H264Sequencer:
    """Reorders frames from Channel 2 (I-frames) and Channel 3 (P-frames) into strict numerical order."""
    def __init__(self, on_frame_callback):
        self.callback = on_frame_callback
        self.buffer = {}
        self.expected_seq = None
        self.has_keyframe = False
        self.lock = threading.Lock()
        self.running = True
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def push(self, seq, is_key, data):
        with self.lock:
            now = time.time()
            if not self.has_keyframe:
                if not is_key:
                    return
                self.has_keyframe = True
                self.expected_seq = seq
                self.buffer[seq] = (data, is_key, now)
                return

            diff = (seq - self.expected_seq) & 0xFFFF
            if diff > 32768:
                return
            if diff > 30:
                self.expected_seq = seq
                self.buffer.clear()
            self.buffer[seq] = (data, is_key, now)

    def _run(self):
        while self.running:
            item = None
            seq_to_send = None
            with self.lock:
                if self.expected_seq is not None:
                    if self.expected_seq in self.buffer:
                        seq_to_send = self.expected_seq
                        item = self.buffer.pop(self.expected_seq)
                        self.expected_seq = (self.expected_seq + 1) & 0xFFFF
                    elif self.buffer:
                        oldest_t = min(t for _, _, t in self.buffer.values())
                        if time.time() - oldest_t > 0.35 or len(self.buffer) > 20:
                            min_seq = min(self.buffer.keys(), key=lambda s: (s - self.expected_seq) & 0xFFFF)
                            self.expected_seq = min_seq
                            seq_to_send = self.expected_seq
                            item = self.buffer.pop(self.expected_seq)
                            self.expected_seq = (self.expected_seq + 1) & 0xFFFF

            if item:
                self.callback(seq_to_send, item[1], item[0])
            else:
                time.sleep(0.003)

    def stop(self):
        self.running = False

class YiCameraStreamer:
    def __init__(self, cam_id, config, tcp_port):
        self.cam_id = cam_id
        self.config = config
        self.tcp_port = tcp_port
        self.broadcaster = H264SocketBroadcaster(tcp_port)
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
        self.cmd_seq = 1
        self.auth_bytes = None
        self.cond = threading.Condition()
        self.p2p_write_lock = threading.Lock()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def reload_config(self):
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r') as f:
                    cams = json.load(f)
                for cam in cams:
                    if self.uid == cam.get("uid"):
                        new_pwd = cam.get("password")
                        if new_pwd and new_pwd != self.pwd:
                            print(f"[{self.cam_id}] Password updated from config: {self.pwd[:3]}*** -> {new_pwd[:3]}***")
                            self.pwd = new_pwd
                            self.config = cam
                            return True
        except Exception as e:
            print(f"[{self.cam_id}] Error reading config: {e}")
        return False

    def make_auth(self):
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        nonce = "".join(random.choice(chars) for _ in range(15))
        str_to_hash = f"user=xiaoyiuser&nonce={nonce}"
        sig = base64.b64encode(hmac.new(self.pwd.encode('utf-8'), str_to_hash.encode('utf-8'), hashlib.sha1).digest()).decode('ascii')
        if len(sig) > 15:
            sig = sig[:15]
        auth_str = f"{nonce},{sig}"
        return auth_str.encode('ascii').ljust(32, b'\x00')

    def _run_loop(self):
        aes_key = AES_KEY()
        st_buf = ctypes.create_string_buffer(256)

        while self.running:
            self.online = False
            sid = -1
            self.reload_config()
            crypto.AES_set_decrypt_key((self.pwd + "0").encode('ascii'), 128, ctypes.byref(aes_key))
            print(f"[{self.cam_id}] Connecting to {self.name} ({self.uid})...")
            for attempt in range(10):
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
                wait_time = 5 if sid == -3006 else 2
                print(f"[{self.cam_id}] Connect attempt {attempt+1} got sid {sid}, retrying in {wait_time}s...")
                time.sleep(wait_time)

            if sid < 0:
                cooldown = 8 if sid == -3006 else 4
                print(f"[{self.cam_id}] Connection failed ({sid}). Retrying in {cooldown}s...")
                time.sleep(cooldown)
                continue

            for _ in range(15):
                chk = cdll.PPPP_Check(sid, st_buf)
                if chk == 0:
                    break
                time.sleep(0.3)

            print(f"[{self.cam_id}] Session established (SID={sid}). Starting video...")
            self.sid = sid
            auth_bytes = self.make_auth()
            self.auth_bytes = auth_bytes

            session_active = threading.Event()
            session_active.set()
            auth_failed = [False]
            last_frame_rx = [time.time()]
            last_fps_calc = [time.time()]
            frames_in_period = [0]

            def send_frame(seq, is_key, nal_data):
                try:
                    self.broadcaster.broadcast(nal_data)
                    last_frame_rx[0] = time.time()
                    with self.cond:
                        self.frame_count += 1
                        self.last_frame_time = time.time()
                        if not self.online:
                            print(f"[{self.cam_id}] Stream live! Video frames broadcasting on TCP :{self.tcp_port}")
                        self.online = True
                        self.cond.notify_all()
                    frames_in_period[0] += 1
                    now = time.time()
                    if now - last_fps_calc[0] >= 2.0:
                        self.fps = round(frames_in_period[0] / (now - last_fps_calc[0]), 1)
                        frames_in_period[0] = 0
                        last_fps_calc[0] = now
                except Exception as e:
                    print(f"[{self.cam_id}] Broadcast error: {e}")

            sequencer = H264Sequencer(send_frame)

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
                                
                                seq = struct.unpack_from('>H', raw_frame, 6)[0]
                                h264_nal = bytes(raw_frame[24:])
                                sequencer.push(seq, ch_num == 2, h264_nal)
                    elif ret < 0 and ret != -3003:
                        if ret in (-3014, -3012, -3006, -3001):
                            print(f"[{self.cam_id}] Ch{ch_num} connection broken ({ret})")
                            session_active.clear()
                            break

            ch2_t = threading.Thread(target=channel_reader, args=(2,), daemon=True)
            ch3_t = threading.Thread(target=channel_reader, args=(3,), daemon=True)
            ch2_t.start()
            ch3_t.start()

            def channel_0_reader():
                c0_buf = ctypes.create_string_buffer(4096)
                while self.running and session_active.is_set():
                    hdr_len = ctypes.c_int(8)
                    ret = cdll.PPPP_Read(sid, ctypes.c_byte(0), c0_buf, ctypes.byref(hdr_len), 1000)
                    if ret >= 0 and hdr_len.value >= 8:
                        body_len = struct.unpack_from('>I', c0_buf.raw, 4)[0]
                        if 0 < body_len <= 4096:
                            b_len = ctypes.c_int(body_len)
                            ret2 = cdll.PPPP_Read(sid, ctypes.c_byte(0), c0_buf, ctypes.byref(b_len), 1000)
                            if ret2 >= 0 and b_len.value >= 8:
                                raw_bytes = bytes(c0_buf.raw[:b_len.value])
                                r_cmd, r_resp, r_seq, r_ex = struct.unpack_from('>HHHH', raw_bytes, 0)
                                r_status = struct.unpack_from('>i', raw_bytes, 8)[0] if len(raw_bytes) >= 12 else 0
                                if r_status == 1:
                                    print(f"[{self.cam_id}] Auth rejected (status=1)")
                                    auth_failed[0] = True
                                    self.reload_config()
                                    session_active.clear()
                                    break
                    elif ret < 0 and ret not in (-3003, -3004):
                        if ret in (-3014, -3012, -3006, -3001):
                            break

            ch0_t = threading.Thread(target=channel_0_reader, daemon=True)
            ch0_t.start()

            # Request video stream on Channel 0 (1280x720 HD resolution: byte 1 = 1)
            payload = bytes([1, 1, 1, 0])
            hdr = struct.pack('>BBHI', 1, 3, 0, 40 + len(payload))
            cmd_hdr = struct.pack('>HHHH', 9029, 1, 0, len(payload)) + auth_bytes
            full_packet = hdr + cmd_hdr + payload
            with self.p2p_write_lock:
                cdll.PPPP_Write(sid, ctypes.c_byte(0), full_packet, len(full_packet))

            stream_start_time = time.time()
            try:
                while self.running and session_active.is_set():
                    if auth_failed[0]:
                        print(f"[{self.cam_id}] Reconnecting due to auth rejection...")
                        break
                    chk = cdll.PPPP_Check(sid, st_buf)
                    if chk < 0:
                        print(f"[{self.cam_id}] PPPP_Check failed ({chk}). Reconnecting...")
                        break
                    if not sequencer.has_keyframe and (time.time() - stream_start_time > 15.0):
                        print(f"[{self.cam_id}] Keyframe timeout (>15s). Reconnecting...")
                        break
                    if sequencer.has_keyframe and (time.time() - last_frame_rx[0] > 12.0):
                        print(f"[{self.cam_id}] Frame timeout (>12s). Reconnecting...")
                        break
                    time.sleep(2.0)
            except Exception as e:
                print(f"[{self.cam_id}] Session monitor error: {e}")
            finally:
                session_active.clear()
                sequencer.stop()
                self.online = False
                self.sid = -1
                cdll.PPPP_Close(sid)
                print(f"[{self.cam_id}] Session closed. Waiting 3s before retry...")
                time.sleep(3)

    def send_ptz(self, direction, speed=0):
        if self.sid < 0:
            return False, "Camera not connected"
        dir_map = {"up": 1, "down": 2, "left": 3, "right": 4}
        if direction == "stop":
            cmd_code = 0x4013
            payload = b""
        elif direction in dir_map:
            dir_val = dir_map[direction]
            speed_val = int(speed) if speed else 0
            cmd_code = 0x4012
            payload = struct.pack('>II', dir_val, speed_val)
        else:
            return False, f"Unknown direction: {direction}"

        auth_bytes = self.make_auth()
        hdr = struct.pack('>BBHI', 1, 3, 0, 40 + len(payload))
        self.cmd_seq = getattr(self, "cmd_seq", 1) + 1
        cmd_hdr = struct.pack('>HHHH', cmd_code, self.cmd_seq, 0, len(payload)) + auth_bytes
        packet = hdr + cmd_hdr + payload
        with self.p2p_write_lock:
            ret = cdll.PPPP_Write(self.sid, ctypes.c_byte(0), packet, len(packet))
        print(f"[{self.cam_id}] PTZ {direction} cmd=0x{cmd_code:04x} ret={ret}")
        return ret >= 0, f"PTZ {direction} sent"

CAMERA_MANAGERS = {}

class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        
        if parts[0] in ("status", "api"):
            statuses = {}
            for cid, mgr in CAMERA_MANAGERS.items():
                statuses[cid] = {
                    "online": mgr.online,
                    "fps": mgr.fps,
                    "frame_count": mgr.frame_count,
                    "name": mgr.name,
                    "tcp_port": mgr.tcp_port
                }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(statuses).encode())
            return

        if len(parts) >= 2:
            cam_id = parts[0]
            action = parts[1]
            mgr = CAMERA_MANAGERS.get(cam_id)
            if not mgr:
                self.send_response(404)
                self.end_headers()
                return

            if action == "ptz":
                params = parse_qs(parsed.query)
                direction = params.get("dir", ["stop"])[0].lower()
                speed = float(params.get("speed", ["0"])[0])
                success, msg = mgr.send_ptz(direction, speed)
                duration = float(params.get("duration", ["0.8"])[0])
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

            if action == "snapshot":
                snap_path = f"/tmp/{cam_id}_snapshot.jpg"
                data = None
                if os.path.exists(snap_path):
                    try:
                        with open(snap_path, "rb") as f:
                            data = f.read()
                    except: pass
                if not data and os.path.exists(PLACEHOLDER_PATH):
                    try:
                        with open(PLACEHOLDER_PATH, "rb") as f:
                            data = f.read()
                    except: pass
                if data:
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_response(404)
                    self.end_headers()
                return

        self.send_response(404)
        self.end_headers()

def main():
    with open(CONFIG_PATH, 'r') as f:
        cams = json.load(f)

    for idx, cam in enumerate(cams):
        uid = cam.get("uid", "")
        if "663868" in uid:
            cam_id = "cam3"
        elif "671576" in uid:
            cam_id = "cam4"
        else:
            cam_id = cam.get("id") or f"cam{idx+3}"
        port = 19003 if cam_id == "cam3" else 19004
        CAMERA_MANAGERS[cam_id] = YiCameraStreamer(cam_id, cam, tcp_port=port)

    server = ThreadingHTTPServer(("0.0.0.0", 8084), BridgeHandler)
    print("="*60)
    print("YI IoT P2P Bridge running on port 8084")
    print("Broadcasting H.264: cam3 on :19003, cam4 on :19004")
    print("PTZ & Status API: http://0.0.0.0:8084/<cam_id>/ptz")
    print("="*60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for mgr in CAMERA_MANAGERS.values():
            mgr.running = False
            mgr.broadcaster.stop()
        server.server_close()
        cdll.PPPP_DeInitialize()
        print("Bridge stopped.")

if __name__ == "__main__":
    main()
