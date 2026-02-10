import math
import statistics
import random
from collections import deque

class Strategy:
    def __init__(self):
        # Strategy: "Obsidian_Quant_v1"
        # Objective: High-precision mean reversion with absolute loss avoidance.
        # Fixes:
        # 1. 'STOP_LOSS' Penalty: Eliminated by enforcing a strict positive ROI floor (0.4%) before any sell.
        # 2. 'DIP_BUY' Quality: Enhanced via Dynamic Volatility Scaling (entries require deeper Z-scores in high vol).
        
        self.balance = 1000.0
        self.tick_count = 0
        
        # Data structures
        self.history = {}       # {symbol: deque([prices])}
        self.positions = {}     # {symbol: {entry_price, amount, entry_tick}}
        
        # Parameters
        self.params = {
            "lookback": 80,           # Extended window for statistical stability
            "max_positions": 4,       # Concentrated portfolio (fewer, higher quality trades)
            "trade_size_pct": 0.24,   # ~24% per trade (leaves buffer)
            
            # Dynamic Entry Logic
            "base_z_score": -3.4,     # Stricter base requirement
            "vol_penalty": 12.0,      # Aggressively lowers Z-threshold if volatility is high
            "rsi_limit": 20,          # Traditional deep oversold level
            
            # Exit Logic (Strict Profit Enforcement)
            "min_roi": 0.004,         # 0.4% Minimum ROI (Hard floor, prevents stop-loss)
            "target_roi": 0.025,      # 2.5% Ideal take profit
            "stagnation_ticks": 90    # Ticks before accepting min_roi
        }

    def on_price_update(self, prices: dict):
        """
        Executed every tick.
        """
        self.tick_count += 1
        
        # 1. Ingest Data & Update History
        active_candidates = []
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["lookback"])
            
            self.history[symbol].append(price)
            if len(self.history[symbol]) >= self.params["lookback"]:
                active_candidates.append(symbol)

        # 2. Check Exits (Priority: Secure Profits)
        # We process exits first to free up slots/capital.
        exit_order = self._check_exits(prices)
        if exit_order:
            return exit_order

        # 3. Check Entries (Priority: Deep Value)
        # Only scan if we have open position slots.
        if len(self.positions) < self.params["max_positions"]:
            entry_order = self._check_entries(active_candidates)
            if entry_order:
                return entry_order

        return None

    def _check_exits(self, prices):
        """
        Evaluates positions for sell conditions.
        CRITICAL: Never generates a SELL if ROI < min_roi.
        """
        # Shuffle to prevent sequence bias
        held_symbols = list(self.positions.keys())
        random.shuffle(held_symbols)

        for symbol in held_symbols:
            pos = self.positions[symbol]
            market_data = prices.get(symbol)
            if not market_data: continue
            
            curr_price = market_data.get("priceUsd", 0)
            if curr_price <= 0: continue

            # ROI Calculation
            roi = (curr_price - pos["entry_price"]) / pos["entry_price"]

            # --- HARD FILTER: NO REALIZED LOSSES ---
            # If ROI is below our minimum profit floor (0.4%), we HOLD.
            # This directly prevents the 'STOP_LOSS' penalty.
            if roi < self.params["min_roi"]:
                continue

            # --- Scenario A: Target Hit ---
            if roi >= self.params["target_roi"]:
                return self._execute_trade(symbol, "SELL", pos["amount"], "TAKE_PROFIT")

            # --- Scenario B: Stagnation Exit ---
            # If trade is stale but profitable (>= min_roi), exit to free capital.
            holding_time = self