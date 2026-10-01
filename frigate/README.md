# Frigate NVR + Full PTZ Integration

This folder contains the complete, ready-to-run Docker configuration for **Frigate NVR** with all 4 cameras and **full ONVIF PTZ motor control**.

---

## Camera & PTZ Architecture

| Camera | Hardware | Type | RTSP Feed | ONVIF PTZ Host:Port |
| :--- | :--- | :--- | :--- | :--- |
| **cam1_macro** | Macro-Video | ONVIF | `rtsp://192.168.0.46:8554/cam1` | `192.168.0.238:8899` |
| **cam2_macro** | Macro-Video | ONVIF | `rtsp://192.168.0.46:8554/cam2` | `192.168.0.11:8899` |
| **cam3_yi_storage** | YI IoT (Storage) | P2P -> RTSP + ONVIF | `rtsp://192.168.0.46:8554/cam3` | `192.168.0.46:8898` |
| **cam4_yi_camara2** | YI IoT (Cámara2) | P2P -> RTSP + ONVIF | `rtsp://192.168.0.46:8554/cam4` | `192.168.0.46:8897` |

- **RTSP Streams:** Served by MediaMTX running on host PC `192.168.0.46:8554`.
- **PTZ for Cam 1 & 2:** Handled natively by cameras over ONVIF port `8899`.
- **PTZ for Cam 3 & 4:** Handled by the integrated ONVIF PTZ bridge running on ports `8898` (Cam 3) and `8897` (Cam 4) on host `192.168.0.46`. When Frigate sends ONVIF `ContinuousMove` or `Stop`, the bridge translates them into native YI IoT P2P motor commands (`0x4012` / `0x4013`).

---

## Starting Frigate

### Option A: Running on a Linux Server / NAS / Raspberry Pi / Unraid
If you have a Linux machine, NAS, or Home Assistant server on your home network:
1. Copy this `frigate` folder to that machine.
2. In the folder, run:
   ```bash
   docker compose up -d
   ```
3. Open Frigate Web UI: `http://<SERVER_IP>:8971` (or unauthenticated port `5001`).

### Option B: Running on this Windows PC
*Note: Your Intel Core i9-12900K currently has CPU Virtualization (VT-x) disabled in BIOS.*
1. Reboot PC and enter BIOS (press **Del** or **F2** on startup).
2. Enable **Intel Virtualization Technology (Intel VT-x / VMX)** under Advanced CPU Settings.
3. Boot back into Windows, install Docker Desktop:
   ```powershell
   winget install Docker.DockerDesktop
   ```
4. Start Docker Desktop, then in this directory run:
   ```powershell
   docker compose up -d
   ```
5. Open Frigate: `http://localhost:8971` or `http://localhost:5001`.

---

## Port Allocation

- `8971` -> Frigate Main Web UI (HTTPS / Auth)
- `5001` -> Frigate Web UI & API (mapped to 5001 to prevent conflict with Flask Hub on 5000)
- `8555` -> go2rtc RTSP restream (mapped to 8555 to prevent conflict with MediaMTX on 8554)
- `8556` -> WebRTC video transport
