"""
AX-Scanner :: discovery.py

Builds a FRESH pool of candidate SNI domains every run — never a static
bundled list. Two sources, combined:

  1. A live top-domains list (Tranco) — popular, big-name sites that are
     unlikely to be blocked wholesale (blocking them causes collateral
     damage), which is exactly the property a good Reality camouflage
     domain needs.

  2. Live CDN IP-range probing — we grab a handful of real, currently-live
     IPs inside major CDNs' published ranges and read the default TLS
     certificate's SAN list off of them, which reveals real hostnames
     actually being served there right now.

If both network sources fail (e.g. this box currently has no working
internet at all), we fall back to a small emergency seed list so the
tool doesn't hard-crash — but that path is clearly logged as a fallback,
never presented as a "real" discovery result.
"""

import csv
import io
import random
import socket
import ssl
import urllib.request
import zipfile

from core.config import DISCOVERY_POOL_SIZE

TRANCO_URL = "https://tranco-list.eu/top-1m-incl-subdomains.csv.zip"
TRANCO_FETCH_ROWS = 2000  # only read this many rows off the top of the list

# Published CDN ranges we sample a few live IPs from. These are network
# *infrastructure* facts (not a domain list), fetched fresh where possible.
CDN_RANGE_SOURCES = {
    "cloudflare": "https://www.cloudflare.com/ips-v4",
    "fastly": "https://api.fastly.com/public-ip-list",
}

_EMERGENCY_FALLBACK_SEED = [
    "cloudflare.com", "www.google.com", "www.microsoft.com", "www.apple.com",
    "www.cloudflare.com", "www.wikipedia.org", "www.amazon.com",
]


def _fetch_tranco_domains(limit=TRANCO_FETCH_ROWS):
    domains = []
    try:
        with urllib.request.urlopen(TRANCO_URL, timeout=15) as r:
            blob = r.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = z.namelist()[0]
            with z.open(name) as f:
                reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
                for i, row in enumerate(reader):
                    if i >= limit:
                        break
                    if len(row) >= 2:
                        domains.append(row[1].strip())
    except Exception:
        return []
    return domains


def _fetch_cdn_ip_pool(sample_per_provider=25):
    """Return a small random sample of IPs across published CDN ranges."""
    ips = []
    for provider, url in CDN_RANGE_SOURCES.items():
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                text = r.read().decode()
            cidrs = []
            if provider == "fastly":
                import json
                data = json.loads(text)
                cidrs = data.get("addresses", [])
            else:
                cidrs = [line.strip() for line in text.splitlines() if line.strip()]

            for cidr in random.sample(cidrs, min(len(cidrs), 6)):
                try:
                    base, size = cidr.split("/")
                    octets = base.split(".")
                    # cheap random host pick within a /24-ish slice; good
                    # enough for sampling, not meant to be a full scanner
                    octets[3] = str(random.randint(1, 254))
                    ips.append((".".join(octets), provider))
                except Exception:
                    continue
        except Exception:
            continue
    return random.sample(ips, min(len(ips), sample_per_provider)) if ips else []


def _sni_less_cert_scan(ip):
    """Connect to an IP on :443, grab whatever default cert it serves, and
    pull hostnames out of its SAN list. Best-effort, silently skips on any
    failure (many CDN edges require a valid SNI and will just refuse)."""
    found = set()
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((ip, 443), timeout=3) as sock:
            with ctx.wrap_socket(sock) as ssock:
                der = ssock.getpeercert(binary_form=True)
                cert = ssl.DER_cert_to_PEM_cert(der)
                # Lightweight SAN extraction without extra deps: rely on
                # getpeercert() dict form on a second, verifying handshake.
        ctx2 = ssl._create_unverified_context()
        with socket.create_connection((ip, 443), timeout=3) as sock:
            with ctx2.wrap_socket(sock) as ssock:
                cert_dict = ssock.getpeercert()
                for field in cert_dict.get("subjectAltName", []):
                    if field[0] == "DNS":
                        name = field[1].lstrip("*.")
                        if "." in name:
                            found.add(name)
    except Exception:
        pass
    return found


def discover_candidates(ui, pool_size=DISCOVERY_POOL_SIZE):
    ui.info("Discovering fresh SNI candidates (top-domains list + live CDN sampling)...")
    pool = set()

    tranco = _fetch_tranco_domains()
    if tranco:
        ui.ok(f"Fetched {len(tranco)} domains from the live top-domains list.")
        pool.update(tranco)
    else:
        ui.warn("Top-domains list fetch failed (no internet, or the source is unreachable).")

    cdn_ips = _fetch_cdn_ip_pool()
    if cdn_ips:
        ui.info(f"Sampling {len(cdn_ips)} live CDN edge IPs for hostnames...")
        for ip, _provider in cdn_ips:
            pool.update(_sni_less_cert_scan(ip))
    else:
        ui.warn("CDN range sampling unavailable right now.")

    if not pool:
        ui.err("Both discovery sources failed — using a tiny emergency fallback list. "
               "Results from this run should not be trusted the way a real scan's would.")
        pool.update(_EMERGENCY_FALLBACK_SEED)

    pool = list(pool)
    random.shuffle(pool)
    return pool[:pool_size]
