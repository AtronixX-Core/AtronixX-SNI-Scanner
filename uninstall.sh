#!/usr/bin/env bash
#
# AX-Scanner uninstaller — complete, isolated removal.
# Safe to run even if the install partially failed; only ever touches
# paths under /opt/ax-scanner, /usr/local/bin/AX-Scanner, and the
# ax-scanner-agent.service systemd unit — never anything belonging to a
# panel or its xray-core.
#
set -uo pipefail

AX_HOME="/opt/ax-scanner"
UNIT_NAME="ax-scanner-agent.service"

if [[ $EUID -ne 0 ]]; then
  echo "Please run this with sudo/root." >&2
  exit 1
fi

echo "Stopping any AX-Scanner processes..."
pkill -f "${AX_HOME}/bin/ax-scanner-xray" 2>/dev/null || true

if systemctl list-unit-files | grep -q "${UNIT_NAME}"; then
  echo "Stopping and removing the AX-Scanner Agent service..."
  systemctl stop "${UNIT_NAME}" 2>/dev/null || true
  systemctl disable "${UNIT_NAME}" 2>/dev/null || true
  rm -f "/etc/systemd/system/${UNIT_NAME}"
  systemctl daemon-reload
fi

echo "Removing ${AX_HOME}..."
rm -rf "${AX_HOME}"

echo "Removing launcher command..."
rm -f /usr/local/bin/AX-Scanner

echo "AX-Scanner has been completely removed. Your panel/xray-core is untouched."
