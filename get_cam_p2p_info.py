"""
YI IoT Cloud Login & P2P Config Generator

Authenticates to the Xiaoyi Gateway API to retrieve your camera's
P2P connection parameters (UID, password, InitString, License).

Outputs cameras_p2p_config.json which yi_p2p_bridge.py reads at startup.

Usage:
    Set environment variables YI_EMAIL, YI_PASSWORD, YI_HMAC_SECRET
    then run with 32-bit Python:

        set YI_EMAIL=your@email.com
        set YI_PASSWORD=YourPassword
        set YI_HMAC_SECRET=YourHmacSecret
        python get_cam_p2p_info.py

    Or create a .env file (not tracked by git):
        YI_EMAIL=your@email.com
        YI_PASSWORD=YourPassword
        YI_HMAC_SECRET=YourHmacSecret
"""

import os
import sys
import urllib.request
import urllib.parse
import hmac
import hashlib
import base64
import json

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
except ImportError:
    print("ERROR: 'cryptography' package required. Install with: pip install cryptography")
    sys.exit(1)

# --- Load credentials from environment ---
def load_env_file():
    """Load .env file if it exists in the script directory."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())

load_env_file()

email = os.environ.get("YI_EMAIL")
password = os.environ.get("YI_PASSWORD")
secret_key = os.environ.get("YI_HMAC_SECRET")

if not all([email, password, secret_key]):
    print("ERROR: Missing credentials. Set these environment variables:")
    print("  YI_EMAIL       - Your YI IoT account email")
    print("  YI_PASSWORD    - Your YI IoT account password")
    print("  YI_HMAC_SECRET - HMAC secret key (found in APK)")
    print("\nOr create a .env file with these values.")
    sys.exit(1)

secret_key = secret_key.encode("utf-8")

# --- Step 1: Login ---
h = hmac.new(secret_key, password.encode("utf-8"), hashlib.sha256)
pwd_b64 = base64.b64encode(h.digest()).decode("ascii")

headers = {
    "User-Agent": "yihome/4.70.1_20200727 (Nexus 6P; Android 8.1.0; en-US)",
    "x-xiaoyi-appversion": "android;241;4.70.1_20200727",
}

base_url = "https://gw-us.xiaoyi.com"
login_url = f"{base_url}/v4/users/login"
params = {
    "seq": "1",
    "account": email,
    "password": pwd_b64,
    "dev_name": "google",
    "dev_type": "Nexus 6P",
    "dev_os_version": "Android_Neutral",
}

print(f"Logging in as {email}...")
req = urllib.request.Request(
    f"{login_url}?{urllib.parse.urlencode(params)}", headers=headers
)
with urllib.request.urlopen(req) as resp:
    res = json.loads(resp.read().decode("utf-8"))
    if res.get("code") != "20000":
        print(f"Login failed: {res}")
        sys.exit(1)
    token = res["data"]["token"]
    token_secret = res["data"]["token_secret"]
    userid = str(res["data"]["userid"])
    print(f"Login successful. User ID: {userid}")

hmac_key = (token + "&" + token_secret).encode("utf-8")


# --- Step 2: Get device list ---
data_to_sign = f"seq=1&userid={userid}"
hmac_sig = base64.b64encode(
    hmac.new(hmac_key, data_to_sign.encode("utf-8"), hashlib.sha1).digest()
).decode("ascii")
dev_url = f"{base_url}/v4/devices/list?{urllib.parse.urlencode([('seq', '1'), ('userid', userid), ('hmac', hmac_sig)])}"
with urllib.request.urlopen(
    urllib.request.Request(dev_url, headers=headers)
) as resp:
    dev_res = json.loads(resp.read().decode("utf-8"))

devices = dev_res.get("data", [])
print(f"Found {len(devices)} device(s)")


def decrypt_cam_password(uid, hex_pwd):
    """AES-128-ECB decrypt the camera password using first 16 chars of UID as key."""
    key = uid[:16].encode("utf-8")
    ciphertext = bytes.fromhex(hex_pwd)
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    pad_len = padded[-1]
    return padded[:-pad_len].decode("utf-8", errors="ignore")


# --- Step 3: Fetch TNP info for each device ---
cameras_info = []

for dev in devices:
    uid = dev["uid"]
    name = dev.get("name", "Camera")
    ip = dev.get("ipcParam", {}).get("ip")
    hex_pwd = dev.get("password")
    decrypted_pwd = decrypt_cam_password(uid, hex_pwd)

    tnp_query = f"seq=1&userid={userid}&uid={uid}"
    tnp_sig = base64.b64encode(
        hmac.new(hmac_key, tnp_query.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")
    tnp_params = [
        ("seq", "1"),
        ("userid", userid),
        ("uid", uid),
        ("hmac", tnp_sig),
    ]
    tnp_url = f"{base_url}/v4/tnp/device_info?{urllib.parse.urlencode(tnp_params)}"
    with urllib.request.urlopen(
        urllib.request.Request(tnp_url, headers=headers)
    ) as tresp:
        tnp_res = json.loads(tresp.read().decode("utf-8"))

    init_str = tnp_res.get("data", {}).get("InitString")
    license_val = tnp_res.get("data", {}).get("License")
    license_key = license_val.split(":")[0] if license_val else ""

    cam_info = {
        "name": name,
        "uid": uid,
        "ip": ip,
        "password": decrypted_pwd,
        "init_string": init_str,
        "license": license_key,
        "full_license": license_val,
        "p2p_encrypt": dev.get("ipcParam", {}).get("p2p_encrypt"),
    }
    cameras_info.append(cam_info)
    print(f"  [{name}] UID={uid}  IP={ip}  Password=***")

output_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "cameras_p2p_config.json"
)
with open(output_path, "w") as f:
    json.dump(cameras_info, f, indent=2)
print(f"\nSaved {len(cameras_info)} camera(s) to {output_path}")
