"""
AX-Scanner :: probe_link.py

On a probe device (a phone/box currently on some carrier's SIM), we need
to know how to reach the backend Agent running on the target/"Germany"
server: its public IP, the Agent's port, and its auth token.

Asked once, cached locally under BASE_DIR/probe_link.json so the operator
doesn't have to retype it every single carrier test.
"""

import json
import os

from core.config import BASE_DIR

LINK_PATH = os.path.join(BASE_DIR, "probe_link.json")


def load():
    if os.path.isfile(LINK_PATH):
        try:
            with open(LINK_PATH) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save(host, port, token):
    os.makedirs(BASE_DIR, exist_ok=True)
    with open(LINK_PATH, "w") as f:
        json.dump({"host": host, "port": port, "token": token}, f)
    os.chmod(LINK_PATH, 0o600)


def get_or_prompt(ui):
    link = load()
    if link:
        ui.info(f"Using saved backend server: {link['host']}:{link['port']}")
        change = input(" Use a different server this time? [y/N]: ").strip().lower()
        if change != "y":
            return link

    print()
    ui.info("Enter the backend server's connection details "
             "(shown when you set up the Agent on your target/Germany server):")
    host = input(" Server public IP or hostname: ").strip()
    port = input(" Agent port [41080]: ").strip() or "41080"
    token = input(" Agent auth token: ").strip()
    save(host, int(port), token)
    return {"host": host, "port": int(port), "token": token}
