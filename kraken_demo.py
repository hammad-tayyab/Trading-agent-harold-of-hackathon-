import time
import hashlib
import hmac
import base64
import requests

class KrakenFuturesAgent:
    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://demo-futures.kraken.com"

    def _get_signature(self, endpoint_path, nonce, post_data=""):
        """Generates the mandatory signature for Kraken Futures API v3."""
        message = post_data + nonce + endpoint_path
        sha256_hash = hashlib.sha256(message.encode("utf-8")).digest()
        secret_decoded = base64.b64decode(self.api_secret)
        hmac_512 = hmac.new(secret_decoded, sha256_hash, hashlib.sha512).digest()
        return base64.b64encode(hmac_512).decode("utf-8")

    def place_market_order(self, symbol="PI_XBTUSD", side="buy", size=1):
        """Places a market order via POST."""
        http_path = "/derivatives/api/v3/sendorder"
        sign_path = "/api/v3/sendorder"
        nonce = str(int(time.time() * 1000))
        order_data = {"orderType": "mkt", "symbol": symbol, "side": side, "size": size}
        
        # Format the query string exactly for the signature
        query_string = f"orderType={order_data['orderType']}&symbol={order_data['symbol']}&side={order_data['side']}&size={order_data['size']}"
        
        authent = self._get_signature(sign_path, nonce, post_data=query_string)
        headers = {
            "APIKey": self.api_key, 
            "Authent": authent, 
            "Nonce": nonce, 
            "Content-Type": "application/x-www-form-urlencoded"
        }
        return requests.post(self.base_url + http_path, data=order_data, headers=headers).json()

    def get_pnl(self, entry_price, size, symbol="PI_XBTUSD"):
        """Calculates current PnL percentage."""
        response = requests.get(self.base_url + "/derivatives/api/v3/tickers").json()
        # Find the specific symbol in the ticker list
        current_price = next(t['last'] for t in response['tickers'] if t['symbol'] == symbol)
        
        pnl_usd = (current_price - entry_price) * (size / entry_price)
        percent = (pnl_usd / (size / entry_price)) * 100
        return {"current_price": current_price, "percent": round(percent, 2)}

    def start_trading(self, symbol="PI_XBTUSD", size=50, tp=0.5, sl=-0.2):
        """Main automated trading loop."""
        print(f"🚀 Initializing Agent: Buying {size} units of {symbol}...")
        
        # 1. Place the entry order
        res = self.place_market_order(symbol=symbol, side="buy", size=size)
    
        if res.get('result') == 'success':
            # 2. Extract price and size from the execution event
            exec_data = res['sendStatus']['orderEvents'][0]
            entry_p = exec_data['price']
            qty = exec_data['amount']
            print(f"✅ Position Open @ ${entry_p}")

            try:
                print(f"--- Monitoring {symbol} (Updates every 1s) ---")
                while True:
                    # 3. Fetch PnL using the correct symbol
                    stats = self.get_pnl(entry_p, qty, symbol=symbol)
                    pnl = stats['percent']
                    
                    print(f"[{time.strftime('%H:%M:%S')}] {symbol} Price: ${stats['current_price']} | PnL: {pnl}%")

                    if pnl >= tp:
                        print(f"\n💰 Target Hit (+{pnl}%)! Selling...")
                        break
                    elif pnl <= sl:
                        print(f"\n⚠️ Stop Loss Hit ({pnl}%)! Selling...")
                        break
                    
                    time.sleep(10)  # Check every 10 seconds

                # 4. Close the position
                self.place_market_order(symbol=symbol, side="sell", size=qty)
                print("✅ Trade Closed Successfully.")
                
            except KeyboardInterrupt:
                print("\nManual Exit: Closing position for safety...")
                self.place_market_order(symbol=symbol, side="sell", size=qty)
        else:
            print(f"❌ Entry Failed: {res}")

if __name__ == "__main__":
    # Add your credentials here
    KEY = "0G9tweA0qw6RjIbyEktfCZkLtuoe0JVBhEWuYxP2ldjUOLy4Y4V2QQdp"
    SECRET = "i0L/mBkA9Tag2NnI7h5qUj51/6KBUqpUmr9nkJ3xIAhO52AfP1YVUfvYsDJFnT3MPCs+9Cr/YVaneC2pB43dOSUR"
    
    agent = KrakenFuturesAgent(KEY, SECRET)
    
    # Example: Trade Bitcoin with a 0.2% Profit Target and 0.1% Stop Loss
    agent.start_trading(symbol="PI_XBTUSD", size=50, tp=0.2, sl=-0.1)