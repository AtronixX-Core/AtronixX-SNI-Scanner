"""
AX-Scanner :: xray_manager.py

Owns a completely separate copy of xray-core, named and pathed so it can
never be confused with (or collide with) whatever xray-core a panel like
Pasargad already has installed and running in production.

Isolation guarantees this module upholds:
  - binary lives at BIN_DIR/ax-scanner-xray, never overwrites another path
  - every config file is written under RUN_DIR, one per ephemeral instance
  - every spawned process is tracked by pid and *always* killed on cleanup
  - ports are chosen from a dedicated range (config.EPHEMERAL_PORT_MIN..MAX)
    and checked free immediately before binding
  - nothing is registered as a systemd service except the optional Agent
    (see agent_server.py), which is a distinct unit name from any panel unit
"""

import json
import os
import platform
import random
import socket
import stat
import subprocess
import time
import urllib.request

from core.config import BIN_DIR, RUN_DIR, XRAY_BIN_PATH, EPHEMERAL_PORT_MIN, EPHEMERAL_PORT_MAX

XRAY_RELEASES_API = "https://api.github.com/repos/XTLS/Xray-core/releases/latest"


def _arch_asset_name():
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "Xray-linux-64.zip"
    if machine in ("aarch64", "arm64"):
        return "Xray-linux-arm64-v8a.zip"
    raise RuntimeError(f"Unsupported architecture for xray-core: {machine}")


def is_installed():
    return os.path.isfile(XRAY_BIN_PATH) and os.access(XRAY_BIN_PATH, os.X_OK)


def install(ui):
    """Downloads xray-core fresh into our isolated bin dir."""
    if is_installed():
        ui.ok("Isolated xray-core binary already present.")
        return

    os.makedirs(BIN_DIR, exist_ok=True)
    asset_name = _arch_asset_name()

    ui.info("Looking up latest xray-core release...")
    with urllib.request.urlopen(XRAY_RELEASES_API, timeout=15) as r:
        release = json.loads(r.read().decode())

    asset = next((a for a in release.get("assets", []) if a["name"] == asset_name), None)
    if not asset:
        raise RuntimeError(f"Could not find asset {asset_name} in latest xray-core release")

    zip_path = os.path.join(BIN_DIR, "xray_download.zip")
    ui.info(f"Downloading {asset_name}...")
    urllib.request.urlretrieve(asset["browser_download_url"], zip_path)

    import zipfile
    with zipfile.ZipFile(zip_path) as z:
        z.extract("xray", BIN_DIR)

    extracted = os.path.join(BIN_DIR, "xray")
    os.replace(extracted, XRAY_BIN_PATH)
    os.chmod(XRAY_BIN_PATH, os.stat(XRAY_BIN_PATH).st_mode | stat.S_IEXEC)
    os.remove(zip_path)

    ui.ok(f"Isolated xray-core installed at {XRAY_BIN_PATH} (never touches the panel's binary).")


def _free_port():
    for _ in range(50):
        port = random.randint(EPHEMERAL_PORT_MIN, EPHEMERAL_PORT_MAX)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Could not find a free ephemeral port in the configured range.")


XHTTP_PATH = "/ax"


def _stream_settings(transport, sni_dest, reality):
    reality = dict(reality)
    ss = {"network": "tcp" if transport == "tcp" else "xhttp", "security": "reality",
          "realitySettings": reality}
    if transport == "xhttp":
        ss["xhttpSettings"] = {"path": XHTTP_PATH, "mode": "auto"}
    return ss


def build_reality_server_config(sni_dest, private_key, short_id, listen_port=None,
                                transport="tcp"):
    """Returns (config_dict, port) for a temporary Reality inbound.
    transport: "tcp" (VLESS + xtls-rprx-vision) or "xhttp"."""
    port = listen_port or _free_port()
    client = {"id": "00000000-0000-0000-0000-000000000000"}
    if transport == "tcp":
        client["flow"] = "xtls-rprx-vision"
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "listen": "0.0.0.0",
            "port": port,
            "protocol": "vless",
            "settings": {"clients": [client], "decryption": "none"},
            "streamSettings": _stream_settings(transport, sni_dest, {
                "show": False,
                "dest": f"{sni_dest}:443",
                "xver": 0,
                "serverNames": [sni_dest],
                "privateKey": private_key,
                "shortIds": [short_id],
            }),
        }],
        "outbounds": [{"protocol": "freedom"}],
    }
    return config, port


def generate_keypair():
    """Uses the isolated xray binary's own x25519 keygen — no external deps."""
    out = subprocess.run([XRAY_BIN_PATH, "x25519"], capture_output=True, text=True, timeout=10)
    private_key, public_key = None, None
    for line in out.stdout.splitlines():
        if line.lower().startswith("private key:"):
            private_key = line.split(":", 1)[1].strip()
        if line.lower().startswith("public key:"):
            public_key = line.split(":", 1)[1].strip()
    if not private_key or not public_key:
        raise RuntimeError("Failed to generate x25519 keypair via xray-core.")
    return private_key, public_key


class XrayProcess:
    """A single tracked, disposable xray-core process. Always clean this up."""

    def __init__(self, config_dict, tag):
        os.makedirs(RUN_DIR, exist_ok=True)
        self.tag = tag
        self.config_path = os.path.join(RUN_DIR, f"{tag}.json")
        with open(self.config_path, "w") as f:
            json.dump(config_dict, f)
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen(
            [XRAY_BIN_PATH, "run", "-c", self.config_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)  # give it a moment to bind

    def is_alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if os.path.exists(self.config_path):
            os.remove(self.config_path)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def kill_all_orphans():
    """Safety net for uninstall / crash recovery: kills any process that was
    launched from OUR binary path specifically — never touches the panel's
    xray process, which lives at a different path/name entirely."""
    try:
        subprocess.run(["pkill", "-f", XRAY_BIN_PATH], check=False)
    except Exception:
        pass
