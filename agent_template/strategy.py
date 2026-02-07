"""
Darwin Arena Active Trading Strategy v2.0
Designed for 10-minute epochs with real-time MEME/Contract price feeds.

Key changes from v1:
- Lower thresholds for faster signal generation
- Position management (TP/SL tracking)
- Sell logic (not just buy)
- Shorter warmup period
- Higher exploration rate

Technique: Bollinger Bands + RSI + Position Management
"""

import random
import statistics
from collections import deque


class MyStrategy:
    def __init__(self):
        print("🧠 Strategy v2.0 (Active Trading + Position Management)")
        self.last_prices = {}
        self.history = {}
        self.banned_tags = set()
        self.balance = 1000.0

        # === Position Tracking ===
        self.current_positions = {}   # {symbol: amount_usd}
        self.entry_prices = {}        # {symbol: entry_price}
        self.max_positions = 4        # Max concurrent positions
        self.max_position_pct = 0.15  # Max 15% of balance per position

        # === Strategy Parameters (tuned for 10-min epochs) ===
        self.history_window = 30      # 30 ticks = 5 min of data at 10s intervals
        self.sma_period = 10          # Shorter SMA for faster signals
        self.base_z_score = -1.2      # Much more sensitive than -2.2
        self.rsi_period = 8           # Shorter RSI for faster signals
        self.oversold_threshold = 40  # More generous (was 27)
        self.overbought_threshold = 65  # For sell signals
        self.risk_per_trade = 30.0
        self.min_band_width = 0.001   # Lower minimum volatility

        # === TP/SL (percentage based) ===
        self.take_profit_pct = 0.03   # +3% take profit
        self.stop_loss_pct = 0.05     # -5% stop loss

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)
            print(f"🚫 Banned tags updated: {self.banned_tags}")

        boost = signal.get("boost", [])
        if boost:
            if "DIP_BUY" in boost or "OVERSOLD" in boost:
                self.oversold_threshold = min(50, self.oversold_threshold + 5)
                self.base_z_score = min(-0.8, self.base_z_score + 0.2)
            if "MOMENTUM" in boost:
                self.overbought_threshold = min(75, self.overbought_threshold + 5)

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Track position after a trade is executed"""
        if side.upper() == "BUY":
            self.current_positions[symbol] = self.current_positions.get(symbol, 0) + amount
            self.entry_prices[symbol] = price
        elif side.upper() == "SELL":
            self.current_positions.pop(symbol, None)
            self.entry_prices.pop(symbol, None)

    def _calculate_rsi(self, prices):
        """Calculate RSI from price history"""
        if len(prices) < self.rsi_period + 1:
            return 50.0

        recent_prices = list(prices)[-(self.rsi_period + 1):]
        gains = []
        losses = []

        for i in range(1, len(recent_prices)):
            change = recent_prices[i] - recent_prices[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: dict):
        """
        Main decision loop. Called every price tick (~10 seconds).
        Priority: 1) Manage existing positions  2) Open new positions
        """
        symbols = list(prices.keys())
        random.shuffle(symbols)

        # Update all history first
        for symbol in symbols:
            data = prices[symbol]
            current_price = data.get("priceUsd", 0)
            if current_price <= 0:
                continue

            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(current_price)
            self.last_prices[symbol] = current_price

        # === PHASE 1: Position Management (check TP/SL) ===
        for symbol in list(self.current_positions.keys()):
            if symbol not in self.last_prices or symbol not in self.entry_prices:
                continue

            current_price = self.last_prices[symbol]
            entry_price = self.entry_prices[symbol]

            if entry_price <= 0:
                continue

            pnl_pct = (current_price - entry_price) / entry_price

            # Take Profit
            if pnl_pct >= self.take_profit_pct:
                sell_amount = self.current_positions.get(symbol, 0)
                if sell_amount > 0:
                    return {
                        "symbol": symbol,
                        "side": "sell",
                        "amount": round(sell_amount * current_price, 2),
                        "reason": ["TAKE_PROFIT", f"PNL_{pnl_pct*100:.1f}%"]
                    }

            # Stop Loss
            if pnl_pct <= -self.stop_loss_pct:
                sell_amount = self.current_positions.get(symbol, 0)
                if sell_amount > 0:
                    return {
                        "symbol": symbol,
                        "side": "sell",
                        "amount": round(sell_amount * current_price, 2),
                        "reason": ["STOP_LOSS", f"PNL_{pnl_pct*100:.1f}%"]
                    }

        # === PHASE 2: New Entries (if room for more positions) ===
        if len(self.current_positions) >= self.max_positions:
            return None  # Full, wait for exits

        for symbol in symbols:
            current_price = self.last_prices.get(symbol, 0)
            if current_price <= 0:
                continue

            # Already have a position in this symbol
            if symbol in self.current_positions:
                continue

            # Need minimum history
            if len(self.history.get(symbol, [])) < self.sma_period + 2:
                continue

            # --- Statistical Calculations ---
            recent_window = list(self.history[symbol])[-self.sma_period:]
            sma = statistics.mean(recent_window)
            stdev = statistics.stdev(recent_window)

            if stdev == 0:
                continue

            z_score = (current_price - sma) / stdev
            band_width = (4 * stdev) / sma
            rsi = self._calculate_rsi(self.history[symbol])

            decision = None

            # STRATEGY A: Mean Reversion Buy (oversold + deviated)
            is_oversold = rsi < self.oversold_threshold
            is_deviated = z_score < self.base_z_score
            has_volatility = band_width > self.min_band_width

            if is_deviated and is_oversold and has_volatility:
                amount = min(self.risk_per_trade, self.balance * self.max_position_pct)
                decision = {
                    "symbol": symbol,
                    "side": "buy",
                    "amount": round(amount, 2),
                    "reason": ["DIP_BUY", "OVERSOLD"]
                }

            # STRATEGY B: Momentum Buy (strong uptrend)
            elif z_score > 0.8 and rsi > 55 and rsi < self.overbought_threshold and has_volatility:
                amount = min(self.risk_per_trade * 0.7, self.balance * self.max_position_pct)
                decision = {
                    "symbol": symbol,
                    "side": "buy",
                    "amount": round(amount, 2),
                    "reason": ["MOMENTUM", "TREND_FOLLOW"]
                }

            # STRATEGY C: Mean Reversion Sell (overbought — sell if we have position)
            elif z_score > 1.5 and rsi > self.overbought_threshold and symbol in self.current_positions:
                sell_amount = self.current_positions[symbol]
                if sell_amount > 0:
                    decision = {
                        "symbol": symbol,
                        "side": "sell",
                        "amount": round(sell_amount * current_price, 2),
                        "reason": ["OVERBOUGHT", "MEAN_REVERT_SELL"]
                    }

            # STRATEGY D: Exploration (random probe trades for genetic diversity)
            elif random.random() < 0.08 and has_volatility:
                side = "buy" if random.random() > 0.4 else "sell"
                # Only sell if we have a position
                if side == "sell" and symbol not in self.current_positions:
                    side = "buy"
                amount = min(15.0, self.balance * 0.05)  # Small probe
                decision = {
                    "symbol": symbol,
                    "side": side,
                    "amount": round(amount, 2),
                    "reason": ["RANDOM_TEST"]
                }

            # --- Execution Check ---
            if decision:
                tags = decision.get("reason", [])
                if any(tag in self.banned_tags for tag in tags):
                    continue
                return decision

        return None

    def get_council_message(self, is_winner: bool) -> str:
        """Called during Council phase."""
        pos_count = len(self.current_positions)
        if is_winner:
            return f"Active position management with TP/SL worked well. {pos_count} positions managed. Z-score + RSI confluence filtered noise."
        else:
            return f"Strategy needs adjustment. Had {pos_count} positions. Considering tighter stops and faster entries."
