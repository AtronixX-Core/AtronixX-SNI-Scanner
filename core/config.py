"""
AX-Scanner :: config.py

Every path/port/name in this file is deliberately namespaced and kept
separate from anything a panel (e.g. Pasargad) installs, so this tool
can never collide with a running production xray-core instance.
"""

import os

# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------
# Everything AX-Scanner ever touches lives under this one directory.
# Nothing is ever written outside of it, and `uninstall` simply erases it.
BASE_DIR = os.environ.get("AX_SCANNER_HOME", "/opt/ax-scanner")

BIN_DIR = os.path.join(BASE_DIR, "bin")
RUN_DIR = os.path.join(BASE_DIR, "run")          # ephemeral configs / pid files
LOG_DIR = os.path.join(BASE_DIR, "logs")
CACHE_DIR = os.path.join(BASE_DIR, "cache")      # discovered domain lists, etc.

# The xray-core binary AX-Scanner downloads is renamed on purpose so it
# never shares a name (or a systemd unit, or a config path) with whatever
# the panel already runs.
XRAY_BIN_NAME = "ax-scanner-xray"
XRAY_BIN_PATH = os.path.join(BIN_DIR, XRAY_BIN_NAME)

SYSTEMD_UNIT_NAME = "ax-scanner-agent.service"
SYSTEMD_UNIT_PATH = f"/etc/systemd/system/{SYSTEMD_UNIT_NAME}"

PID_FILE = os.path.join(RUN_DIR, "agent.pid")

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------
# Port range AX-Scanner is allowed to bind ephemeral test servers on.
# Chosen deliberately far away from common panel/xray default ports
# (443, 2053, 2083, 2087, 8443, etc.) to minimize any chance of collision.
EPHEMERAL_PORT_MIN = 41000
EPHEMERAL_PORT_MAX = 41999

# Default port the persistent backend Agent listens on (on the target/
# "Germany" server). Change during setup if it clashes with something.
AGENT_DEFAULT_PORT = 41080

# Port the probe broker listens on (same service/process as the Agent).
# Your own computer's probe client connects OUT to this port and stays
# connected; every carrier-path test is then executed on that computer.
BROKER_DEFAULT_PORT = 41081
AGENT_INFO_PATH = os.path.join(BASE_DIR, "agent.json")   # {"port":..., "broker_port":...}
TLS_CERT_PATH = os.path.join(BASE_DIR, "broker_cert.pem")
TLS_KEY_PATH = os.path.join(BASE_DIR, "broker_key.pem")

# Timeouts (seconds)
TCP_CONNECT_TIMEOUT = 4
TLS_HANDSHAKE_TIMEOUT = 5
REALITY_TEST_TIMEOUT = 8
AGENT_HTTP_TIMEOUT = 10

# ---------------------------------------------------------------------------
# Test-run tuning (per the agreed spec)
# ---------------------------------------------------------------------------
STAGE1_PASSES = 3          # repeat TCP+TLS check this many times per domain
STAGE1_MAX_CONCURRENCY = 40

STAGE2_CANDIDATE_COUNT = 50   # only the top N from stage 1 get a real Reality test
FINAL_RESULT_COUNT = 20       # how many rows the user sees at the end

DISCOVERY_POOL_SIZE = 400     # how many candidate domains discovery should gather

# ---------------------------------------------------------------------------
# Branding
# ---------------------------------------------------------------------------
PRODUCT_NAME = "AtronixX-SNI-Scanner"
BRAND_LINE = "by AtronixX-Core"
CHANNEL_HANDLE = "@AtronixX_Core"
SUPPORT_HANDLE = "@AtronixX_Support"
CLI_COMMAND = "AX-Scanner"
VERSION = "1.0.0"

# NOTE: asn_hints below are best-effort reference points only (used to give
# the ISP-mismatch warning something to compare against). ASN assignments
# do change over time — carriers.py always does a *live* IP-to-ISP lookup
# and shows you the actual detected org name, it does not trust this list
# blindly. Update/expand this list if you find it's out of date.
CARRIERS = [
    {"key": "irancell", "label": "Irancell (MTN)", "emoji": "📶", "asn_hints": ["44244", "197207"]},
    {"key": "hamrah_aval", "label": "Hamrah Aval (MCI)", "emoji": "📱", "asn_hints": ["197207", "44244", "43754"]},
    {"key": "rightel", "label": "RighTel", "emoji": "📡", "asn_hints": ["57218"]},
    {"key": "mokhaberat", "label": "Mokhaberat / TCI (ADSL)", "emoji": "☎️", "asn_hints": ["58224", "12880"]},
    {"key": "shatel", "label": "Shatel", "emoji": "🌐", "asn_hints": ["31549"]},
    {"key": "other", "label": "Other / Custom ISP", "emoji": "🔧", "asn_hints": []},
]


def ensure_dirs():
    for d in (BASE_DIR, BIN_DIR, RUN_DIR, LOG_DIR, CACHE_DIR):
        os.makedirs(d, exist_ok=True)
