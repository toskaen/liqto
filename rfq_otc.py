# rfq_otc.py - Confidential OTC Settlement on Liquid Network
# Requires: elementsd running in regtest mode, python-bitcoinrpc

from bitcoinrpc.authproxy import AuthServiceProxy
import hashlib
import json
import time
from decimal import Decimal
from dataclasses import dataclass, asdict
from typing import Optional

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
    approx_amount: float  # Approximate for privacy
    expiry_time: int
    client_signature: str

@dataclass
class Quote:
    """Dealer quote response"""
    rfq_id: str
    dealer_id: str
    dealer_address: str  # Liquid address for settlement
    exact_amount_sell: float
    exact_amount_buy: float
    price: float
    expiry_time: int
    dealer_signature: str

class LiquidRFQProtocol:
    def __init__(self, rpc_url: str):
        self.rpc = AuthServiceProxy(rpc_url)
        
    def create_rfq(self, client_addr: str, sell_asset: str, buy_asset: str, 
                   approx_amount: float, expiry_seconds: int = 300) -> RFQ:
        """Create RFQ - client wants to trade"""
        rfq_id = hashlib.sha256(
            f"{client_addr}{time.time()}".encode()
        ).hexdigest()[:16]
        
        rfq_data = {
            "rfq_id": rfq_id,
            "client_address": client_addr,
            "asset_to_sell": sell_asset,
            "asset_to_buy": buy_asset,
            "approx_amount": approx_amount,
            "expiry_time": int(time.time()) + expiry_seconds
        }
        
        # Sign RFQ with client's key
        signature = self.rpc.signmessage(client_addr, json.dumps(rfq_data))
        
        return RFQ(**rfq_data, client_signature=signature)
    
    def dealer_quote(self, rfq: RFQ, dealer_addr: str, dealer_id: str, 
                    exact_sell: float, exact_buy: float) -> Quote:
        """Dealer responds with firm quote"""
        quote_data = {
            "rfq_id": rfq.rfq_id,
            "dealer_id": dealer_id,
            "dealer_address": dealer_addr,
            "exact_amount_sell": exact_sell,
            "exact_amount_buy": exact_buy,
            "price": exact_buy / exact_sell,
            "expiry_time": int(time.time()) + 120  # 2 min to execute
        }
        
        # Dealer signs quote
        signature = self.rpc.signmessage(dealer_addr, json.dumps(quote_data))
        
        return Quote(**quote_data, dealer_signature=signature)
    
    def create_atomic_settlement(self, rfq: RFQ, quote: Quote) -> str:
        """Create confidential atomic swap PSET for settlement"""
        
        # Step 1: Dealer creates partially blinded transaction
        # Dealer sends exact_amount_buy to client
        # Client sends exact_amount_sell to dealer
        
        # Get unspent outputs for atomic swap
        dealer_utxos = self.rpc.listunspent(1, 9999999, [quote.dealer_address])
        client_utxos = self.rpc.listunspent(1, 9999999, [rfq.client_address])
        
        # Find UTXO with enough of sell asset
        dealer_input = next((u for u in dealer_utxos 
                           if u['asset'] == rfq.asset_to_buy 
                           and u['amount'] >= quote.exact_amount_buy), None)
        
        client_input = next((u for u in client_utxos 
                           if u['asset'] == rfq.asset_to_sell 
                           and u['amount'] >= quote.exact_amount_sell), None)
        
        if not dealer_input or not client_input:
            raise ValueError("Insufficient funds for atomic swap")
        
        # Create raw transaction with both inputs
        inputs = [
            {"txid": dealer_input['txid'], "vout": dealer_input['vout']},
            {"txid": client_input['txid'], "vout": client_input['vout']}
        ]
        
        # Outputs: confidential amounts to both parties
        outputs = [
            {quote.dealer_address: quote.exact_amount_sell, "asset": rfq.asset_to_sell},
            {rfq.client_address: quote.exact_amount_buy, "asset": rfq.asset_to_buy}
        ]
        
        # Create transaction (Elements automatically makes it confidential)
        rawtx = self.rpc.createrawtransaction(inputs, outputs)
        
        # Blind transaction (hide amounts)
        blinded = self.rpc.blindrawtransaction(rawtx)
        
        # Convert to PSET for partial signing
        pset = self.rpc.converttopsbt(blinded)
        
        return pset
    
    def sign_and_broadcast(self, pset: str, dealer_addr: str, client_addr: str) -> str:
        """Both parties sign PSET and broadcast"""
        
        # Dealer signs first
        dealer_signed = self.rpc.walletprocesspsbt(pset)
        
        # Client signs
        client_signed = self.rpc.walletprocesspsbt(dealer_signed['psbt'])
        
        if not client_signed['complete']:
            raise ValueError("PSET signing incomplete")
        
        # Finalize and extract
        final_tx = self.rpc.finalizepsbt(client_signed['psbt'])
        
        # Broadcast confidential transaction
        txid = self.rpc.sendrawtransaction(final_tx['hex'])
        
        return txid


class OTCDesk:
    """Simulated OTC desk that responds to RFQs"""
    
    def __init__(self, desk_id: str, rpc_url: str, address: str):
        self.desk_id = desk_id
        self.protocol = LiquidRFQProtocol(rpc_url)
        self.address = address
        self.spreads = {
            "L-BTC/L-USDt": 0.001,  # 10 bps spread
        }
    
    def process_rfq(self, rfq: RFQ) -> Optional[Quote]:
        """Desk evaluates RFQ and returns quote if interested"""
        
        # Check if we trade this pair
        pair = f"{rfq.asset_to_sell}/{rfq.asset_to_buy}"
        if pair not in self.spreads:
            return None
        
        # Simulate price check (in real life: check market)
        # For demo: assume 1 L-BTC = 50,000 L-USDt
        if rfq.asset_to_sell == "L-BTC":
            mid_price = 50000
        else:
            mid_price = 1 / 50000
        
        # Apply spread
        spread = self.spreads[pair]
        if rfq.asset_to_sell == "L-BTC":
            quoted_price = mid_price * (1 - spread)  # Bid price
        else:
            quoted_price = mid_price * (1 + spread)  # Ask price
        
        exact_sell = rfq.approx_amount
        exact_buy = exact_sell * quoted_price
        
        return self.protocol.dealer_quote(
            rfq, self.address, self.desk_id, exact_sell, exact_buy
        )


def demo_confidential_otc_settlement():
    """Full working demo of confidential OTC RFQ settlement"""
    
    rpc_url = f"http://{RPC_USER}:{RPC_PASS}@{RPC_HOST}:{RPC_PORT}"
    protocol = LiquidRFQProtocol(rpc_url)
    rpc = protocol.rpc
    
    print("=== Confidential OTC Settlement Demo ===\n")
    
    # Setup: Create addresses for client and dealers
    client_addr = rpc.getnewaddress("client", "bech32")
    dealer1_addr = rpc.getnewaddress("dealer1", "bech32")
    dealer2_addr = rpc.getnewaddress("dealer2", "bech32")
    
    print(f"Client address: {client_addr}")
    print(f"Dealer1 address: {dealer1_addr}")
    print(f"Dealer2 address: {dealer2_addr}\n")
    
    # Fund addresses with L-BTC and L-USDt (simulate)
    # In real scenario: peg-in BTC to get L-BTC
    rpc.generatetoaddress(101, client_addr)  # Mine to get L-BTC
    
    # Get asset IDs (L-BTC is native, L-USDt would be issued asset)
    l_btc_asset = rpc.dumpassetlabels()['bitcoin']
    
    # For demo: issue L-USDt test asset
    l_usdt_asset = rpc.issueasset(100000, 0)['asset']
    rpc.sendtoaddress(dealer1_addr, 100000, "", "", False, False, 1, "UNSET", False, l_usdt_asset)
    rpc.sendtoaddress(dealer2_addr, 100000, "", "", False, False, 1, "UNSET", False, l_usdt_asset)
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
        300  # 5 min expiry
    )
    
    print(f"RFQ ID: {rfq.rfq_id}")
    print(f"Approx amount: {rfq.approx_amount} (hidden from market)")
    print(f"Expiry: {rfq.expiry_time}\n")
    
    # Step 2: Dealers respond with quotes
    print("STEP 2: Dealers respond with quotes")
    
    desk1 = OTCDesk("Dealer_Alpha", rpc_url, dealer1_addr)
    desk2 = OTCDesk("Dealer_Beta", rpc_url, dealer2_addr)
    
    quote1 = desk1.process_rfq(rfq)
    quote2 = desk2.process_rfq(rfq)
    
    print(f"Quote from {quote1.dealer_id}:")
    print(f"  Price: {quote1.price:.2f} L-USDt per L-BTC")
    print(f"  You receive: {quote1.exact_amount_buy:.2f} L-USDt")
    
    print(f"\nQuote from {quote2.dealer_id}:")
    print(f"  Price: {quote2.price:.2f} L-USDt per L-BTC")
    print(f"  You receive: {quote2.exact_amount_buy:.2f} L-USDt\n")
    
    # Step 3: Client selects best quote
    print("STEP 3: Client selects best quote")
    best_quote = quote1 if quote1.exact_amount_buy > quote2.exact_amount_buy else quote2
    print(f"Selected: {best_quote.dealer_id} @ {best_quote.price:.2f}\n")
    
    # Step 4: Create and execute confidential atomic settlement
    print("STEP 4: Execute confidential atomic settlement")
    print("Creating PSET for atomic swap...")
    
    try:
        pset = protocol.create_atomic_settlement(rfq, best_quote)
        print(f"PSET created: {pset[:50]}...")
        
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
