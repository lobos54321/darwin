"""
Bot Agents - In-process demo agents that keep the Arena alive.

These lightweight bots run inside the arena server process, trading
directly via the MatchingEngine API. No WebSocket connection needed.

Purpose:
- Dashboard is never empty after server restart
- Always-on activity for demo/showcase
- Provide baseline competition for real agents
"""

import asyncio
import random
import logging
import statistics
from collections import deque
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Bot profiles: each has a distinct trading personality
BOT_PROFILES = [
    {"id": "Bot_Alpha", "style": "momentum", "aggression": 0.7},
    {"id": "Bot_Beta", "style": "mean_revert", "aggression": 0.5},
    {"id": "Bot_Gamma", "style": "breakout", "aggression": 0.6},
]

NUM_BOTS = len(BOT_PROFILES)


class BotStrategy:
    """Simple rule-based strategy for demo bots."""

    def __init__(self, style: str, aggression: float):
        self.style = style
        self.aggression = aggression
        self.history: Dict[str, deque] = {}
        self.positions: Dict[str, float] = {}  # symbol -> amount
        self.entry_prices: Dict[str, float] = {}
        self.balance = 1000.0

    def on_prices(self, prices: dict) -> Optional[dict]:
        """Evaluate prices and return an order or None."""
        for sym, pdata in prices.items():
            price = pdata.get("priceUsd", 0) if isinstance(pdata, dict) else 0
            if price <= 0:
                continue
            if sym not in self.history:
                self.history[sym] = deque(maxlen=30)
            self.history[sym].append(price)

        # Check exits first
        exit_order = self._check_exits(prices)
        if exit_order:
            return exit_order

        # Max 2 positions
        if len(self.positions) >= 2:
            return None

        # Evaluate entries
        symbols = list(prices.keys())
        random.shuffle(symbols)
        for sym in symbols:
            if sym in self.positions:
                continue
            hist = self.history.get(sym, [])
            if len(hist) < 8:
                continue
            order = self._evaluate_entry(sym, list(hist))
            if order:
                return order
        return None

    def _check_exits(self, prices: dict) -> Optional[dict]:
        for sym, amt in list(self.positions.items()):
            pdata = prices.get(sym, {})
            cur = pdata.get("priceUsd", 0) if isinstance(pdata, dict) else 0
            entry = self.entry_prices.get(sym, 0)
            if cur <= 0 or entry <= 0:
                continue
            pnl = (cur - entry) / entry

            # Take profit at 3%
            if pnl >= 0.03:
                return {"symbol": sym, "side": "SELL", "amount": round(amt * cur * 0.98, 2),
                        "reason": ["TAKE_PROFIT"]}
            # Stop loss at 4%
            if pnl <= -0.04:
                return {"symbol": sym, "side": "SELL", "amount": round(amt * cur * 0.98, 2),
                        "reason": ["STOP_LOSS"]}
        return None

    def _evaluate_entry(self, symbol: str, hist: list) -> Optional[dict]:
        cur = hist[-1]
        avg = statistics.mean(hist)
        std = statistics.stdev(hist) if len(hist) > 1 else 0

        # Skip if no volatility
        if std == 0 or avg == 0:
            return None

        z_score = (cur - avg) / std
        size = round(min(25.0 * self.aggression, self.balance * 0.12), 2)
        if size < 5:
            return None

        if self.style == "momentum":
            # Buy when price is trending up
            if z_score > 0.5 and hist[-1] > hist[-2] > hist[-3]:
                return {"symbol": symbol, "side": "BUY", "amount": size,
                        "reason": ["MOMENTUM", "BOT"]}

        elif self.style == "mean_revert":
            # Buy when oversold
            if z_score < -1.0:
                return {"symbol": symbol, "side": "BUY", "amount": size,
                        "reason": ["DIP_BUY", "BOT"]}

        elif self.style == "breakout":
            # Buy on new highs
            recent_high = max(hist[:-1]) if len(hist) > 1 else cur
            if cur > recent_high and z_score > 0.3:
                return {"symbol": symbol, "side": "BUY", "amount": size,
                        "reason": ["BREAKOUT", "BOT"]}

        # Small exploration chance
        if random.random() < 0.02:
            return {"symbol": symbol, "side": "BUY", "amount": round(min(10.0, self.balance * 0.03), 2),
                    "reason": ["RANDOM_TEST", "BOT"]}

        return None


class BotManager:
    """Manages in-process bot agents."""

    def __init__(self, group_manager, trade_counter_fn=None):
        self.group_manager = group_manager
        self.bots: Dict[str, BotStrategy] = {}
        self._task: Optional[asyncio.Task] = None
        self._trade_counter_fn = trade_counter_fn  # callback(amount) to increment global counters

    async def spawn_bots(self):
        """Register bot agents and start their trading loop."""
        for profile in BOT_PROFILES:
            agent_id = profile["id"]
            group = await self.group_manager.assign_agent(agent_id)
            strategy = BotStrategy(style=profile["style"], aggression=profile["aggression"])
            strategy.balance = self.group_manager.get_balance(agent_id)
            self.bots[agent_id] = strategy
            logger.info(f"🤖 Bot spawned: {agent_id} ({profile['style']}) → Group {group.group_id}")

        self._task = asyncio.create_task(self._trading_loop())
        logger.info(f"🤖 {len(self.bots)} demo bots active")

    async def _trading_loop(self):
        """Main loop: every 10 seconds, each bot evaluates prices and may trade."""
        from matching import OrderSide

        while True:
            try:
                await asyncio.sleep(10)

                for agent_id, strategy in self.bots.items():
                    group = self.group_manager.get_group(agent_id)
                    if not group:
                        continue

                    prices = group.feeder.prices
                    if not prices:
                        continue

                    # Update balance from engine
                    strategy.balance = self.group_manager.get_balance(agent_id)

                    order = strategy.on_prices(prices)
                    if not order:
                        continue

                    side = OrderSide.BUY if order["side"] == "BUY" else OrderSide.SELL
                    success, msg, fill_price = self.group_manager.execute_order(
                        agent_id, order["symbol"], side, order["amount"], order.get("reason", [])
                    )

                    if success:
                        # Update local position tracking
                        if order["side"] == "BUY" and fill_price > 0:
                            amt = order["amount"] / fill_price
                            strategy.positions[order["symbol"]] = strategy.positions.get(order["symbol"], 0) + amt
                            strategy.entry_prices[order["symbol"]] = fill_price
                        elif order["side"] == "SELL":
                            strategy.positions.pop(order["symbol"], None)
                            strategy.entry_prices.pop(order["symbol"], None)

                        strategy.balance = self.group_manager.get_balance(agent_id)

                        if self._trade_counter_fn:
                            self._trade_counter_fn(order["amount"])

                        logger.debug(f"🤖 {agent_id}: {order['side']} {order['symbol']} ${order['amount']:.2f}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Bot trading loop error: {e}")

    def stop(self):
        """Stop the bot trading loop."""
        if self._task and not self._task.done():
            self._task.cancel()
