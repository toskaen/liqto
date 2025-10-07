#!/bin/bash
# setup_liquid_regtest.sh - Start Liquid regtest for testing

# Start elementsd in regtest mode
elementsd -regtest -daemon \
  -rpcuser=user \
  -rpcpassword=pass \
  -rpcport=18884 \
  -fallbackfee=0.00001 \
  -txindex=1

echo "Waiting for elementsd to start..."
sleep 5

# Create wallet
elements-cli -regtest createwallet "test_wallet"

echo "Liquid regtest ready!"
echo "Run: python rfq_otc.py"
