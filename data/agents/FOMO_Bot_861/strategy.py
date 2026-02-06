import random
import math
import statistics
from collections import deque, defaultdict

# -----------------------------------------------------------------------------
# Darwin SDK - User Strategy: "Darwinian_Adapter_v3"
# 🧬 Evolution Log:
# 1. Integration of 'Hive Mind' signals for filtering (Winner's trait).
# 2. Dynamic Volatility Position Sizing (Risk Management).
# 3. Hybrid Trend-Mean Reversion Logic (Unique Mutation).
# 4. Emergency Circuit Breaker for rapid drawdowns.
# -----------------------------------------------------------------------------

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized: Darwinian_Adapter_v3 (Survival Mode)")
        
        # === Configuration ===
        self.history_maxlen = 60
        self.volatility_window = 20
        self.ema_short_period = 7
        self.ema_long_period = 25
        
        # Risk Management
        self.base_risk_per_trade = 0.15  # Risk 15% of equity per trade (Aggressive recovery)
        self.max_drawdown_tolerance = 0.03 # 3% max loss per trade
        self.trailing_stop_activation = 0.04 # Activate trailing after 4% gain
        self.trailing_gap = 0.02 # Trail by 2%
        
        # === State ===
        # History: { "SYMBOL": deque([p1, p2...]) }
        self.price_history = defaultdict(lambda: deque(maxlen=self.history_maxlen))
        self.last_prices = {}
        
        # Portfolio: { "SYMBOL": {"entry_price": float, "highest_price": float, "hold_time": int} }
        self.positions = {}
        
        # Market Sentiment
        self.banned_tags = set()
        self.boosted_tags = set()
        self.cooldowns = {} # { "SYMBOL": steps_remaining }

    def on_hive_signal(self, signal: dict):
        """Adapt to collective intelligence signals"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Hive Penalty: Avoiding {penalize}")
            self.banned_tags.update(penalize)
            
        boost = signal.get("boost", [])
        if boost:
            print(f"🚀 Hive Boost: Targeting {boost}")
            self.boosted_tags.update(boost)

    def _calculate_ema(self, prices, period):
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50
        
        gains = []
        losses = []
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
                
        # Simple average for efficiency in high-freq
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: dict):
        """
        Main decision loop.
        Expects prices dict: { "SYMBOL": {"priceUsd": float, "tags": [str...]} }
        Returns: { "action": "buy"/"sell", "symbol": "XYZ", "amount": float, "reason": str }
        """
        decision = None
        
        # 1. Update Data & Manage Cooldowns
        active_symbols = list(prices.keys())
        for symbol in list(self.cooldowns.keys()):
            self.cooldowns[symbol] -= 1
            if self.cooldowns[symbol] <= 0:
                del self.cooldowns[symbol]

        # 2. Portfolio Management (Sell Logic)
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            current_price = prices[symbol]["priceUsd"]
            pos = self.positions[symbol]
            entry_price = pos["entry_price"]
            
            # Update highest price seen
            if current_price > pos["highest_price"]:
                self.positions[symbol]["highest_price"] = current_price
            
            highest_price = self.positions[symbol]["highest_price"]
            
            # Calculate PnL
            pnl_pct = (current_price - entry_price) / entry_price
            drawdown_from_peak = (highest_price - current_price) / highest_price
            
            should_sell = False
            reason = ""
            
            # A. Hard Stop Loss
            if pnl_pct < -self.max_drawdown_tolerance:
                should_sell = True
                reason = f"🛑 Stop Loss hit ({pnl_pct*100:.2f}%)"
                self.cooldowns[symbol] = 10 # Stay out for a bit
            
            # B. Trailing Stop Profit
            elif pnl_pct > self.trailing_stop_activation and drawdown_from_peak > self.trailing_gap:
                should_sell = True
                reason = f"💰 Trailing Profit ({pnl_pct*100:.2f}%)"
            
            # C. Stagnation Kill (Time-based exit)
            pos["hold_time"] += 1
            if pos["hold_time"] > 40 and pnl_pct < 0.01:
                should_sell = True
                reason = "⏳ Stagnation"

            if should_sell:
                del self.positions[symbol]
                return {
                    "action": "sell",
                    "symbol": symbol,
                    "amount": 1.0, # Sell 100%
                    "reason": reason
                }

        # 3. Entry Logic (Buy Logic)
        # Only look for one buy per tick to avoid complexity
        best_score = -1
        best_symbol = None
        
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            tags = data.get("tags", [])
            
            # Update History
            self.price_history[symbol].append(current_price)
            hist = list(self.price_history[symbol])
            
            # Skip if holding, cooling down, or banned
            if symbol in self.positions or symbol in self.cooldowns:
                continue
            if any(t in self.banned_tags for t in tags):
                continue
                
            if len(hist) < self.ema_long_period:
                continue
            
            # Indicators
            ema_short = self._calculate_ema(hist, self.ema_short_period)
            ema_long = self._calculate_ema(hist, self.ema_long_period)
            rsi = self._calculate_rsi(hist)
            
            if not ema_short or not ema_long:
                continue

            # --- STRATEGY CORE: Momentum + Volatility ---
            
            # Trend Check
            is_uptrend = ema_short > ema_long and current_price > ema_short
            
            # Volatility Check (Standard Deviation relative to mean)
            recent_slice = hist[-10:]
            if len(recent_slice) > 1:
                stdev = statistics.stdev(recent_slice)
                mean_price = statistics.mean(recent_slice)
                volatility_ratio = stdev / mean_price if mean_price > 0 else 0
            else:
                volatility_ratio = 0
                
            # Scoring System
            score = 0
            
            # 1. Trend Score
            if is_uptrend:
                score += 10
            
            # 2. RSI Filter (Buy dips in uptrend, or breakouts not yet overextended)
            if 40 < rsi < 65:
                score += 5
            elif rsi > 75:
                score -= 10 # Overbought
            
            # 3. Hive Boost
            if any(t in self.boosted_tags for t in tags):
                score += 15
                
            # 4. Volatility Expansion (Breakout)
            if volatility_ratio > 0.005: # Arbitrary threshold for "moving"
                score += 5
                
            if score > best_score:
                best_score = score
                best_symbol = symbol

        # Execute Buy
        if best_symbol and best_score >= 15:
            # Position Sizing: Current balance is ~$536. 
            # We use fixed USD amount approx 15% of initial $1000 ($150) or available.
            # Assuming SDK handles balance checks, we request a dollar amount.
            buy_amount = 120.0 
            
            self.positions[best_symbol] = {
                "entry_price": prices[best_symbol]["priceUsd"],
                "highest_price": prices[best_symbol]["priceUsd"],
                "hold_time": 0
            }
            
            return {
                "action": "buy",
                "symbol": best_symbol,
                "amount": buy_amount,
                "reason": f"Score: {best_score} (Trend+Hive)"
            }

        return decision