"""
AX-Scanner :: uninstall.py

Removes everything this tool ever created, and nothing else:
  - kills any lingering process spawned from our isolated xray binary
  - stops + disables + removes the optional systemd Agent unit
  - deletes BASE_DIR (/opt/ax-scanner) entirely

It never touches the panel's xray-core, its systemd units, or its config,
because those all live at completely different paths/names by design
(see config.py's isolation section).
"""

import json
import os
import shutil
import socket
import subprocess

from core.config import (BASE_DIR, SYSTEMD_UNIT_NAME, SYSTEMD_UNIT_PATH, XRAY_BIN_PATH,
                         AGENT_INFO_PATH, AGENT_DEFAULT_PORT, BROKER_DEFAULT_PORT)
from core import xray_manager

LAUNCHER = "/usr/local/bin/AX-Scanner"


def _ports():
    ports = {AGENT_DEFAULT_PORT, BROKER_DEFAULT_PORT}
    try:
        with open(AGENT_INFO_PATH) as f:
            d = json.load(f)
        ports |= {d.get("port"), d.get("broker_port")}
    except Exception:
        pass
    return {p for p in ports if p}


def _listening(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        return True
    except OSError:
        return False


def _our_xray_running():
    r = subprocess.run(["pgrep", "-f", XRAY_BIN_PATH], capture_output=True, text=True)
    return bool(r.stdout.strip())


def run(ui):
    ui.warn(f"This will completely remove {BASE_DIR}, the '{LAUNCHER}' command and the "
            "AX-Scanner service, and stop every AX-Scanner process (including its private "
            "xray-core). It does NOT touch your panel or the panel's xray-core.")
    confirm = input(" Type 'yes' to confirm uninstall: ").strip().lower()
    if confirm != "yes":
        ui.info("Uninstall cancelled.")
        return

    ports = _ports()

    if os.path.isfile(SYSTEMD_UNIT_PATH):
        ui.info("Stopping and removing the AX-Scanner Agent systemd service...")
        subprocess.run(["systemctl", "stop", SYSTEMD_UNIT_NAME], check=False)
        subprocess.run(["systemctl", "disable", SYSTEMD_UNIT_NAME], check=False)
        try:
            os.remove(SYSTEMD_UNIT_PATH)
        except FileNotFoundError:
            pass
        subprocess.run(["systemctl", "daemon-reload"], check=False)

    ui.info("Stopping any lingering AX-Scanner xray processes...")
    xray_manager.kill_all_orphans()

    if os.path.isdir(BASE_DIR):
        ui.info(f"Deleting {BASE_DIR} (binary, keys, certificate, token, caches)...")
        shutil.rmtree(BASE_DIR, ignore_errors=True)
    if os.path.isfile(LAUNCHER):
        os.remove(LAUNCHER)

    print()
    ui.info("Verification:")
    checks = [
        (f"{BASE_DIR} removed", not os.path.exists(BASE_DIR)),
        ("systemd service removed", not os.path.exists(SYSTEMD_UNIT_PATH)),
        ("'AX-Scanner' command removed", not os.path.exists(LAUNCHER)),
        ("no AX-Scanner xray process running", not _our_xray_running()),
        ("agent/probe ports closed", not any(_listening(p) for p in ports)),
    ]
    for label, good in checks:
        (ui.ok if good else ui.err)(label)
    if all(g for _, g in checks):
        ui.ok("AX-Scanner is completely gone from this server. Also run "
              "'probe_client.py --uninstall' on your own computer(s) to clean those too.")
    else:
        ui.warn("Something is left — see the red lines above.")
