"""
MEXC Futures Data Feeder
从 MEXC 获取合约 (Futures) 实时价格
"""

import asyncio
import ccxt.async_support as ccxt  # 异步版 CCXT
from datetime import datetime
from typing import Dict, Optional, List, Deque
from collections import deque

# 目标合约 (Symbol: MEXC 格式)
TARGET_CONTRACTS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "DOGE/USDT:USDT"
]

class FuturesFeeder:
    """MEXC 合约数据抓取器"""
    
    def __init__(self):
        self.prices: Dict[str, dict] = {}
        self.history: Dict[str, Deque] = {
            sym.split('/')[0]: deque(maxlen=100) for sym in TARGET_CONTRACTS
        }
        self.last_update: Optional[datetime] = None
        self._running = False
        self._subscribers = []
        
        # 初始化 MEXC 交易所 (异步)
        self.exchange = ccxt.mexc({
            'options': {
                'defaultType': 'swap',  # 合约模式
            }
        })
    
    async def fetch_all_prices(self) -> Dict[str, dict]:
        """获取所有目标合约价格"""
        try:
            tickers = await self.exchange.fetch_tickers(TARGET_CONTRACTS)
            
            result = {}
            for symbol, data in tickers.items():
                # 简化 Symbol: "BTC/USDT:USDT" -> "BTC"
                simple_symbol = symbol.split('/')[0]
                
                price_data = {
                    "symbol": simple_symbol,
                    "contract": symbol,
                    "priceUsd": float(data.get('last', 0)),
                    "priceChange24h": float(data.get('percentage', 0)),
                    "volume24h": float(data.get('quoteVolume', 0)), # USDT Volume
                    "fundingRate": float(data.get('info', {}).get('fundingRate', 0) or 0),
                    "timestamp": datetime.now().timestamp()
                }
                
                result[simple_symbol] = price_data
                
                # Append to history
                if simple_symbol in self.history:
                    self.history[simple_symbol].append({
                        "timestamp": price_data["timestamp"],
                        "price": price_data["priceUsd"]
                    })
            
            self.prices = result
            self.last_update = datetime.now()
            return self.prices
            
        except Exception as e:
            print(f"❌ Error fetching futures: {e}")
            return {}
    
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
        print(f"🚀 MEXC Futures Feeder started. Zone: CONTRACT")
        
        try:
            while self._running:
                prices = await self.fetch_all_prices()
                if prices:
                    await self.broadcast(prices)
                    
                    # 打印摘要 (每 5 次打印一次，避免刷屏)
                    # print(f"📊 Futures Update: BTC ${prices['BTC']['priceUsd']:.1f}")
                
                await asyncio.sleep(2) # 合约数据更新快一点
        finally:
            await self.exchange.close()
    
    def stop(self):
        """停止抓取"""
        self._running = False

# 测试
if __name__ == "__main__":
    feeder = FuturesFeeder()
    
    async def test():
        print("Connecting to MEXC...")
        await feeder.start()
    
    try:
        asyncio.run(test())
    except KeyboardInterrupt:
        print("Stopped.")
