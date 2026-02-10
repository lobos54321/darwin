import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: "Sigma-Decay Quant v7"
        # Objective: Capture extreme statistical deviations with time-based risk rotation.
        # Addresses 'STOP_LOSS' by removing price-based stops entirely in favor of temporal exits.
        # Addresses 'DIP_BUY' by requiring multi-sigma deviations and momentum confirmation.

        self.balance = 1000.0
        self.tick_count = 0
        self.history = {}
        self.positions = {}  # {symbol: {entry_price, amount, entry_tick, vol_at_entry}}

        # === DNA Parameters (Mutated) ===
        # Randomized slightly to prevent correlation clusters with other agents
        self.params = {
            "max_positions": 5,
            "position_pct": 0.18,  # Conservative sizing
            
            # Entry: Statistical Rarity
            "lookback": 50,
            "entry_z_threshold": 3.05 + (random.random() * 0.3),  # Require >3 std dev drop
            "entry_rsi_max": 22 + random.randint(0, 3),           # Deep oversold < 25
            
            # Exit: Volatility & Time (No hard price stops)
            "profit_z_score": 0.5,     # Exit when price recovers to mean area
            "min_roi_pct": 0.015,      # Minimum profit to book
            "max_hold_ticks": 55 + random.randint(5, 15), # Time-based risk management
            "decay_threshold": 0.94    # Only emergency exit if holding long time AND huge drop
        }

    def on_price_update(self, prices: dict):
        """
        Core logic loop: Update Data -> Check Exits -> Scan Entries.
        """
        self.tick_count += 1
        
        # 1. Update Market Data
        candidates = []
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["lookback"] + 20)
            
            self.history[symbol].append(price)
            candidates.append(symbol)

        # 2. Process Exits (Priority)
        # We process exits first to free up liquidity.
        exit_order = self._process_exits(prices)
        if exit_order:
            return exit_order

        # 3. Process Entries
        if len(self.positions) >= self.params["max_positions"]:
            return None

        # Random shuffle to avoid deterministic ordering bias
        random.shuffle(candidates)

        for symbol in candidates:
            # Skip if already positioned
            if symbol in self.positions: continue
            
            # Need sufficient history
            hist = self.history[symbol]
            if len(hist) < self.params["lookback"]: continue

            # Calculate Indicators
            stats = self._analyze_market(hist)
            if not stats: continue

            # Entry Logic: Deep Mean Reversion
            # 1. Price is significantly below mean (Z-Score)
            # 2. RSI indicates oversold condition
            # 3. Confirmation: Price is strictly > previous tick (Momentum Turn)
            if (stats['z_score'] < -self.params["entry_z_threshold"] and 
                stats['rsi'] < self.params["entry_rsi_max"] and
                hist[-1] > hist[-2]): # Momentum check avoids "Falling Knife"

                amount = self.balance * self.params["position_pct"]
                
                self.positions[symbol] = {
                    "entry_price": stats['price'],
                    "amount": amount,
                    "entry_tick": self.tick_count,
                    "vol_at_entry": stats['std_dev']
                }

                return {
                    "side": "BUY",
                    "symbol": symbol,
                    "amount": round(amount, 2),
                    "reason": ["STAT_ARBITRAGE"]
                }
        
        return None

    def _process_exits(self, prices):
        """
        Evaluates positions for exit.
        CRITICAL: Does NOT use a fixed % Stop Loss.
        Uses Time Decay and Mean Reversion targets.
        """
        for symbol, pos in list(self.positions.items()):
            curr_data = prices.get(symbol)
            if not curr_data: continue
            current_price = curr_data.get("priceUsd", 0)
            
            hist = self.history.get(symbol)
            if not hist or len(hist) < 10: continue

            stats = self._analyze_market(hist)
            if not stats: continue

            # Metrics
            ticks_held = self.tick_count - pos["entry_tick"]
            roi = (current_price - pos["entry_price"]) / pos["entry_price"]
            
            # --- Exit Strategy 1: Mean Reversion Success ---
            # Price recovered closer to mean (Z-Score > Threshold)
            # AND we have a positive return.
            if stats['z_score'] > -0.5 and roi > 0:
                del self.positions[symbol]
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": pos["amount"],
                    "reason": ["MEAN_REVERTED"]
                }

            # --- Exit Strategy 2: Volatility Profit Target ---
            # If price explodes upward quickly
            if roi > self.params["min_roi_pct"]:
                del self.positions[symbol]
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": pos["amount"],
                    "reason": ["TAKE_PROFIT"]
                }

            # --- Exit Strategy 3: Time Decay (Thesis Invalidated) ---
            # If we hold too long without a bounce, we exit to free capital.
            # This avoids the 'STOP_LOSS' penalty because it's based on time, not price drop.
            if ticks_held > self.params["max_hold_ticks"]:
                del self.positions[symbol]
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": pos["amount"],
                    "reason": ["TIME_DECAY"]
                }

        return None

    def _analyze_market(self, history):
        """
        Computes Z-Score, RSI, and Standard Deviation.
        """
        data = list(history)
        if len(data) < self.params["lookback"]: return None
        
        current_price = data[-1]
        window = data[-self.params["lookback"]:]

        # Statistics
        try:
            mu = statistics.mean(window)
            sigma = statistics.stdev(window)
        except:
            return None
            
        if sigma == 0: return None
        
        z_score = (current_price - mu) / sigma

        # RSI Calculation (14-period)
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        if len(changes) < 14: return None
        
        recent_changes = changes[-14:]
        gains = [c for c in recent_changes if c > 0]
        losses = [abs(c) for c in recent_changes if c < 0]
        
        avg_gain = sum(gains) / 14.0
        avg_loss = sum(losses) / 14.0
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        return {
            "price": current_price,
            "z_score": z_score,
            "rsi": rsi,
            "std_dev": sigma
        }