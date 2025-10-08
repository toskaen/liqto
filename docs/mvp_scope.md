# LIQTO MVP Scope & Runbook

This document consolidates the minimum viable product (MVP) definition, validation steps, and positioning notes used for the PlanB submission. It is intentionally concise so a reviewer can match each requirement to the working code in minutes.

## Product Intent
- **Audience:** OTC desks, market makers, and institutional clients that require private, bilateral execution on the Liquid Network.
- **Problem:** Existing OTC RFQ flows rely on opaque chats or custodial venues that cannot guarantee privacy nor atomic settlement.
- **Solution Statement:** Provide a one-click demonstrator that issues an RFQ, receives dealer quotes, and settles atomically via a Confidential Transaction protected by Miniscript-based recovery logic.

## Feature Matrix
| Capability | Code Anchor | Validation Command |
|------------|-------------|--------------------|
| Confidential settlement via blinded PSET | `LiquidRFQProtocol.create_atomic_settlement` | `python3 rfq_otc.py` → look for `✅ Settlement complete!` |
| Bilateral signatures with reclaim path | `LiquidRFQProtocol.build_joint_timelocked_address` | `elements-cli -regtest validateaddress <protected_address>` |
| Authentic Liquid RPC integration | `LiquidRFQProtocol.__init__` / `AuthServiceProxy` | `elements-cli -regtest getblockcount` while demo runs |
| Deterministic quoting spread | `OTCDesk.process_rfq` | Inspect printed dealer quotes in demo output |

## MVP Acceptance Criteria
1. **End-to-end RFQ flow:** The demo must bootstrap a regtest, issue an RFQ, receive at least one valid quote, and complete settlement without manual transaction crafting.
2. **Privacy proof points:** All settlement outputs in the broadcast transaction are blinded; no clear-text amounts leak on-chain.
3. **Client protection:** The settlement descriptor grants the client a time-delayed reclaim path (`older(csv_delay)` in Miniscript).
4. **Operational clarity:** A new operator can start from `git clone`, follow the README, and complete a trade in under ten minutes.

## Operational Runbook
1. Launch regtest – `bash setup_liquid_regtest.sh`.
2. Install dependencies – `pip install -r requirements.txt`.
3. Execute demo – `python3 rfq_otc.py`.
4. Inspect transaction – `elements-cli -regtest gettransaction <txid>`.
5. Validate descriptor – `elements-cli -regtest validateaddress <protected_address>`.

If a step fails, restart `elementsd` and re-run from step 1. Regtest data lives under `~/.elements/regtest` and can be safely deleted to reset.

## PlanB Positioning Notes
- **Deep & private liquidity:** The flow assumes multiple dealers, each sourcing their own inventory, while the settlement remains confidential. Liquidity depth is represented by the ability to plug additional OTCDesk instances without altering the protocol layer.
- **RFQ-first design:** Quotes are structured as signed JSON messages (`Quote` dataclass), which can be transported over PlanB's preferred channels (Nostr relays, VPN links, or bespoke APIs) without altering settlement logic.
- **Sound engineering:** No artificial mocks—every step talks to Elements Core. The code surfaces errors explicitly (e.g., insufficient funds) so integration partners can extend handling logic confidently.

## Suggested Enhancements
- Integrate a persistent RFQ registry (SQLite or Postgres) to track quote history for compliance teams.
- Add a Nostr bridge service that publishes RFQs and listens for encrypted dealer responses.
- Expand asset support by loading issuer data from Liquid's asset registry to auto-label quotes.

Keeping these next steps scoped ensures the MVP remains demonstrably complete while pointing to clear growth vectors for the PlanB review.
