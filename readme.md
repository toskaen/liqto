# LIQTO: Confidential OTC RFQ Demo on Liquid

## Overview
LIQTO demonstrates a functioning request-for-quote (RFQ) flow for bilateral, confidential settlement on the Liquid Network. The project focuses on showing how Bitcoin-adjacent infrastructure can deliver fast, final, and private over-the-counter trades without requiring custodial intermediaries.

## Core Problem: Transparent Liquidity & Limited Interaction
Most OTC desks currently depend on fragmented chat channels or opaque spreadsheets, creating two complementary issues:
- **Transparent liquidity gaps** – Order intent is hidden from the wider market, reducing the ability to source competitive quotes.
- **Limited interaction options** – Negotiations happen via manual outreach, delaying price discovery and eroding trust.

LIQTO explores how on-chain privacy tech and open coordination layers can address both challenges while keeping counterparties in control of their keys and trade data.

## Current Capabilities
This repository already contains a real RFQ sequence using core Liquid primitives:
- **Confidential Transactions** ensure amounts remain private through Pedersen commitments.
- **Partially Signed Elements Transactions (PSETs)** deliver atomic settlement and remove escrow risk.
- **Miniscript-guarded settlement outputs** use `OP_CSV` timelocks so the client can reclaim funds if a dealer stalls, showcasing Elements' extended opcode support.
- **Native Elements RPC calls** drive genuine blockchain operations instead of simulations.
- **Confidential `blech32` addresses** are used for every participant to stay aligned with Liquid best practices.
- **Two-minute finality** by leveraging Liquid’s one-minute blocks with a single confirmation target.

The `rfq_otc.py` script wires these pieces together to demonstrate an end-to-end trade on Liquid regtest.

## Proposed Solution Extensions
To unlock broader liquidity while keeping privacy guarantees, we propose augmenting the demo with open coordination concepts:

### Trade Matching via Nostr Events
- Publish anonymized RFQs as Nostr events, allowing market makers to subscribe without revealing counterparty identities.
- Use event tagging to signal asset pairs, size bands, expiry windows, and reputational metadata.
- Allow responders to broadcast encrypted quotes back to the requester using Nostr direct messages, which then transition into the existing PSET workflow.
- Maintain settlement privacy by executing only the matched trades on Liquid; unmatched intents remain ephemeral in the Nostr relay ecosystem.

### Additional Collaboration Ideas
- Introduce reputation scoring for liquidity providers using signed attestations or proof-of-fulfillment events.
- Layer in rate-limiting or staking mechanics to reduce spam while preserving permissionless access.
- Explore cross-market data feeds to benchmark quotes against public markets for transparency.

## Getting Started
### Prerequisites
- Elements Core (`elementsd` / `elements-cli`) v0.21.0.3 or newer available in your `PATH`.
- Python 3.11 or later.

### Run the Demo
```bash
# 1. Start Liquid regtest
bash setup_liquid_regtest.sh

# 2. (Optional) Review dependencies
pip install -r requirements.txt

# 3. Execute the RFQ example
python3 rfq_otc.py

# 4. Inspect the blinded settlement transaction (optional)
elements-cli -regtest gettransaction <txid>
```

## Next Steps
Community contributions are welcome to prototype the Nostr trade-matching layer, integrate additional liquidity sources, or refine the UX for institutional desks. Feel free to open issues, share feedback, or suggest interoperable designs.
