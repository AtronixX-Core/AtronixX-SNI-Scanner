"""
AX-Scanner :: carriers.py

Handles: showing the carrier picker, and doing a *live* IP -> ASN/ISP
lookup on the machine's own public IP so we can warn the operator if
they picked "Irancell" but the box is actually, say, on Shatel.

We never silently trust the live lookup over the user's choice (the
live lookup itself can be wrong/rate-limited) — we just warn and let
them confirm.
"""

import json
import urllib.request

from core import probe_session
from core.config import CARRIERS


def _get_json(url, timeout=5):
    """Runs on the probe client when one is connected, so the IP/ISP we
    see is the REAL carrier's, not the server's."""
    if probe_session.active():
        return probe_session.job("http_get_json", {"url": url, "timeout": timeout},
                                 timeout=timeout + 10)["json"]
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def get_public_ip():
    try:
        return _get_json("https://api.ipify.org?format=json")["ip"]
    except Exception:
        return None


def lookup_isp(ip):
    """Returns dict with 'org', 'asn', 'isp' or None on failure."""
    if not ip:
        return None
    try:
        url = f"http://ip-api.com/json/{ip}?fields=status,message,isp,org,as,query"
        data = _get_json(url)
        if data.get("status") != "success":
            return None
        asn = ""
        if data.get("as"):
            # ip-api "as" field looks like "AS44244 Irancell..."
            parts = data["as"].split(" ", 1)
            asn = parts[0].replace("AS", "")
        return {"org": data.get("org", ""), "isp": data.get("isp", ""), "asn": asn}
    except Exception:
        return None


def detect_and_confirm_carrier(selected_carrier_key, ui):
    """
    Does a live lookup and warns (does not block) if it looks like a
    mismatch with what the user picked from the menu.
    Returns True to proceed, False if the user wants to abort.
    """
    source = "your computer (probe client)" if probe_session.active() else "this server"
    ui.info(f"Verifying the real ISP/ASN of {source} before testing...")
    ip = get_public_ip()
    if not ip:
        ui.warn("Could not determine public IP (no internet, or the lookup service is blocked). Proceeding on trust.")
        return True

    result = lookup_isp(ip)
    if not result:
        ui.warn(f"Public IP detected ({ip}) but ISP lookup failed. Proceeding on trust.")
        return True

    selected = next((c for c in CARRIERS if c["key"] == selected_carrier_key), None)
    hints = selected["asn_hints"] if selected else []

    ui.info(f"Detected: {result['isp'] or result['org']}  (ASN {result['asn']}, IP {ip})")

    if selected_carrier_key == "other":
        return True

    if hints and result["asn"] not in hints:
        ui.warn(
            f"This looks like it might NOT be {selected['label']} "
            f"(detected ASN {result['asn']} / {result['isp']}). "
            "Results will be mislabeled if this connection isn't actually that carrier."
        )
        answer = input(" Continue anyway? [y/N]: ").strip().lower()
        return answer == "y"

    ui.ok(f"Confirmed — this connection matches {selected['label']}.")
    return True


def choose_carrier(ui):
    print()
    ui.info("Select the carrier you are CURRENTLY connected through on this device:")
    print()
    for i, c in enumerate(CARRIERS, 1):
        print(f"   {i}) {c['emoji']}  {c['label']}")
    print()
    while True:
        choice = input(" > ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(CARRIERS):
            return CARRIERS[int(choice) - 1]
        ui.err("Invalid choice, try again.")
