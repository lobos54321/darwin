"""
DexScreener Data Feeder
从 DexScreener 获取 Base 链代币实时价格
"""

import asyncio
import aiohttp
import ssl
import certifi
from datetime import datetime
from typing import Dict, Optional, List
from collections import deque
from config import TARGET_TOKENS, DEXSCREENER_BASE_URL, PRICE_UPDATE_INTERVAL

# 创建 SSL context (解决 macOS 证书问题)
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


class DexScreenerFeeder:
    """DexScreener 数据抓取器"""

    def __init__(self, tokens: Dict[str, str] = None):
        self._tokens = tokens or TARGET_TOKENS
        self.prices: Dict[str, dict] = {}
        self.history: Dict[str, deque] = {
            sym: deque(maxlen=100) for sym in self._tokens.keys()
        }
        self.last_update: Optional[datetime] = None
        self._running = False
        self._subscribers = []
    
    async def fetch_token_price(self, session: aiohttp.ClientSession, address: str) -> Optional[dict]:
        """获取单个代币价格"""
        url = f"{DEXSCREENER_BASE_URL}/latest/dex/tokens/{address}"
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        # 取流动性最高的交易对
                        best_pair = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
                        return {
                            "symbol": best_pair["baseToken"]["symbol"],
                            "address": address,
                            "priceUsd": float(best_pair.get("priceUsd", 0)),
                            "priceChange24h": float(best_pair.get("priceChange", {}).get("h24", 0) or 0),
                            "volume24h": float(best_pair.get("volume", {}).get("h24", 0) or 0),
                            "liquidity": float(best_pair.get("liquidity", {}).get("usd", 0) or 0),
                            "dex": best_pair.get("dexId"),
                            "pairAddress": best_pair.get("pairAddress"),
                        }
        except Exception as e:
            print(f"Error fetching {address}: {e}")
        return None
    
    async def fetch_all_prices(self) -> Dict[str, dict]:
        """获取所有目标代币价格"""
        connector = aiohttp.TCPConnector(ssl=SSL_CONTEXT)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            for symbol, address in self._tokens.items():
                tasks.append(self.fetch_token_price(session, address))

            results = await asyncio.gather(*tasks)

            for symbol, result in zip(self._tokens.keys(), results):
                if result:
                    self.prices[symbol] = result
                    # Append to history
                    self.history[symbol].append({
                        "timestamp": datetime.now().timestamp(),
                        "price": result["priceUsd"]
                    })
            
            self.last_update = datetime.now()
            return self.prices
    
    def subscribe(self, callback):
        """订阅价格更新"""
        self._subscribers.append(callback)
    
    async def broadcast(self, prices: dict):
        """广播价格给所有订阅者"""
        for callback in self._subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(prices)
                else:
                    callback(prices)
            except Exception as e:
                print(f"Broadcast error: {e}")
    
    async def start(self):
        """启动价格抓取循环"""
        self._running = True
        print(f"🚀 DexScreener Feeder started. Updating every {PRICE_UPDATE_INTERVAL}s")
        
        while self._running:
            prices = await self.fetch_all_prices()
            await self.broadcast(prices)
            
            # 打印价格摘要
            print(f"\n📊 Price Update @ {self.last_update.strftime('%H:%M:%S')}")
            for symbol, data in prices.items():
                print(f"  {symbol}: ${data['priceUsd']:.4f} ({data['priceChange24h']:+.2f}%)")
            
            await asyncio.sleep(PRICE_UPDATE_INTERVAL)
    
    def stop(self):
        """停止抓取"""
        self._running = False


# 测试
if __name__ == "__main__":
    feeder = DexScreenerFeeder()
    
    async def test():
        prices = await feeder.fetch_all_prices()
        print("\n=== Test Results ===")
        for symbol, data in prices.items():
            print(f"{symbol}:")
            print(f"  Price: ${data['priceUsd']:.4f}")
            print(f"  24h Change: {data['priceChange24h']:+.2f}%")
            print(f"  24h Volume: ${data['volume24h']:,.0f}")
            print(f"  Liquidity: ${data['liquidity']:,.0f}")
            print()
    
    asyncio.run(test())
