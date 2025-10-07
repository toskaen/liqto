## What This Actually Does

Real, working RFQ protocol for confidential OTC settlement on Liquid Network using:
- **Confidential Transactions** - Amounts hidden via Pedersen commitments
- **PSETs** - Atomic swaps eliminate escrow risk  
- **Real Elements RPC** - Not pseudocode, actual blockchain operations
- **2-minute finality** - Liquid's 1-minute blocks with 1-block confirmation

## Run It
```bash
# 1. Start Liquid regtest
bash setup_liquid_regtest.sh

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run demo
python rfq_otc.py
