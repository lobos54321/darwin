#!/usr/bin/env python3
"""
Darwin Arena Agent v2.0 - Active Trading Edition
Single-file autonomous trading agent for Project Darwin.

Features:
- Active Trading: buys AND sells (TP/SL position management)
- 4 strategies: DIP_BUY, MOMENTUM, OVERBOUGHT_SELL, RANDOM_TEST
- Council participation with strategy insights
- Hive Mind integration (boost/penalize adaptation)
- Self-healing WebSocket connection

Usage:
  python3 darwin_agent.py --agent_id="MyAgent"
  python3 darwin_agent.py --agent_id="MyAgent" --url="wss://www.darwinx.fun"
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Darwin")


# ==========================================
# STRATEGY: Active Trading v2.0
# ==========================================
class ActiveStrategy:
    """
    Active trading strategy with position management.
    Designed for 10-minute epochs with real-time price feeds.
    """
    def __init__(self):
        self.history = {}
        self.banned_tags = set()
        self.balance = 1000.0
        self.current_positions = {}
        self.entry_prices = {}

        # Parameters (tuned for 10-min epochs)
        self.sma_period = 10
        self.base_z_score = -1.2
        self.rsi_period = 8
        self.oversold_threshold = 40
        self.overbought_threshold = 65
        self.risk_per_trade = 30.0
        self.take_profit_pct = 0.03
        self.stop_loss_pct = 0.05

    def on_hive_signal(self, signal: dict):
        """Adapt to Hive Mind patches"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)
            logger.info(f"Hive Mind: Banning {penalize}")
        boost = signal.get("boost", [])
        if boost:
            if "DIP_BUY" in boost or "OVERSOLD" in boost:
                self.oversold_threshold = min(50, self.oversold_threshold + 5)
                self.base_z_score = min(-0.8, self.base_z_score + 0.2)

    def _rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0
        recent = list(prices)[-(self.rsi_period + 1):]
        gains, losses = [], []
        for i in range(1, len(recent)):
            d = recent[i] - recent[i - 1]
            gains.append(max(0, d))
            losses.append(max(0, -d))
        ag = statistics.mean(gains) if gains else 0
        al = statistics.mean(losses) if losses else 0
        if al == 0:
            return 100.0 if ag > 0 else 50.0
        return 100 - (100 / (1 + ag / al))

    def on_price_update(self, prices: dict):
        symbols = list(prices.keys())
        random.shuffle(symbols)

        # Update history
        for sym in symbols:
            p = prices[sym].get("priceUsd", 0)
            if p <= 0:
                continue
            if sym not in self.history:
                self.history[sym] = deque(maxlen=30)
            self.history[sym].append(p)

        # Phase 1: Position management (TP/SL)
        for sym in list(self.current_positions.keys()):
            if sym not in self.history or sym not in self.entry_prices:
                continue
            cur = self.history[sym][-1]
            entry = self.entry_prices[sym]
            if entry <= 0:
                continue
            pnl = (cur - entry) / entry
            if pnl >= self.take_profit_pct:
                amt = self.current_positions[sym]
                return {"symbol": sym, "side": "SELL", "amount": round(amt * cur, 2),
                        "reason": ["TAKE_PROFIT"]}
            if pnl <= -self.stop_loss_pct:
                amt = self.current_positions[sym]
                return {"symbol": sym, "side": "SELL", "amount": round(amt * cur, 2),
                        "reason": ["STOP_LOSS"]}

        # Phase 2: New entries
        if len(self.current_positions) >= 4:
            return None

        for sym in symbols:
            if sym in self.current_positions:
                continue
            hist = self.history.get(sym, [])
            if len(hist) < self.sma_period + 2:
                continue

            cur = hist[-1]
            window = list(hist)[-self.sma_period:]
            sma = statistics.mean(window)
            std = statistics.stdev(window)
            if std == 0:
                continue

            z = (cur - sma) / std
            bw = (4 * std) / sma
            rsi = self._rsi(hist)

            decision = None

            # A: Mean Reversion Buy
            if z < self.base_z_score and rsi < self.oversold_threshold and bw > 0.001:
                amt = min(self.risk_per_trade, self.balance * 0.15)
                decision = {"symbol": sym, "side": "BUY", "amount": round(amt, 2),
                            "reason": ["DIP_BUY", "OVERSOLD"]}

            # B: Momentum Buy
            elif z > 0.8 and 55 < rsi < self.overbought_threshold and bw > 0.001:
                amt = min(self.risk_per_trade * 0.7, self.balance * 0.15)
                decision = {"symbol": sym, "side": "BUY", "amount": round(amt, 2),
                            "reason": ["MOMENTUM", "TREND_FOLLOW"]}

            # C: Exploration
            elif random.random() < 0.08 and bw > 0.001:
                amt = min(15.0, self.balance * 0.05)
                decision = {"symbol": sym, "side": "BUY", "amount": round(amt, 2),
                            "reason": ["RANDOM_TEST"]}

            if decision:
                if any(t in self.banned_tags for t in decision.get("reason", [])):
                    continue
                return decision

        return None


# ==========================================
# CLIENT: WebSocket Connection
# ==========================================
async def run_agent(agent_id, arena_url):
    try:
        import aiohttp
    except ImportError:
        print("Missing: pip install aiohttp")
        sys.exit(1)

    strategy = ActiveStrategy()
    logger.info(f"Agent '{agent_id}' starting...")

    async with aiohttp.ClientSession() as session:
        # 1. Register
        http_url = arena_url.replace("wss://", "https://").replace("ws://", "http://")
        try:
            async with session.post(f"{http_url}/auth/register?agent_id={agent_id}") as resp:
                if resp.status != 200:
                    logger.error(f"Registration failed: {resp.status}")
                    return
                data = await resp.json()
                api_key = data.get("api_key")
                logger.info(f"Registered! Key: {api_key[:8]}...")
        except Exception as e:
            logger.error(f"Auth error: {e}")
            return

        # 2. Connect & Loop
        ws_url = f"{arena_url}/ws/{agent_id}?api_key={api_key}"
        while True:
            try:
                async with session.ws_connect(ws_url) as ws:
                    logger.info("Connected to Arena!")

                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        data = json.loads(msg.data)
                        msg_type = data.get("type")

                        if msg_type == "welcome":
                            strategy.balance = data.get("balance", 1000)
                            # Sync positions
                            for sym, pdata in data.get("positions", {}).items():
                                amt = pdata.get("amount", 0) if isinstance(pdata, dict) else pdata
                                avg = pdata.get("avg_price", 0) if isinstance(pdata, dict) else 0
                                if amt > 0:
                                    strategy.current_positions[sym] = amt
                                    strategy.entry_prices[sym] = avg
                            logger.info(f"Welcome! Epoch {data.get('epoch')}, Balance: ${strategy.balance:.2f}")

                        elif msg_type == "price_update":
                            order = strategy.on_price_update(data.get("prices", {}))
                            if order:
                                order["type"] = "order"
                                await ws.send_json(order)
                                logger.info(f"ORDER: {order['side']} {order['symbol']} ${order['amount']:.2f} [{','.join(order['reason'])}]")

                        elif msg_type == "order_result":
                            if data.get("success"):
                                strategy.balance = data.get("balance", strategy.balance)
                                # Sync positions from server
                                strategy.current_positions = {}
                                for sym, pdata in data.get("positions", {}).items():
                                    amt = pdata.get("amount", 0) if isinstance(pdata, dict) else pdata
                                    avg = pdata.get("avg_price", 0) if isinstance(pdata, dict) else 0
                                    if amt > 0:
                                        strategy.current_positions[sym] = amt
                                        if sym not in strategy.entry_prices:
                                            strategy.entry_prices[sym] = avg
                                logger.info(f"Trade OK! Balance: ${strategy.balance:.2f}")
                            else:
                                logger.warning(f"Trade failed: {data.get('message', '')}")

                        elif msg_type == "epoch_end":
                            rankings = data.get("rankings", [])
                            for i, r in enumerate(rankings):
                                if r.get("agent_id") == agent_id:
                                    logger.info(f"Epoch {data.get('epoch')} ended. Rank #{i+1}/{len(rankings)} PnL: {r.get('pnl', 0):+.2f}%")
                                    break

                        elif msg_type == "council_open":
                            winner = data.get("winner", "")
                            role = "winner" if winner == agent_id else "insight"
                            msg_content = f"Z-score threshold at {strategy.base_z_score:.1f}, RSI at {strategy.oversold_threshold}. Positions: {len(strategy.current_positions)}."
                            await ws.send_json({"type": "council_submit", "role": role, "content": msg_content})

                        elif msg_type == "hive_patch":
                            params = data.get("parameters", {})
                            strategy.on_hive_signal(params)
                            boost = params.get("boost", [])
                            penalize = params.get("penalize", [])
                            if boost or penalize:
                                logger.info(f"Hive Mind: boost={boost} penalize={penalize}")

            except Exception as e:
                logger.warning(f"Connection lost ({e}). Retrying in 5s...")
                await asyncio.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Darwin Arena Agent v2.0")
    parser.add_argument("--agent_id", default=f"Agent_{random.randint(1000,9999)}")
    parser.add_argument("--url", default=os.getenv("DARWIN_ARENA_URL", "wss://www.darwinx.fun"))
    args = parser.parse_args()

    try:
        asyncio.run(run_agent(args.agent_id, args.url))
    except KeyboardInterrupt:
        print("\nExiting...")
