#!/usr/bin/env python3
"""
🧬 Darwin Arena Agent (Phoenix Edition)
Single-file autonomous trading agent for Project Darwin.

Includes:
- WebSocket Client
- Phoenix Strategy (RSI + Bollinger Confluence)
- Self-Healing Connection
- Hive Mind Integration
"""

import asyncio
import argparse
import os
import sys
import random
import json
import statistics
import logging
from collections import deque
from datetime import datetime

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Darwin")

# ==========================================
# 🧠 STRATEGY: PHOENIX CHAMPION
# ==========================================
class PhoenixStrategy:
    """
    The 'Phoenix' strategy evolved over 360+ epochs.
    Logic: Buy when RSI < 30 AND Price < Bollinger Lower Band AND Price is curling up.
    """
    def __init__(self):
        self.history = {}  # {symbol: deque(maxlen=60)}
        self.banned_tags = set()
        
        # Hyperparameters (Evolved)
        self.history_window = 60
        self.base_z_score = -2.0
        self.rsi_period = 14
        self.oversold_threshold = 30
        self.risk_per_trade = 25.0
        self.min_band_width = 0.003

    def on_hive_signal(self, signal: dict):
        """Adapt to Hive Mind patches"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)
            logger.info(f"🧠 Hive Mind Update: Avoid {penalize}")

    def _calculate_rsi(self, prices):
        if len(prices) < self.rsi_period + 1: return 50.0
        gains, losses = [], []
        recent = list(prices)[-(self.rsi_period+1):]
        
        for i in range(1, len(recent)):
            delta = recent[i] - recent[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0: return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: dict):
        """Analyze market and generate orders"""
        decisions = []
        symbols = list(prices.keys())
        random.shuffle(symbols) # Avoid bias
        
        for symbol in symbols:
            current_price = prices[symbol]["priceUsd"]
            
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(current_price)
            
            # Need Data
            if len(self.history[symbol]) < 21: continue

            # Calc Indicators
            window = list(self.history[symbol])[-20:]
            sma = statistics.mean(window)
            stdev = statistics.stdev(window)
            if stdev == 0: continue
            
            z_score = (current_price - sma) / stdev
            band_width = (4 * stdev) / sma
            rsi = self._calculate_rsi(self.history[symbol])
            
            # Logic: Phoenix Mean Reversion
            if (rsi < self.oversold_threshold and 
                z_score < self.base_z_score and 
                band_width > self.min_band_width):
                
                # Confirmation: Tick Up?
                prev_price = self.history[symbol][-2]
                if current_price > prev_price:
                    decisions.append({
                        "symbol": symbol,
                        "side": "BUY",
                        "amount": self.risk_per_trade * 1.5,
                        "reason": ["PHOENIX_ENTRY", "RSI_OVERSOLD"]
                    })
        
        return decisions

# ==========================================
# 🔌 CLIENT: WEBSOCKET & AUTH
# ==========================================
async def run_agent(agent_id, arena_url):
    try:
        import aiohttp
    except ImportError:
        print("❌ Missing dependency: aiohttp")
        print("👉 Run: pip install aiohttp")
        sys.exit(1)

    print(f"🧬 Agent '{agent_id}' connecting to {arena_url}...")
    strategy = PhoenixStrategy()
    
    async with aiohttp.ClientSession() as session:
        # 1. Register/Auth
        http_url = arena_url.replace("wss://", "https://").replace("ws://", "http://")
        try:
            async with session.post(f"{http_url}/auth/register?agent_id={agent_id}") as resp:
                if resp.status != 200:
                    logger.error(f"Registration failed: {resp.status}")
                    return
                data = await resp.json()
                api_key = data.get("api_key")
        except Exception as e:
            logger.error(f"Auth error: {e}")
            return

        # 2. Connect WebSocket
        ws_url = f"{arena_url}/ws/{agent_id}?api_key={api_key}"
        while True:
            try:
                async with session.ws_connect(ws_url) as ws:
                    logger.info("✅ Connected to Arena")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            msg_type = data.get("type")
                            
                            if msg_type == "price_update":
                                orders = strategy.on_price_update(data.get("prices", {}))
                                for order in orders:
                                    # Fix: Ensure side is valid
                                    order["type"] = "order"
                                    await ws.send_json(order)
                                    logger.info(f"📤 {order['side']} ${order['amount']} {order['symbol']}")
                                    
                            elif msg_type == "hive_patch":
                                strategy.on_hive_signal(data.get("parameters", {}))
                                
                            elif msg_type == "order_result":
                                if data.get("success"):
                                    logger.info(f"✅ Trade: {data.get('message')}")
                                else:
                                    pass # Silent on fail to reduce noise
                                    
            except Exception as e:
                logger.warning(f"⚠️ Connection lost ({e}). Retrying in 5s...")
                await asyncio.sleep(5)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent_id", default=f"Agent_{random.randint(1000,9999)}")
    parser.add_argument("--url", default=os.getenv("DARWIN_ARENA_URL", "wss://www.darwinx.fun"))
    args = parser.parse_args()
    
    try:
        asyncio.run(run_agent(args.agent_id, args.url))
    except KeyboardInterrupt:
        print("\n👋 Exiting...")
