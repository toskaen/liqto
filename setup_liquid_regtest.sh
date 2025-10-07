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

# Start elementsd in regtest mode
elementsd -regtest -daemon \
  -rpcuser=user \
  -rpcpassword=pass \
  -rpcport=18884 \
  -fallbackfee=0.00001 \
  -txindex=1

echo "Waiting for elementsd to start..."
sleep 5

# Create wallet if it is not already present
if ! elements-cli -regtest listwallets | grep -q "test_wallet"; then
  elements-cli -regtest createwallet "test_wallet" >/dev/null
fi

echo "Liquid regtest ready!"
echo "Run: python rfq_otc.py"
