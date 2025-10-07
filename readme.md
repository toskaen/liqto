## What This Actually Does

Real, working RFQ protocol for confidential OTC settlement on Liquid Network using:
- **Confidential Transactions** - Amounts hidden via Pedersen commitments
- **PSETs** - Atomic swaps eliminate escrow risk
- **Real Elements RPC** - Not pseudocode, actual blockchain operations
- **2-minute finality** - Liquid's 1-minute blocks with 1-block confirmation

## Prerequisites

- Elements Core (elementsd / elements-cli) v0.21.0.3 or newer in your PATH
- Python 3.11+

## Run It
```bash
# 1. Start Liquid regtest
bash setup_liquid_regtest.sh

# 2. (Optional) Review requirements
pip install -r requirements.txt  # No external packages needed

# 3. Run demo
python3 rfq_otc.py

# (optional) Inspect the blinded settlement transaction
elements-cli -regtest gettransaction <txid>
```
