import ccxt
import time
import json

def test_mexc_futures():
    print("🔌 Connecting to MEXC Futures...")
    mexc = ccxt.mexc({
        'options': {
            'defaultType': 'swap',  # Futures/Swap mode
        }
    })
    
    # Symbols to track (Contract Zone targets)
    symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT']
    
    try:
        print("📊 Fetching Tickers...")
        tickers = mexc.fetch_tickers(symbols)
        
        for symbol, data in tickers.items():
            print(f"\n🪙 {symbol}")
            print(f"   Price: ${data['last']}")
            print(f"   Vol:   {data['baseVolume']}")
            print(f"   Chg:   {data['percentage']}%")
            
        print("\n✅ MEXC Futures Data Feed is READY.")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_mexc_futures()
