# LocalCameraHub

A self-hosted, zero-cloud surveillance dashboard that streams live video from ONVIF/RTSP cameras and YI IoT (CB101) P2P cameras directly in your browser. No subscriptions, no cloud dependencies, no phone required.

## Features

- **4-Camera Live Dashboard** — Simultaneous MJPEG streams with real-time viewing
- **Native P2P Bridge** — Direct peer-to-peer streaming from YI IoT cameras using reverse-engineered protocol
- **ONVIF PTZ Control** — Pan/Tilt/Zoom motor controls for ONVIF-compatible cameras
- **SD Card Playback** — Browse and play recorded footage from camera SD cards
- **External Player Support** — One-click launch in VLC or ffplay
- **Zero Cloud Dependency** — All processing happens on your local network
- **Auto-Reconnect** — P2P bridge automatically reconnects dropped sessions

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Browser Dashboard                         │
│                   http://localhost:5000                       │
└────────────────────────┬────────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          │     Flask Hub (app.py)       │
          │     Port 5000 (64-bit)      │
          └──────┬───────────┬──────────┘
                 │           │
     ┌───────────┘           └───────────┐
     │ RTSP/ONVIF                        │ HTTP Proxy
     │                                   │
┌────┴─────┐  ┌──────────┐    ┌─────────┴─────────┐
│ Camera 1 │  │ Camera 2 │    │  P2P Bridge        │
│ ONVIF    │  │ ONVIF    │    │  yi_p2p_bridge.py  │
│ .238:554 │  │ .11:554  │    │  Port 8084 (32-bit)│
└──────────┘  └──────────┘    └────┬──────────┬────┘
                                   │ P2P      │ P2P
                              ┌────┴───┐ ┌────┴───┐
                              │ Cam 3  │ │ Cam 4  │
                              │ YI IoT │ │ YI IoT │
                              │ CB101  │ │ CB101  │
                              └────────┘ └────────┘
```

## How It Works

### ONVIF Cameras (Cam 1 & 2)
Standard RTSP streams are transcoded to MJPEG via FFmpeg for browser playback. PTZ commands are sent as ONVIF SOAP requests.

### YI IoT P2P Cameras (Cam 3 & 4)
The P2P bridge reverse-engineers the YI IoT protocol:

1. **Cloud Authentication** — Logs into the Xiaoyi Gateway API to retrieve device credentials
2. **Password Decryption** — AES-128-ECB decrypts camera passwords using UID-derived keys
3. **P2P Session** — Uses the native `PPPP_API.dll` (TUTK-based P2P library) to establish direct connections
4. **HMAC Authentication** — Authenticates to each camera using HMAC-SHA1 signed nonces
5. **Video Streaming** — Receives encrypted H.264 frames on channels 2 (I-frames) and 3 (P-frames)
6. **Frame Decryption** — AES-128-ECB decrypts the first 32 bytes of each encrypted frame
7. **FFmpeg Transcoding** — Pipes raw H.264 NAL units into FFmpeg to produce MJPEG for the browser

### Protocol Details

| Component | Detail |
|-----------|--------|
| P2P Library | `PPPP_API.dll` (32-bit, TUTK-based) |
| Command Channel | Channel 0 (bidirectional) |
| I-Frame Channel | Channel 2 (keyframes, ~80KB) |
| P-Frame Channel | Channel 3 (delta frames, ~1-13KB) |
| Video Stream Command | Code 9029 (`0x2345`) — Start streaming |
| SD Playback Command | Code 9030 (`0x2346`) — SD card clip streaming |
| PTZ Motor Move | Code 16402 (`0x4012`) — Payload: `<II` (dir: 1=UP, 2=DOWN, 3=LEFT, 4=RIGHT, speed: 0-100) |
| PTZ Motor Stop | Code 16403 (`0x4013`) — Payload: empty (0 bytes) |
| Auth Format | `nonce,HMAC-SHA1(password, "user=xiaoyiuser&nonce=" + nonce)` |
| Encryption | AES-128-ECB, key = `password + "0"` |
| Frame Header | 24 bytes (codec, flags, width, height, timestamp) |
| Byte Order | Big-endian network headers, little-endian payload fields |

## Requirements

### Software
- **Python 3.10+** (64-bit) for the Flask dashboard
- **Python 3.x** (32-bit) for the P2P bridge (required by 32-bit PPPP_API.dll)
- **FFmpeg** — for RTSP-to-MJPEG and H.264-to-MJPEG transcoding
- **Flask** — `pip install flask`
- **cryptography** — `pip install cryptography` (only for `get_cam_p2p_info.py`)

### Hardware
- ONVIF/RTSP cameras (any standard IP camera)
- YI IoT CB101 cameras (or similar TUTK-based P2P cameras with TNP prefix UIDs)

### Required DLLs (for P2P cameras)
- `PPPP_API.dll` — 32-bit TUTK P2P library (extract from YI IoT APK or camera firmware)
- `libcrypto-1_1.dll` — 32-bit OpenSSL (for AES decryption via ctypes)

## Setup

### 1. Clone and Configure

```bash
git clone https://github.com/YOUR_USER/LocalCameraHub.git
cd LocalCameraHub
pip install flask
```

### 2. Configure ONVIF Cameras

Edit the `CAMERAS` dict in `app.py` with your camera IPs and RTSP URLs.

### 3. Configure YI IoT P2P Cameras

#### Option A: Automatic (recommended)
Set your YI IoT credentials as environment variables and run the config generator:

```bash
set YI_EMAIL=your@email.com
set YI_PASSWORD=YourPassword
set YI_HMAC_SECRET=YourHmacSecret
python get_cam_p2p_info.py
```

This creates `cameras_p2p_config.json` with all required P2P connection parameters.

#### Option B: Manual
Copy `cameras_p2p_config.example.json` to `cameras_p2p_config.json` and fill in your camera details. You'll need:
- **UID** — Camera's P2P unique identifier (format: `TNPXGBG-XXXXXX-XXXXX`)
- **Password** — Decrypted camera password
- **InitString** — P2P initialization string from TNP device info API
- **License** — P2P license key from TNP device info API

### 4. Place DLLs
Put `PPPP_API.dll` and `libcrypto-1_1.dll` in a directory and update the paths in `yi_p2p_bridge.py`.

### 5. Update Paths
Edit `yi_p2p_bridge.py` to set:
- `DLL_PATH` — Path to `PPPP_API.dll`
- `CRYPTO_PATH` — Path to `libcrypto-1_1.dll`
- `FFMPEG_PATH` — Path to `ffmpeg.exe`
- `CONFIG_PATH` — Path to `cameras_p2p_config.json`

### 6. Launch

**One-click (Windows):**
```bash
start_cameras.bat
```

**Manual:**
```bash
# Terminal 1: Start P2P bridge (32-bit Python)
path\to\python32\python.exe yi_p2p_bridge.py

# Terminal 2: Start Flask dashboard (64-bit Python)
python app.py
```

Open http://localhost:5000 in your browser.

## Use Cases

### Home Security Monitoring
View all cameras from a single dashboard on any device on your network. No cloud subscriptions needed.

### Baby/Pet Monitoring
Full-screen any camera feed with real-time streaming. PTZ controls let you follow movement.

### SD Card Forensics
Plug a camera's SD card into your PC and browse/play all recorded footage directly in the dashboard.

### Network-Isolated Surveillance
Runs entirely on your LAN — cameras never need internet access after initial P2P credential retrieval.

### Multi-Protocol Unification
Combines ONVIF/RTSP cameras with proprietary P2P cameras (YI IoT, Kami, etc.) into a single interface.

### DIY NVR Replacement
Replace cloud-dependent NVR systems with a lightweight, transparent, open-source alternative.

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard HTML |
| `/stream/<cam_id>` | GET | MJPEG live stream |
| `/snapshot/<cam_id>` | GET | Latest JPEG frame |
| `/api/ptz/<cam_id>?dir=<direction>&speed=<float>&duration=<float>` | GET | PTZ motor control |
| `/api/launch_player?player=<vlc\|ffplay>&cam_id=<id>` | GET | Launch external player |
| `/api/records` | GET | List SD card recordings |
| `/api/records/play?file=<path>` | GET | Stream recorded MP4 |
| `/api/records/open_vlc?file=<path>` | GET | Open recording in VLC |

### P2P Bridge API (port 8084)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Bridge status |
| `/status` | GET | Per-camera status (online, fps, frame count) |
| `/<cam_id>/video` | GET | MJPEG stream |
| `/<cam_id>/snapshot` | GET | Latest JPEG |

## File Structure

```
LocalCameraHub/
├── app.py                          # Flask dashboard + ONVIF PTZ + RTSP proxy
├── yi_p2p_bridge.py                # Native P2P bridge for YI IoT cameras
├── get_cam_p2p_info.py             # Cloud login & config generator
├── cameras_p2p_config.example.json # Template for P2P camera config
├── start_cameras.bat               # One-click Windows launcher
├── sd_card_files/                  # Camera SD card configuration files
│   ├── anyka_cfg.ini
│   ├── README_SD.txt
│   ├── run.sh
│   ├── test.sh
│   └── Factory/
│       ├── config.sh
│       └── init.sh
├── mediamtx.yml                    # MediaMTX unified RTSP server configuration
├── .gitignore
└── README.md
```

## RTSP Server & Frigate NVR Integration

The system includes a high-performance **MediaMTX** RTSP server running on port `8554`. It converts both YI IoT P2P camera feeds and ONVIF streams into clean, unified, low-latency RTSP feeds for NVRs like **Frigate**, **Home Assistant**, or **VLC**.

### Unified RTSP Endpoints

| Camera | Hardware | Type | RTSP URL |
| :--- | :--- | :--- | :--- |
| **Cam 1** | Macro-Video | ONVIF | `rtsp://<HOST_IP>:8554/cam1` |
| **Cam 2** | Macro-Video | ONVIF | `rtsp://<HOST_IP>:8554/cam2` |
| **Cam 3** | YI IoT (Storage) | P2P -> RTSP | `rtsp://<HOST_IP>:8554/cam3` |
| **Cam 4** | YI IoT (Cámara2) | P2P -> RTSP | `rtsp://<HOST_IP>:8554/cam4` |

*Note: For this host PC (`192.168.0.46`), replace `<HOST_IP>` with `192.168.0.46`.*

### Frigate NVR Configuration (`config.yml`)

Add the following to your Frigate `config.yml`:

```yaml
cameras:
  cam1:
    ffmpeg:
      inputs:
        - path: rtsp://192.168.0.46:8554/cam1
          input_args: preset-rtsp-generic
          roles:
            - detect
            - record
    detect:
      width: 640
      height: 480
      fps: 5

  cam2:
    ffmpeg:
      inputs:
        - path: rtsp://192.168.0.46:8554/cam2
          input_args: preset-rtsp-generic
          roles:
            - detect
            - record
    detect:
      width: 1280
      height: 720
      fps: 5

  cam3:
    ffmpeg:
      inputs:
        - path: rtsp://192.168.0.46:8554/cam3
          input_args: preset-rtsp-generic
          roles:
            - detect
            - record
    detect:
      width: 1280
      height: 720
      fps: 5

  cam4:
    ffmpeg:
      inputs:
        - path: rtsp://192.168.0.46:8554/cam4
          input_args: preset-rtsp-generic
          roles:
            - detect
            - record
    detect:
      width: 1280
      height: 720
      fps: 5
```

## Troubleshooting


### P2P Camera shows "Stream reconnecting"
- Check that the P2P bridge is running on port 8084
- Ensure no other app (e.g., phone app) is connected to the camera (only one P2P session at a time)
- Error -3006 means the camera's P2P slot is occupied — close other connections

### ONVIF Camera not streaming
- Verify the camera is reachable at its IP:554
- Check the RTSP URL format in the `CAMERAS` config

### PTZ not responding
- ONVIF PTZ uses port 8899 — ensure your camera's ONVIF service is on that port
- Check the PTZ profile token matches your camera's configuration

### 32-bit Python DLL errors
- `WinError 193` means you're using 64-bit Python with 32-bit DLLs — use 32-bit Python
- Ensure `PPPP_API.dll` and `libcrypto-1_1.dll` are both 32-bit

## Security Notes

- **No credentials in the codebase** — All secrets are loaded from environment variables or `.env` files
- **LAN-only by default** — The dashboard binds to `0.0.0.0:5000` but is intended for local network use
- **P2P bridge binds to localhost** — Only accessible from the same machine
- **Camera passwords** are AES-encrypted in transit from the cloud API and only stored locally

## License

MIT License — See [LICENSE](LICENSE) for details.

## Acknowledgments

- Protocol reverse-engineering from tinyCam APK decompilation
- TUTK P2P library documentation from CS2 Network resources
- ONVIF PTZ specification for SOAP-based motor control
