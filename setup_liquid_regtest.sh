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
REGTEST_DIR="${DATA_ROOT%/}/regtest"
WALLET_NAME="${LIQUID_WALLET_NAME:-test_wallet}"

cli() {
  elements-cli -regtest \
    -datadir="${DATA_ROOT}" \
    -rpcuser="${RPC_USER}" \
    -rpcpassword="${RPC_PASSWORD}" \
    -rpcport="${RPC_PORT}" "$@"
}

mkdir -p "${REGTEST_DIR}"

echo "Ensuring elementsd is running (data dir: ${REGTEST_DIR})..."
if ! cli getblockchaininfo >/dev/null 2>&1; then
  elementsd -regtest -daemon \
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
