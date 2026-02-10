import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy v6.0 (Adaptive Volatility Arb)")
        # Essential state
        self.balance = 1000.0
        self.history = {}
        self.last_prices = {}
        
        # Position Management
        # symbol -> {entry_price, size, highest_price, entry_tick, atr_at_entry}
        self.positions = {}
        self.max_positions = 5
        self.max_allocation_pct = 0.18  # Conservative sizing
        
        # Strategy Parameters
        self.lookback_window = 35
        self.z_score_window = 20
        self.rsi_period = 14
        self.tick_counter = 0
        
        # Dynamic Exit Parameters (Replaces Static STOP_LOSS)
        self.trailing_atr_mult = 3.0  # Wider trailing to allow breathing room
        self.max_hold_ticks = 50      # Time-based stop
        self.invalidation_z_score = -4.0  # Regime change threshold

    def _calculate_indicators(self, prices):
        if len(prices) < self.lookback_window:
            return None
            
        recent = list(prices)[-self.lookback_window:]
        current_price = recent[-1]
        
        # 1. Volatility (ATR approximation)
        tr_sum = 0
        for i in range(1, min(15, len(recent))):
            tr_sum += abs(recent[-i] - recent[-i-1])
        atr = tr_sum / 14.0 if tr_sum > 0 else current_price * 0.01

        # 2. Z-Score (Mean Reversion)
        z_slice = recent[-self.z_score_window:]
        if len(z_slice) < 2: return None
        
        mu = statistics.mean(z_slice)
        sigma = statistics.stdev(z_slice)
        z_score = 0
        if sigma > 0:
            z_score = (current_price - mu) / sigma
            
        # 3. RSI
        rsi_slice = recent[-(self.rsi_period + 1):]
        if len(rsi_slice) < 2: return None
        
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
            "mean": mu,
            "sigma": sigma
        }

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        # Update position tracking locally
        if side == "BUY":
            hist = self.history.get(symbol, [])
            atr = 0
            if hist:
                 inds = self._calculate_indicators(hist)
                 if inds: atr = inds['atr']
            if atr == 0: atr = price * 0.02
            
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

        # 2. Exit Logic (Replaces Penalized STOP_LOSS)
        # Using Dynamic Volatility Trailing and Statistical Invalidation
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            current_price = self.last_prices.get(symbol, pos['entry_price'])
            
            # Update high water mark for trailing
            if current_price > pos['highest_price']:
                self.positions[symbol]['highest_price'] = current_price
            
            hist = self.history.get(symbol, [])
            inds = self._calculate_indicators(hist)
            if not inds: continue
            
            # EXIT A: Chandelier Exit (Trailing Volatility)
            # If price drops 3 ATRs from the highest point since entry, exit.
            # This adapts to market noise rather than a fixed % drop.
            trailing_floor = pos['highest_price'] - (inds['atr'] * self.trailing_atr_mult)
            if current_price < trailing_floor:
                return {
                    "symbol": symbol,
                    "side": "SELL",
                    "amount": pos['size'],
                    "reason": ["VOLATILITY_TRAILING", "DYNAMIC_EXIT"]
                }
            
            # EXIT B: Thesis Invalidation (Regime Change)
            # If Z-Score drops significantly below entry expectations (e.g. < -4.0),
            # the mean reversion thesis has failed (crash/black swan).
            if inds['z_score'] < self.invalidation_z_score:
                return {
                    "symbol": symbol,
                    "side": "SELL",
                    "amount": pos['size'],
                    "reason": ["THESIS_INVALID", "REGIME_CHANGE"]
                }
                
            # EXIT C: Time Decay (Stale Trade)
            if (self.tick_counter - pos['entry_tick']) > self.max_hold_ticks:
                return {
                    "symbol": symbol,
                    "side": "SELL",
                    "amount": pos['size'],
                    "reason": ["TIME_DECAY", "STALE_CAPITAL"]
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
            
            score = 0
            reasons = []
            
            # Stricter Criteria to ensure high probability
            is_oversold = inds['rsi'] < 30
            is_deep_value = inds['z_score'] < -2.2
            
            # Mutation: Volatility Contraction check
            # Don't buy if volatility is exploding (falling knife)
            vol_ratio = inds['atr'] / (hist[-1] * 0.05) 
            stable_vol = vol_ratio < 1.5
            
            if is_oversold and is_deep_value and stable_vol:
                # Score based on how extreme the deviation is
                score = abs(inds['z_score']) + (100 - inds['rsi']) / 10.0
                reasons = ["STAT_VALUE", "RSI_CONFLUENCE"]
                
                # Boost score if price is stabilizing (derivative check)
                if len(hist) > 3:
                     # Check if the rate of descent is slowing
                     delta1 = hist[-2] - hist[-3]
                     delta2 = hist[-1] - hist[-2]
                     if delta2 > delta1: # Deceleration of drop
                         score += 2.0
            
            if score > best_score and score > 6.0:
                best_score = score
                
                # Dynamic Sizing based on Volatility
                # Higher risk (volatility) = Lower size
                risk_factor = max(1.0, inds['atr'] / (hist[-1] * 0.01))
                allocation = self.max_allocation_pct / risk_factor
                size_usd = self.balance * allocation
                qty = size_usd / hist[-1]
                
                best_signal = {
                    "symbol": symbol,
                    "side": "BUY",
                    "amount": float(round(qty, 5)),
                    "reason": reasons
                }

        return best_signal