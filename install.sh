#!/usr/bin/env bash
#
# AX-Scanner installer
# Target: Ubuntu 24.04. Everything is installed under /opt/ax-scanner
# and is fully isolated from any panel (Pasargad, etc.) already on this
# box — separate binary, separate ports, separate systemd unit name.
#
set -euo pipefail

AX_HOME="/opt/ax-scanner"
APP_DIR="${AX_HOME}/app"

if [[ $EUID -ne 0 ]]; then
  echo "Please run this installer with sudo/root." >&2
  exit 1
fi

echo "== AX-Scanner installer =="
echo

echo "[1/4] Installing base packages (python3, curl, openssl, unzip)..."
apt-get update -qq
apt-get install -y -qq python3 curl openssl unzip >/dev/null

echo "[2/4] Setting up isolated directory at ${AX_HOME}..."
mkdir -p "${APP_DIR}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "${SCRIPT_DIR}/." "${APP_DIR}/"
rm -rf "${APP_DIR}/.git" 2>/dev/null || true

echo "[3/4] Creating the 'AX-Scanner' launcher command..."
cat > /usr/local/bin/AX-Scanner <<EOF
#!/usr/bin/env bash
exec python3 "${APP_DIR}/ax_scanner.py" "\$@"
EOF
chmod +x /usr/local/bin/AX-Scanner

echo "[4/4] Done."
echo
echo "AX-Scanner is installed. Run it with:"
echo
echo "    AX-Scanner"
echo
echo "Nothing has been started yet, and nothing here touches any existing"
echo "panel or xray-core install. Next steps:"
echo "  1) AX-Scanner -> option 1 : set up the Agent on this server"
echo "  2) AX-Scanner -> option 2 : shows the exact command to run ONCE on your own"
echo "     Windows/Linux computer (probe_client.py, copy it from ${APP_DIR})"
echo "  3) AX-Scanner -> option 3 or 4 : run the carrier test"
