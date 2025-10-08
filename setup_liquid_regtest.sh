#!/bin/bash
# setup_liquid_regtest.sh - Start Liquid regtest for testing
set -euo pipefail

if ! command -v elementsd >/dev/null 2>&1; then
  echo "elementsd binary not found. Install Elements Core and ensure elementsd is in PATH." >&2
  exit 1
fi

if ! command -v elements-cli >/dev/null 2>&1; then
  echo "elements-cli binary not found. Install Elements Core and ensure elements-cli is in PATH." >&2
  exit 1
fi

RPC_USER="${LIQUID_RPC_USER:-user}"
RPC_PASSWORD="${LIQUID_RPC_PASSWORD:-pass}"
RPC_PORT="${LIQUID_RPC_PORT:-18884}"
DATA_ROOT="${LIQUID_DATA_DIR:-$HOME/.elements}"

# Default to the modern chain alias introduced in Elements Core 23.x while
# keeping backwards compatibility with the historic ``elementsregtest`` name.
# Users occasionally export ``LIQUID_CHAIN_NAME=regtest`` (Bitcoin's testing
# chain) which causes Elements to run in non-confidential mode and breaks
# asset issuance.  Guard against that misconfiguration so the Python demo does
# not fail later with a cryptic RPC 500 error.
DEFAULT_CHAIN="liquidregtest"
if [ "${LIQUID_CHAIN_NAME:-}" = "elementsregtest" ]; then
  DEFAULT_CHAIN="elementsregtest"
fi
CHAIN_NAME="${LIQUID_CHAIN_NAME:-$DEFAULT_CHAIN}"

if [ "${CHAIN_NAME}" = "regtest" ]; then
  echo "ERROR: LIQUID_CHAIN_NAME=regtest selects Bitcoin's regtest network." >&2
  echo "       Re-run without that override or set LIQUID_CHAIN_NAME=liquidregtest" >&2
  echo "       so Elements starts an issuance-capable chain." >&2
  exit 1
fi
CHAIN_DIR="${DATA_ROOT%/}/${CHAIN_NAME}"
WALLET_NAME="${LIQUID_WALLET_NAME:-test_wallet}"

cli() {
  elements-cli -chain="${CHAIN_NAME}" \
    -datadir="${DATA_ROOT}" \
    -rpcuser="${RPC_USER}" \
    -rpcpassword="${RPC_PASSWORD}" \
    -rpcport="${RPC_PORT}" "$@"
}

mkdir -p "${CHAIN_DIR}"

echo "Ensuring elementsd is running (data dir: ${CHAIN_DIR})..."
if ! cli getblockchaininfo >/dev/null 2>&1; then
  if pgrep -x elementsd >/dev/null 2>&1; then
    echo "Detected running elementsd process, but it is not reachable with" >&2
    echo "the configured credentials/chain (${CHAIN_NAME})." >&2
    echo "If this is a different Elements instance, stop it before proceeding" >&2
    echo "or ensure it was started with -chain=${CHAIN_NAME} and matches the" >&2
    echo "RPC configuration used by this script." >&2
  fi
  elementsd -chain="${CHAIN_NAME}" -daemon \
    -datadir="${DATA_ROOT}" \
    -rpcuser="${RPC_USER}" \
    -rpcpassword="${RPC_PASSWORD}" \
    -rpcport="${RPC_PORT}" \
    -fallbackfee=0.00001 \
    -txindex=1
  echo "Waiting for elementsd to start..."
fi

if ! cli -rpcwait -rpcwaittimeout=60 getblockchaininfo >/dev/null 2>&1; then
  echo "Failed to connect to elementsd RPC after waiting." >&2
  if [ -f "${CHAIN_DIR}/debug.log" ]; then
    echo "--- Tail of ${CHAIN_DIR}/debug.log ---" >&2
    tail -n 20 "${CHAIN_DIR}/debug.log" >&2 || true
    echo "--- End debug.log ---" >&2
  fi
  exit 1
fi

actual_chain=$(cli getblockchaininfo | awk -F'"' '/"chain"/ {print $4; exit}')
if [ "${actual_chain}" != "${CHAIN_NAME}" ]; then
  echo "ERROR: elementsd is running on '${actual_chain}', expected '${CHAIN_NAME}'." >&2
  echo "       Remove the existing data directory at ${CHAIN_DIR} or stop any" >&2
  echo "       conflicting daemon, then rerun this script." >&2
  exit 1
fi

if ! cli listwallets | grep -qx "${WALLET_NAME}"; then
  if cli -named createwallet wallet_name="${WALLET_NAME}" >/dev/null 2>&1; then
    echo "Created wallet ${WALLET_NAME}."
  else
    echo "Wallet ${WALLET_NAME} already exists, attempting to load..."
    cli loadwallet "${WALLET_NAME}" >/dev/null 2>&1 || true
  fi
fi

echo "Liquid regtest ready!"
echo "Run: python rfq_otc.py"
