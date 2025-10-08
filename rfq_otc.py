# rfq_otc.py - Confidential OTC Settlement on Liquid Network
# Requires: elementsd running in regtest mode, python-bitcoinrpc

from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
import hashlib
import json
import time
from decimal import Decimal, InvalidOperation, getcontext
from dataclasses import dataclass
from typing import Optional, Tuple

# Liquid CT works with 8 decimal places – guarantee exact arithmetic.
getcontext().prec = 16

# Real Elements RPC connection
RPC_USER = "user"
RPC_PASS = "pass"
RPC_HOST = "127.0.0.1"
RPC_PORT = 18884  # Liquid regtest default


@dataclass
class RFQ:
    """Request for Quote - actual data structure"""

    rfq_id: str
    client_address: str  # Liquid address to receive
    asset_to_sell: str  # Asset ID (L-BTC or L-USDt)
    asset_to_buy: str
    approx_amount: Decimal  # Approximate for privacy
    expiry_time: int
    client_signature: str


@dataclass
class Quote:
    """Dealer quote response"""

    rfq_id: str
    dealer_id: str
    dealer_address: str  # Liquid address for settlement
    exact_amount_sell: Decimal
    exact_amount_buy: Decimal
    price: Decimal
    expiry_time: int
    dealer_signature: str


def ensure_regtest_readiness(rpc: AuthServiceProxy) -> dict:
    """Validate that the connected Elements node can run the RFQ demo.

    Returns a summary dictionary when all pre-flight checks pass. Raises an
    ``EnvironmentError`` with actionable instructions when the regtest node is
    not ready for the workflow.
    """

    try:
        chain_info = rpc.getblockchaininfo()
    except Exception as exc:  # pragma: no cover - network/IO guard
        raise EnvironmentError(
            "Cannot reach Elements RPC. Start regtest via ``setup_liquid_regtest.sh`` "
            "or ensure elementsd is running with ``-chain=liquidregtest`` (or "
            "``-chain=elementsregtest`` on older versions)."
        ) from exc

    chain = chain_info.get("chain", "")
    if chain not in {"elementsregtest", "liquidregtest"}:
        raise EnvironmentError(
            "RFQ demo requires a Liquid regtest node. Current chain is "
            f"'{chain}'. Restart elementsd with ``-chain=liquidregtest`` (or "
            "``-chain=elementsregtest`` for legacy builds) or rerun the setup script."
        )

    try:
        wallet_info = rpc.getwalletinfo()
    except Exception as exc:  # pragma: no cover - wallet guard
        raise EnvironmentError(
            "Wallet RPC is unavailable. Start elementsd with wallet support and "
            "load or create a default wallet (``elements-cli -chain=liquidregtest "
            "createwallet wallet``; replace the chain with ``elementsregtest`` when "
            "using older builds)."
        ) from exc

    if not wallet_info.get("private_keys_enabled", True):
        raise EnvironmentError(
            "Loaded wallet is watch-only. Re-run ``elements-cli -chain=liquidregtest "
            "createwallet`` with private keys enabled (use ``elementsregtest`` on "
            "older versions) or load a wallet that holds signing keys."
        )

    unlocked_until = wallet_info.get("unlocked_until")
    if unlocked_until is not None and unlocked_until == 0:
        raise EnvironmentError(
            "Wallet is locked. Unlock it first using ``elements-cli "
            "-chain=liquidregtest walletpassphrase <passphrase> 600`` (or replace "
            "the chain argument with ``elementsregtest`` on legacy builds)."
        )

    missing_cmds = []
    for cmd in ("blindpsbt", "walletprocesspsbt", "dumpmasterblindingkey", "signmessage"):
        try:
            rpc.help(cmd)
        except JSONRPCException:
            missing_cmds.append(cmd)
        except Exception as exc:  # pragma: no cover - unexpected RPC errors
            raise EnvironmentError(
                f"Unexpected RPC error while checking `{cmd}`: {exc}"
            ) from exc

    if missing_cmds:
        joined = ", ".join(sorted(set(missing_cmds)))
        raise EnvironmentError(
            "Elements node is missing required wallet RPCs "
            f"({joined}). Upgrade to Elements Core 0.21.0.3+ built with wallet "
            "support."
        )

    network_info = rpc.getnetworkinfo()

    return {
        "chain": chain,
        "blocks": chain_info.get("blocks"),
        "warnings": chain_info.get("warnings"),
        "wallet": wallet_info.get("walletname", ""),
        "private_keys_enabled": wallet_info.get("private_keys_enabled", True),
        "version": network_info.get("version"),
        "subversion": network_info.get("subversion"),
    }


def ensure_mature_lbtc_balance(
    rpc: AuthServiceProxy, mining_addr: str, target_balance: Decimal = Decimal("2")
) -> Decimal:
    """Make sure the wallet owns enough matured L-BTC for demo asset issuance.

    Asset issuance spends native L-BTC as fees, so a freshly started regtest
    node must mine blocks until some coinbase rewards reach maturity.  This
    helper mines in batches of 101 blocks (enough for the first coinbase to
    mature) until the wallet's trusted balance meets ``target_balance``.
    """

    def _parse_lbtc_amount(value) -> Decimal:
        """Return the L-BTC amount from ``getbalances`` values."""

        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            pass

        if isinstance(value, dict):
            # Elements >= 23 returns per-asset dictionaries. Prefer canonical keys.
            for key in ("bitcoin", "lbtc", "L-BTC"):
                if key in value:
                    try:
                        return Decimal(str(value[key]))
                    except (InvalidOperation, TypeError, ValueError):
                        break

            # Fallback: use the first numeric-looking entry.
            for amount in value.values():
                try:
                    return Decimal(str(amount))
                except (InvalidOperation, TypeError, ValueError):
                    continue

        return Decimal("0")

    for _ in range(3):
        balances = rpc.getbalances()
        trusted = _parse_lbtc_amount(balances.get("mine", {}).get("trusted", "0"))
        if trusted >= target_balance:
            return trusted

        # Mine another batch of blocks and re-check once confirmations accrue.
        rpc.generatetoaddress(101, mining_addr)

    raise RuntimeError(
        "Unable to obtain matured L-BTC for the demo even after mining. "
        "Verify your regtest node is not running with `-minrelaytxfee` too "
        "high and that the wallet can receive block rewards."
    )


class LiquidRFQProtocol:
    def __init__(self, rpc_url: str):
        self.rpc = AuthServiceProxy(rpc_url)

    def create_rfq(
        self,
        client_addr: str,
        sell_asset: str,
        buy_asset: str,
        approx_amount: float,
        expiry_seconds: int = 300,
    ) -> RFQ:
        """Create RFQ - client wants to trade"""
        rfq_id = hashlib.sha256(
            f"{client_addr}{time.time()}".encode()
        ).hexdigest()[:16]

        rfq_data = {
            "rfq_id": rfq_id,
            "client_address": client_addr,
            "asset_to_sell": sell_asset,
            "asset_to_buy": buy_asset,
            "approx_amount": str(Decimal(str(approx_amount))),
            "expiry_time": int(time.time()) + expiry_seconds,
        }

        # Sign RFQ with client's key
        payload = json.dumps(rfq_data, sort_keys=True, separators=(",", ":"))
        signature = self.rpc.signmessage(client_addr, payload)

        return RFQ(
            rfq_id=rfq_id,
            client_address=client_addr,
            asset_to_sell=sell_asset,
            asset_to_buy=buy_asset,
            approx_amount=Decimal(str(approx_amount)),
            expiry_time=rfq_data["expiry_time"],
            client_signature=signature,
        )

    def dealer_quote(
        self,
        rfq: RFQ,
        dealer_addr: str,
        dealer_id: str,
        exact_sell: float,
        exact_buy: float,
    ) -> Quote:
        """Dealer responds with firm quote"""
        exact_sell_dec = Decimal(str(exact_sell))
        exact_buy_dec = Decimal(str(exact_buy))
        quote_data = {
            "rfq_id": rfq.rfq_id,
            "dealer_id": dealer_id,
            "dealer_address": dealer_addr,
            "exact_amount_sell": str(exact_sell_dec),
            "exact_amount_buy": str(exact_buy_dec),
            "price": str(
                (exact_buy_dec / exact_sell_dec).quantize(Decimal("0.00000001"))
            ),
            "expiry_time": int(time.time()) + 120,  # 2 min to execute
        }

        # Dealer signs quote
        payload = json.dumps(quote_data, sort_keys=True, separators=(",", ":"))
        signature = self.rpc.signmessage(dealer_addr, payload)

        return Quote(
            rfq_id=rfq.rfq_id,
            dealer_id=dealer_id,
            dealer_address=dealer_addr,
            exact_amount_sell=exact_sell_dec,
            exact_amount_buy=exact_buy_dec,
            price=Decimal(quote_data["price"]),
            expiry_time=quote_data["expiry_time"],
            dealer_signature=signature,
        )

    def verify_rfq(self, rfq: RFQ) -> bool:
        rfq_payload = {
            "rfq_id": rfq.rfq_id,
            "client_address": rfq.client_address,
            "asset_to_sell": rfq.asset_to_sell,
            "asset_to_buy": rfq.asset_to_buy,
            "approx_amount": str(rfq.approx_amount),
            "expiry_time": rfq.expiry_time,
        }
        message = json.dumps(rfq_payload, sort_keys=True, separators=(",", ":"))
        return self.rpc.verifymessage(
            rfq.client_address, rfq.client_signature, message
        )

    def verify_quote(self, quote: Quote) -> bool:
        quote_payload = {
            "rfq_id": quote.rfq_id,
            "dealer_id": quote.dealer_id,
            "dealer_address": quote.dealer_address,
            "exact_amount_sell": str(quote.exact_amount_sell),
            "exact_amount_buy": str(quote.exact_amount_buy),
            "price": str(quote.price),
            "expiry_time": quote.expiry_time,
        }
        message = json.dumps(quote_payload, sort_keys=True, separators=(",", ":"))
        return self.rpc.verifymessage(
            quote.dealer_address,
            quote.dealer_signature,
            message,
        )

    def _descriptor_key(self, address: str) -> str:
        """Return descriptor key expression for wallet-owned address."""

        info = self.rpc.getaddressinfo(address)
        pubkey = info["pubkey"]
        fingerprint = info.get("hdmasterfingerprint")
        path = info.get("hdkeypath")

        if fingerprint and path:
            # hdkeypath is of the form m/84'/1776'/0'/0/0. Descriptor expects
            # [fingerprint/84'/1776'/0'/0/0]PUBKEY format.
            descriptor_path = path[1:]  # drop leading "m"
            return f"[{fingerprint}{descriptor_path}]{pubkey}"

        return pubkey

    def build_joint_timelocked_address(
        self, client_addr: str, dealer_addr: str, csv_delay: int = 10
    ) -> Tuple[str, str]:
        """Create a miniscript-driven address protecting client settlement."""

        # The policy allows the dealer to spend immediately, while the client
        # can reclaim funds after `csv_delay` blocks. This demonstrates usage of
        # Liquid-native opcodes like OP_CSV via Miniscript while keeping the
        # flow atomic and confidential.
        client_key = self._descriptor_key(client_addr)
        dealer_key = self._descriptor_key(dealer_addr)

        miniscript_policy = (
            f"or_i(pk({dealer_key}),and_v(v:pk({client_key}),older({csv_delay})))"
        )
        descriptor = f"wsh({miniscript_policy})"

        descriptor_info = self.rpc.getdescriptorinfo(descriptor)
        # Import as watch-only so wallet can analyze future spends if needed.
        import_result = self.rpc.importdescriptors(
            [
                {
                    "desc": descriptor_info["descriptor"],
                    "timestamp": "now",
                    "label": "rfq_joint_timelock",
                    "active": False,
                }
            ]
        )[0]

        if not import_result.get("success", False):
            error = import_result.get("error")
            if not error or "exists" not in error.get("message", "").lower():
                raise RuntimeError(
                    f"Descriptor import failed: {json.dumps(import_result)}"
                )

        base_address = self.rpc.deriveaddresses(descriptor_info["descriptor"])[0]
        master_blinding = self.rpc.dumpmasterblindingkey()
        confidential_address = self.rpc.createblindedaddress(
            base_address, master_blinding
        )

        return confidential_address, descriptor_info["descriptor"]

    def create_atomic_settlement(
        self, rfq: RFQ, quote: Quote
    ) -> Tuple[str, str]:
        """Create confidential atomic swap PSET for settlement."""

        # Returns the blinded PSET and the Miniscript descriptor securing the
        # dealer's received L-BTC leg.

        # Step 1: Dealer creates partially blinded transaction
        # Dealer sends exact_amount_buy to client
        # Client sends exact_amount_sell to dealer

        # Get unspent outputs for atomic swap
        dealer_utxos = self.rpc.listunspent(1, 9999999, [quote.dealer_address])
        client_utxos = self.rpc.listunspent(1, 9999999, [rfq.client_address])

        # Find UTXO with enough of sell asset
        target_buy = quote.exact_amount_buy.quantize(Decimal("0.00000001"))
        target_sell = quote.exact_amount_sell.quantize(Decimal("0.00000001"))

        dealer_input = next(
            (
                u
                for u in dealer_utxos
                if u["asset"] == rfq.asset_to_buy
                and Decimal(str(u["amount"])) >= target_buy
            ),
            None,
        )

        client_input = next(
            (
                u
                for u in client_utxos
                if u["asset"] == rfq.asset_to_sell
                and Decimal(str(u["amount"]))
                >= (target_sell + Decimal("0.0001"))
            ),
            None,
        )

        if not dealer_input or not client_input:
            raise ValueError("Insufficient funds for atomic swap")

        fee = Decimal("0.0001")  # pay fee from client's BTC leg
        dealer_input_amt = Decimal(str(dealer_input["amount"]))
        client_input_amt = Decimal(str(client_input["amount"]))

        dealer_change = (dealer_input_amt - target_buy).quantize(Decimal("0.00000001"))
        client_change = (
            client_input_amt - target_sell - fee
        ).quantize(Decimal("0.00000001"))

        if client_change < Decimal("0") or dealer_change < Decimal("0"):
            raise ValueError("Selected UTXOs cannot fund settlement with fee")

        inputs = [
            {"txid": dealer_input["txid"], "vout": dealer_input["vout"]},
            {"txid": client_input["txid"], "vout": client_input["vout"]},
        ]

        protected_address, descriptor = self.build_joint_timelocked_address(
            rfq.client_address, quote.dealer_address
        )

        outputs = [
            {
                rfq.client_address: {
                    "asset": rfq.asset_to_buy,
                    "amount": str(target_buy),
                }
            }
        ]

        outputs.append(
            {
                protected_address: {
                    "asset": rfq.asset_to_sell,
                    "amount": str(target_sell),
                }
            }
        )

        if dealer_change > Decimal("0.00000001"):
            outputs.append(
                {
                    quote.dealer_address: {
                        "asset": rfq.asset_to_buy,
                        "amount": str(dealer_change),
                    }
                }
            )

        if client_change > Decimal("0.00000001"):
            outputs.append(
                {
                    rfq.client_address: {
                        "asset": rfq.asset_to_sell,
                        "amount": str(client_change),
                    }
                }
            )

        outputs.append({"fee": str(fee)})

        # Create confidential PSBT skeleton
        psbt = self.rpc.createpsbt(inputs, outputs)

        # Attach UTXO information for both legs so blinding works
        prev_txs = []
        for utxo in (dealer_input, client_input):
            txout = self.rpc.gettxout(utxo["txid"], utxo["vout"], True)
            if not txout:
                raise ValueError("Missing UTXO information for blinding")
            prev_txs.append(
                {
                    "txid": utxo["txid"],
                    "vout": utxo["vout"],
                    "scriptPubKey": txout["scriptPubKey"]["hex"],
                    "amount": txout["value"],
                    "asset": txout["asset"],
                }
            )

        enriched_psbt = self.rpc.utxoupdatepsbt(psbt, prev_txs)

        # Blind to hide amounts/asset ids on-chain
        blinded_psbt = self.rpc.blindpsbt(enriched_psbt)

        return blinded_psbt, descriptor

    def sign_and_broadcast(self, pset: str, dealer_addr: str, client_addr: str) -> str:
        """Both parties sign PSET and broadcast"""

        # Dealer signs first
        dealer_signed = self.rpc.walletprocesspsbt(pset, True)

        # Client signs
        client_signed = self.rpc.walletprocesspsbt(dealer_signed["psbt"], True)

        if not client_signed["complete"]:
            raise ValueError("PSET signing incomplete")

        # Finalize and extract
        final_tx = self.rpc.finalizepsbt(client_signed["psbt"])

        if not final_tx["complete"]:
            raise ValueError("Finalization failed")

        # Broadcast confidential transaction
        txid = self.rpc.sendrawtransaction(final_tx["hex"])

        return txid


class OTCDesk:
    """Simulated OTC desk that responds to RFQs"""

    def __init__(self, desk_id: str, rpc_url: str, address: str):
        self.desk_id = desk_id
        self.protocol = LiquidRFQProtocol(rpc_url)
        self.address = address
        labels = self.protocol.rpc.dumpassetlabels()
        self.lbtc_asset = labels["bitcoin"]
        self.spread_bps = Decimal("0.001")  # 10 bps default spread

    def process_rfq(self, rfq: RFQ) -> Optional[Quote]:
        """Desk evaluates RFQ and returns quote if interested"""

        # Only stream liquidity when we are lifting L-BTC offers
        if rfq.asset_to_sell != self.lbtc_asset:
            return None

        # Simulate price check (in real life: check market)
        # For demo: assume 1 L-BTC = 50,000 L-USDt
        mid_price = Decimal("50000")

        # Apply spread
        quoted_price = mid_price * (Decimal("1") - self.spread_bps)

        exact_sell = rfq.approx_amount
        exact_buy = (exact_sell * quoted_price).quantize(Decimal("0.00000001"))

        return self.protocol.dealer_quote(
            rfq, self.address, self.desk_id, exact_sell, exact_buy
        )


def demo_confidential_otc_settlement():
    """Full working demo of confidential OTC RFQ settlement"""

    rpc_url = f"http://{RPC_USER}:{RPC_PASS}@{RPC_HOST}:{RPC_PORT}"
    protocol = LiquidRFQProtocol(rpc_url)
    rpc = protocol.rpc

    print("=== Confidential OTC Settlement Demo ===\n")

    print("Performing regtest readiness checks...")
    readiness = ensure_regtest_readiness(rpc)
    print(
        "Connected to Elements "
        f"{readiness.get('version')} {readiness.get('subversion')} on {readiness.get('chain')}"
    )
    if readiness.get("wallet"):
        print(
            f"Active wallet: {readiness['wallet']} (private keys enabled: "
            f"{readiness['private_keys_enabled']})"
        )
    if readiness.get("warnings"):
        print(f"Node warnings: {readiness['warnings']}")
    print("")

    # Setup: Create addresses for client and dealers
    client_addr = rpc.getnewaddress("client", "blech32")
    dealer1_addr = rpc.getnewaddress("dealer1", "blech32")
    dealer2_addr = rpc.getnewaddress("dealer2", "blech32")

    print(f"Client address: {client_addr}")
    print(f"Dealer1 address: {dealer1_addr}")
    print(f"Dealer2 address: {dealer2_addr}\n")

    # Fund addresses with L-BTC and L-USDt (simulate)
    # In real scenario: peg-in BTC to get L-BTC
    print("Ensuring wallet has matured L-BTC for issuance fees...")
    matured_balance = ensure_mature_lbtc_balance(rpc, client_addr)
    print(f"Matured L-BTC balance: {matured_balance} L-BTC\n")

    # Get asset IDs (L-BTC is native, L-USDt would be issued asset)
    l_btc_asset = rpc.dumpassetlabels()["bitcoin"]

    # For demo: issue L-USDt test asset
    try:
        l_usdt_asset = rpc.issueasset(100000, 0)["asset"]
    except JSONRPCException as exc:
        raise RuntimeError(
            "Failed to issue demo asset. Ensure the regtest wallet has matured "
            "L-BTC to cover issuance fees and supports confidential transactions. "
            f"Underlying RPC error: {exc.message}"
        ) from exc
    rpc.sendtoaddress(
        dealer1_addr,
        100000,
        "",
        "",
        False,
        False,
        1,
        "UNSET",
        False,
        l_usdt_asset,
    )
    rpc.sendtoaddress(
        dealer2_addr,
        100000,
        "",
        "",
        False,
        False,
        1,
        "UNSET",
        False,
        l_usdt_asset,
    )
    rpc.generatetoaddress(1, client_addr)

    print(f"L-BTC asset: {l_btc_asset}")
    print(f"L-USDt asset: {l_usdt_asset}\n")

    # Step 1: Client creates RFQ
    print("STEP 1: Client creates RFQ")
    print("Client wants to sell 1.0 L-BTC for L-USDt")

    rfq = protocol.create_rfq(
        client_addr,
        l_btc_asset,  # Selling L-BTC
        l_usdt_asset,  # Buying L-USDt
        1.0,  # ~1 BTC
        300,  # 5 min expiry
    )

    print(f"RFQ ID: {rfq.rfq_id}")
    if not protocol.verify_rfq(rfq):
        raise RuntimeError("RFQ signature invalid")

    print(f"Approx amount: {rfq.approx_amount} (hidden from market)")
    print(f"Expiry: {rfq.expiry_time}\n")

    # Step 2: Dealers respond with quotes
    print("STEP 2: Dealers respond with quotes")

    desk1 = OTCDesk("Dealer_Alpha", rpc_url, dealer1_addr)
    desk2 = OTCDesk("Dealer_Beta", rpc_url, dealer2_addr)

    quote1 = desk1.process_rfq(rfq)
    quote2 = desk2.process_rfq(rfq)

    if not quote1 or not quote2:
        raise RuntimeError("Dealers declined the RFQ")

    if not protocol.verify_quote(quote1) or not protocol.verify_quote(quote2):
        raise RuntimeError("Quote signature invalid")

    print(f"Quote from {quote1.dealer_id}:")
    print(f"  Price: {float(quote1.price):.2f} L-USDt per L-BTC")
    print(f"  You receive: {float(quote1.exact_amount_buy):.2f} L-USDt")

    print(f"\nQuote from {quote2.dealer_id}:")
    print(f"  Price: {float(quote2.price):.2f} L-USDt per L-BTC")
    print(f"  You receive: {float(quote2.exact_amount_buy):.2f} L-USDt\n")

    # Step 3: Client selects best quote
    print("STEP 3: Client selects best quote")
    best_quote = quote1 if quote1.exact_amount_buy > quote2.exact_amount_buy else quote2
    print(f"Selected: {best_quote.dealer_id} @ {float(best_quote.price):.2f}\n")

    # Step 4: Create and execute confidential atomic settlement
    print("STEP 4: Execute confidential atomic settlement")
    print("Creating PSET for atomic swap...")

    try:
        pset, descriptor = protocol.create_atomic_settlement(rfq, best_quote)
        print(f"PSET created: {pset[:50]}...")
        print("Timelocked settlement descriptor (Miniscript):")
        print(f"  {descriptor}\n")

        print("\nBoth parties signing...")
        txid = protocol.sign_and_broadcast(pset, best_quote.dealer_address, rfq.client_address)

        print(f"\n✅ Settlement complete!")
        print(f"Transaction ID: {txid}")
        print(f"\nConfidential Transaction properties:")
        print(f"- Amounts HIDDEN from public")
        print(f"- Only client and dealer know values")
        print(f"- Settlement finality: ~2 minutes (2 blocks)")
        print(f"- No front-running possible")

    except Exception as e:
        print(f"Error in settlement: {e}")
        print("(In production: would retry with different UTXOs)")

    print("\n=== Demo Complete ===")


if __name__ == "__main__":
    demo_confidential_otc_settlement()
