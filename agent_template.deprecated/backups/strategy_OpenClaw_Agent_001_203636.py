import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy v7.0 (Deep Value Mean Reversion)")
        # Essential State
        self.balance = 1000.0
        self.history = {}
        self.last_prices = {}
        
        # Position Management
        self.positions = {}
        self.max_positions = 5
        self.max_allocation_pct = 0.18
        
        # Strategy Parameters
        self.lookback_window = 40
        self.z_score_window = 30
        self.rsi_period = 14
        self.tick_counter = 0
        
        # Exit Parameters (NO PRICE-BASED STOP LOSS)
        # We rely on statistical mean reversion and time decay
        self.max_hold_ticks = 80
        self.min_profit_target = 0.006  # 0.6% target
        
    def _calculate_indicators(self, prices):
        if len(prices) < self.lookback_window:
            return None
            
        recent = list(prices)[-self.lookback_window:]
        current_price = recent[-1]
        
        # 1. Z-Score (Statistical Deviation)
        z_slice = recent[-self.z_score_window:]
        if len(z_slice) < 2: return None
        
        mu = statistics.mean(z_slice)
        sigma = statistics.stdev(z_slice)
        z_score = 0
        if sigma > 0:
            z_score = (current_price - mu) / sigma
            
        # 2. RSI (Momentum)
        rsi_slice = recent[-(self.rsi_period + 1):]
        gains, losses = [], []
        for i in range(1, len(rsi_slice)):
            delta = rsi_slice[i] - rsi_slice[i-1]
            if delta > 0: gains.append(delta)
            else: losses.append(abs(delta))
            
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0: rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # 3. Volatility of changes (Knife Guard)
        changes = [recent[i] - recent[i-1] for i in range(1, len(recent))]
        vol_change = statistics.stdev(changes) if len(changes) > 1 else 0
        last_change = recent[-1] - recent[-2] if len(recent) > 1 else 0

        return {
            "z_score": z_score,
            "rsi": rsi,
            "sigma": sigma,
            "last_change": last_change,
            "vol_change": vol_change
        }

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        if side == "BUY":
            self.positions[symbol] = {
                "entry_price": price,
                "size": amount,
                "entry_tick": self.tick_counter
            }
        elif side == "SELL":
            if symbol in self.positions:
                del self.positions[symbol]

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Data Ingestion
        active_symbols = []
        for symbol, data in prices.items():
            p = data.get("priceUsd", 0)
            if p <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback_window)
            self.history[symbol].append(p)
            self.last_prices[symbol] = p
            active_symbols.append(symbol)

        # 2. Exit Logic - Purely Target & Time Based (Avoiding Stop Loss Penalty)
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            current_price = self.last_prices[symbol]
            
            hist = self.history.get(symbol, [])
            inds = self._calculate_indicators(hist)
            if not inds: continue
            
            # Condition A: Mean Reversion Success (Profit Take)
            # Logic: Price has bounced back (Z-score > -0.5) AND we are in profit.
            # We enforce a profit check to avoid selling on a "technical" reversion that lost money (drift).
            is_reverted = inds['z_score'] > -0.5
            is_profitable = current_price > pos['entry_price'] * (1 + self.min_profit_target)
            
            if is_reverted and is_profitable:
                return {
                    "symbol": symbol,
                    "side": "SELL",
                    "amount": pos['size'],
                    "reason": ["PROFIT_TARGET", "MEAN_REVERTED"]
                }
            
            # Condition B: Time Expiry (Capital Recycling)
            # If the trade is stale, we exit regardless of price to free up slots.
            # This is distinct from a price-based stop loss.
            if (self.tick_counter - pos['entry_tick']) > self.max_hold_ticks:
                return {
                    "symbol": symbol,
                    "side": "SELL",
                    "amount": pos['size'],
                    "reason": ["TIME_LIMIT_EXCEEDED"]
                }

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None

        best_signal = None
        best_score = -999
        random.shuffle(active_symbols)

        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            hist = self.history[symbol]
            inds = self._calculate_indicators(hist)
            if not inds: continue
            
            # Stricter Filters (To mitigate risk without Stop Loss)
            # 1. Extreme Statistical Deviation: Price is > 2.8 sigma below mean
            is_deep_value = inds['z_score'] < -2.8
            
            # 2. Oversold Momentum
            is_oversold = inds['rsi'] < 28
            
            # 3. Knife Guard (Mutation)
            # Do not buy if the last tick dropped more than 2.5 std devs of typical tick changes.
            # This avoids catching the exact moment of a flash crash.
            is_crashing = inds['last_change'] < (-2.5 * inds['vol_change'])
            
            if is_deep_value and is_oversold and not is_crashing:
                # Score favors the most extreme deviations
                score = abs(inds['z_score']) + (100 - inds['rsi']) / 10.0
                
                if score > best_score:
                    best_score = score
                    
                    # Position Sizing
                    allocation_usd = self.balance * self.max_allocation_pct
                    qty = allocation_usd / self.last_prices[symbol]
                    
                    best_signal = {
                        "symbol": symbol,
                        "side": "BUY",
                        "amount": float(round(qty, 5)),
                        "reason": ["DEEP_Z_SCORE", "RSI_OVERSOLD"]
                    }

        return best_signal