# LIQTO — Confidential OTC RFQ Demo on Liquid (regtest)

A compact, auditable demo that runs a full **RFQ → Quote → Atomic settlement** flow on a local Liquid-style chain (Elements **regtest**). It uses **Confidential Transactions (CT)**, **PSET**, and a **CSV timelock** reclaim path — no custodians, amounts are blinded.

---

## What’s in this repo

* `rfq_otc.py` – the end-to-end demo: creates RFQ, gathers two quotes, builds a blinded joint-settlement PSET with a CSV reclaim path, signs, and broadcasts.
* Uses **blech32** addresses for on-chain payments and **legacy (P2PKH)** addresses for message signing (`signmessage` / `verifymessage`), which Elements requires. The script handles this automatically.

---

## Prerequisites

* **Bitcoin Core** (unpacked somewhere in `$HOME/bitcoin-<ver>/bin`)
* **Elements Core** (on your PATH; tested with 23.x)
* **Python 3.10+** and `python-bitcoinrpc`

  ```bash
  pip install -r requirements.txt
  ```

---

## 1) Start Bitcoin Core on an isolated regtest

This keeps mainnet/testnet untouched by using a separate datadir.

```bash
# Paths
BTC="$HOME/bitcoin-28.1/bin"   # adjust if needed

# Dedicated datadir + config
mkdir -p ~/.bitcoin-regtest
cat > ~/.bitcoin-regtest/bitcoin.conf <<'EOF'
regtest=1
daemon=1
txindex=1

[regtest]
rpcuser=user3
rpcpassword=password3
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
rpcport=18443
port=18444
fallbackfee=0.0002
EOF

# Start + wait
"$BTC/bitcoind" -datadir="$HOME/.bitcoin-regtest" -daemon
"$BTC/bitcoin-cli" -datadir="$HOME/.bitcoin-regtest" -regtest -rpcwait getblockchaininfo

# Create wallet and mine spendable coins
"$BTC/bitcoin-cli" -datadir="$HOME/.bitcoin-regtest" -regtest createwallet dev
ADDR=$("$BTC/bitcoin-cli" -datadir="$HOME/.bitcoin-regtest" -regtest -rpcwallet=dev getnewaddress)
"$BTC/bitcoin-cli" -datadir="$HOME/.bitcoin-regtest" -regtest generatetoaddress 101 "$ADDR"
"$BTC/bitcoin-cli" -datadir="$HOME/.bitcoin-regtest" -regtest -rpcwallet=dev getbalances
```

---

## 2) Start Elements (Liquid) regtest with peg-in validation

We’ll peg in regtest BTC → L-BTC on Elements.

```bash
# Clean chain if needed (optional)
pkill -f elementsd || true
rm -rf ~/.elements/elementsregtest

# Start Elements with mainchain RPC wired up for peg-ins
elementsd -daemon -chain=elementsregtest -rpcport=18884 \
  -txindex=1 -acceptnonstdtxn=1 -fallbackfee=0.0002 \
  -rpcuser=user -rpcpassword=pass \
  -validatepegin=1 \
  -mainchainrpchost=127.0.0.1 \
  -mainchainrpcport=18443 \
  -mainchainrpcuser=user3 \
  -mainchainrpcpassword=password3

# Wait for RPC
elements-cli -rpcwait -chain=elementsregtest -rpcport=18884 -rpcuser=user -rpcpassword=pass -getinfo
```

Create a wallet that supports `getpeginaddress` (non-descriptor):

```bash
elements-cli -chain=elementsregtest -rpcport=18884 -rpcuser=user -rpcpassword=pass \
  -named createwallet wallet_name=peg descriptors=false disable_private_keys=false blank=false
```

---

## 3) Peg in BTC to L-BTC

```bash
# Get peg-in address from Elements
PEGJSON=$(elements-cli -chain=elementsregtest -rpcport=18884 -rpcuser=user -rpcpassword=pass -rpcwallet=peg getpeginaddress)
PEGADDR=$(echo "$PEGJSON" | jq -r '.mainchain_address')

# Send 1 BTC on regtest to the peg-in address, then confirm 10 blocks
bc() { "$HOME/bitcoin-28.1/bin/bitcoin-cli" -datadir="$HOME/.bitcoin-regtest" -regtest "$@"; }
TXID=$(bc -rpcwallet=dev sendtoaddress "$PEGADDR" 1)
ADDR=$(bc -rpcwallet=dev getnewaddress)
bc generatetoaddress 10 "$ADDR"

# Produce proof + raw
PROOF=$(bc gettxoutproof '["'"$TXID"'"]')
RAW=$(bc getrawtransaction "$TXID")

# Claim on Elements, then confirm 1 block
CLAIMTX=$(elements-cli -chain=elementsregtest -rpcport=18884 -rpcuser=user -rpcpassword=pass -rpcwallet=peg claimpegin "$RAW" "$PROOF")
MADDR=$(elements-cli -chain=elementsregtest -rpcport=18884 -rpcuser=user -rpcpassword=pass -rpcwallet=peg getnewaddress "" legacy)
UADDR=$(elements-cli -chain=elementsregtest -rpcport=18884 -rpcuser=user -rpcpassword=pass -rpcwallet=peg getaddressinfo "$MADDR" | jq -r '.unconfidential // .address')
elements-cli -chain=elementsregtest -rpcport=18884 -rpcuser=user -rpcpassword=pass generatetoaddress 1 "$UADDR"

# Check L-BTC balance
elements-cli -chain=elementsregtest -rpcport=18884 -rpcuser=user -rpcpassword=pass -rpcwallet=peg getbalances
```

---

## 4) Run the LIQTO demo

Point the script at your **peg** wallet:

```bash
cd ~/Desktop/liqto
export ELEMENTS_RPC="http://user:pass@127.0.0.1:18884/wallet/peg"
python3 rfq_otc.py
```

You should see:

* Pre-flight checks (chain/wallet/RPCs)
* Creation of **pay** (blech32) and **signing** (legacy) addresses
* Issuance of a demo asset (as L-USDt)
* Two dealer quotes
* Creation of a blinded PSET with a CSV timelock
* Signing, broadcast, and a settlement TXID

To inspect the transaction:

```bash
TXID=<printed-txid>
elements-cli -chain=elementsregtest -rpcport=18884 -rpcuser=user -rpcpassword=pass gettransaction "$TXID"
# Amounts should be blinded (value commitments instead of clear amounts).
```

---

## Notes on addresses & signing

* **On-chain settlement** uses **blech32** confidential addresses.
* **Message signing** uses **legacy (P2PKH)** addresses because Elements’ `signmessage`/`verifymessage` operate on legacy keys.
* The script **creates and binds both** (pay + signing) per participant; you don’t need to do anything extra.

---

## Troubleshooting

* **“Address does not refer to key”**
  You tried to sign with a confidential address. The script now uses a separate legacy signing address; re-run the demo.

* **Fee estimation failed (Bitcoin regtest)**
  Ensure `fallbackfee=0.0002` is present in `~/.bitcoin-regtest/bitcoin.conf` (under `[regtest]`), or set a manual fee:

  ```bash
  "$BTC/bitcoin-cli" -datadir="$HOME/.bitcoin-regtest" -regtest -rpcwallet=dev settxfee 0.0001
  ```

* **Elements lock / already running**
  Only one `elementsd` instance per datadir. If needed:

  ```bash
  pkill -f elementsd
  rm -f ~/.elements/elementsregtest/.lock
  ```

* **Old Elements builds**
  Some releases use `-chain=liquidregtest` instead of `elementsregtest`. Adjust the `-chain` flag and CLI calls accordingly.

---

## Why this matters (quick)

* **Privacy by default** – CT hides sizes from observers.
* **No escrow risk** – atomic settlement via PSET.
* **Safety valve** – CSV timelock lets the client reclaim funds if a dealer stalls.
* **Composable RFQ** – signed JSON payloads can ride over Nostr/APIs later without changing settlement.

Happy testing 💚
