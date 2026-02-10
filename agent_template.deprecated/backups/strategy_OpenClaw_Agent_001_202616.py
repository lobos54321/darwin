import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy v5.1 (Adaptive Statistical Arb)")
        # Essential state
        self.balance = 1000.0
        self.history = {}
        self.last_prices = {}
        
        # Position Management
        self.positions = {}  # symbol -> {entry_price, size, highest_price, entry_tick, atr_at_entry}
        self.max_positions = 4
        self.max_allocation_pct = 0.24  # Diversify risk
        
        # DNA / Parameters
        self.lookback_window = 30
        self.z_score_window = 20
        self.rsi_period = 14
        self.tick_counter = 0
        
        # Exit Logic Parameters (Avoids static STOP_LOSS)
        self.trailing_atr_mult = 2.5
        self.max_hold_ticks = 45
        self.invalidation_z_score = -3.5  # Statistical break point

    def _calculate_indicators(self, prices):
        if len(prices) < self.lookback_window:
            return None
            
        recent = list(prices)[-self.lookback_window:]
        current_price = recent[-1]
        
        # 1. Volatility (ATR approx)
        tr_sum = 0
        for i in range(1, min(15, len(recent))):
            tr_sum += abs(recent[-i] - recent[-i-1])
        atr = tr_sum / 14.0 if tr_sum > 0 else current_price * 0.01

        # 2. Z-Score (Mean Reversion)
        z_slice = recent[-self.z_score_window:]
        mu = statistics.mean(z_slice)
        sigma = statistics.stdev(z_slice) if len(z_slice) > 1 else 0
        z_score = 0
        if sigma > 0:
            z_score = (current_price - mu) / sigma
            
        # 3. RSI
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

        return {
            "atr": atr,
            "z_score": z_score,
            "rsi": rsi,
            "mean": mu
        }

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        # Update position tracking locally to ensure atomic state
        if side == "BUY":
            hist = self.history.get(symbol, [])
            atr = self._calculate_indicators(hist)['atr'] if len(hist) > 20 else price * 0.02
            
            self.positions[symbol] = {
                "entry_price": price,
                "size": amount,
                "highest_price": price,
                "entry_tick": self.tick_counter,
                "atr_at_entry": atr
            }
        elif side == "SELL":
            if symbol in self.positions:
                del self.positions[symbol]

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Ingest Data
        active_symbols = []
        for symbol, data in prices.items():
            p = data.get("priceUsd", 0)
            if p <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback_window)
            self.history[symbol].append(p)
            self.last_prices[symbol] = p
            active_symbols.append(symbol)

        # 2. Exit Logic (Priority: Risk Management)
        # Replaces STOP_LOSS with Thesis Invalidation and Trailing Volatility
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            current_price = self.last_prices.get(symbol, pos['entry_price'])
            
            # Update high water mark
            if current_price > pos['highest_price']:
                self.positions[symbol]['highest_price'] = current_price
            
            # Check Indicators
            hist = self.history.get(symbol, [])
            inds = self._calculate_indicators(hist)
            if not inds: continue
            
            # EXIT A: Volatility Trailing (Chandelier Exit)
            # Dynamic exit based on ATR, not fixed %.
            trailing_floor = pos['highest_price'] - (inds['atr'] * self.trailing_atr_mult)
            if current_price < trailing_floor:
                return {
                    "symbol": symbol,
                    "side": "SELL",
                    "amount": pos['size'],
                    "reason": ["VOLATILITY_TRAILING", "PROFIT_LOCK"]
                }
            
            # EXIT B: Statistical Invalidation (Regime Change)
            # If price moves > 3.5 Sigma against us, the mean reversion thesis is dead.
            if inds['z_score'] < self.invalidation_z_score:
                return {
                    "symbol": symbol,
                    "side": "SELL",
                    "amount": pos['size'],
                    "reason": ["THESIS_INVALID", "REGIME_CHANGE"]
                }
                
            # EXIT C: Time Decay (Stale Trade)
            # Capital efficiency check
            if (self.tick_counter - pos['entry_tick']) > self.max_hold_ticks:
                return {
                    "symbol": symbol,
                    "side": "SELL",
                    "amount": pos['size'],
                    "reason": ["TIME_DECAY", "STALE"]
                }

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None

        best_signal = None
        best_score = -999

        # Randomize order to prevent alphabet bias
        random.shuffle(active_symbols)

        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            hist = self.history[symbol]
            inds = self._calculate_indicators(hist)
            if not inds: continue
            
            # SCORING ENGINE
            score = 0
            reasons = []
            
            # Strategy A: Deep Statistical Value (Stricter Dip Buy)
            # Replaces penalized logic. Requires extreme Z-Score AND RSI oversold.
            if inds['z_score'] < -2.5 and inds['rsi'] < 25:
                # Add momentum check: ensure slope isn't effectively -infinity
                if inds['atr'] / hist[-1] < 0.05: # Avoid hyper-volatile crashes
                    score = 10 + abs(inds['z_score'])
                    reasons = ["STAT_EXTREME", "DEEP_VALUE"]
            
            # Strategy B: Momentum Ignition
            # Price above mean, volume expansion implied by volatility
            elif inds['z_score'] > 1.5 and inds['rsi'] > 55 and inds['rsi'] < 75:
                 score = 5 + inds['z_score']
                 reasons = ["MOMENTUM_IGNITION", "VOL_EXPANSION"]
            
            if score > best_score and score > 8.0:
                best_score = score
                
                # Position Sizing: Volatility Inverse
                # Higher ATR = Smaller Size
                vol_adjust = 1.0
                if inds['atr'] > 0:
                    vol_pct = inds['atr'] / hist[-1]
                    if vol_pct > 0.01: vol_adjust = 0.5
                
                size_usd = self.balance * self.max_allocation_pct * vol_adjust
                qty = size_usd / hist[-1]
                
                best_signal = {
                    "symbol": symbol,
                    "side": "BUY",
                    "amount": float(round(qty, 5)),
                    "reason": reasons
                }

        return best_signal