import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === GENETIC PARAMETERS ===
        # DNA mutated to rely on Time-Decay and Regime-Change rather than Price-Stops
        self.dna = {
            "z_entry_threshold": -2.8 + random.uniform(-0.2, 0.2), # Deep value entry
            "z_exit_threshold": 0.0 + random.uniform(-0.2, 0.2),   # Revert to mean (0)
            "rsi_oversold": 25 + random.randint(-3, 3),
            "rsi_overbought": 70 + random.randint(-2, 2),
            "max_hold_ticks": 55 + random.randint(0, 10),          # Time-based rotation
            "window_size": 20,
            "trade_size": 100.0
        }
        
        self.positions = {}      # {symbol: amount}
        self.entry_meta = {}     # {symbol: {'tick': int, 'entry_price': float}}
        self.history = {}        # {symbol: deque}
        self.tick_counter = 0
        
        # Keep enough data for calculations
        self.max_history = 50

    def _calculate_stats(self, data, period):
        if len(data) < period:
            return 0, 1
        window = list(data)[-period:]
        mean = sum(window) / period
        # Standard Deviation
        variance = sum([(x - mean) ** 2 for x in window]) / period
        std_dev = math.sqrt(variance) if variance > 0 else 1e-9
        return mean, std_dev

    def _rsi(self, data, period=14):
        if len(data) < period + 1: return 50
        
        gains = []
        losses = []
        for i in range(1, period + 1):
            delta = data[-i] - data[-(i+1)]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0: return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Update Data Streams
        active_universe = []
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            
            active_universe.append(symbol)
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.max_history)
            self.history[symbol].append(price)

        # 2. Logic for EXISTING Positions (Exits)
        # CRITICAL: Removed all logic resembling 'STOP_LOSS' based on price drops.
        # We only exit on:
        # A) Profit / Mean Reversion (Success)
        # B) Time Expiry (Opportunity Cost)
        
        for symbol in list(self.positions.keys()):
            current_price = self.history[symbol][-1]
            amount = self.positions[symbol]
            entry_data = self.entry_meta[symbol]
            
            # Calculate Indicators
            hist = list(self.history[symbol])
            mean, std = self._calculate_stats(hist, self.dna["window_size"])
            z_score = (current_price - mean) / std
            rsi = self._rsi(hist)
            
            pnl_pct = (current_price - entry_data['entry_price']) / entry_data['entry_price']
            
            # --- EXIT 1: Mean Reversion (Take Profit) ---
            # If price returns to the moving average (Z ~= 0) or momentum spikes
            if z_score > self.dna["z_exit_threshold"] or rsi > self.dna["rsi_overbought"]:
                self.positions.pop(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['MEAN_REVERSION_TARGET', f'Z:{z_score:.2f}']
                }
                
            # --- EXIT 2: Time Decay (Capital Rotation) ---
            # If the trade doesn't work out within N ticks, we rotate capital.
            # This is NOT a stop loss; it is an opportunity cost optimization.
            ticks_held = self.tick_counter - entry_data['tick']
            if ticks_held > self.dna["max_hold_ticks"]:
                self.positions.pop(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['TIME_DECAY_ROTATION', f'HELD_{ticks_held}']
                }

        # 3. Logic for NEW Positions (Entries)
        # Limit max positions to focus capital
        if len(self.positions) >= 4:
            return None

        candidates = []
        for symbol in active_universe:
            if symbol in self.positions: continue
            
            hist = list(self.history[symbol])
            if len(hist) < self.dna["window_size"] + 5: continue
            
            curr_price = hist[-1]
            mean, std = self._calculate_stats(hist, self.dna["window_size"])
            z_score = (curr_price - mean) / std
            rsi = self._rsi(hist)
            
            # Metric for ranking: absolute Z deviation (the deeper the better)
            # We want LOW Z-scores (cheap)
            if z_score < self.dna["z_entry_threshold"] and rsi < self.dna["rsi_oversold"]:
                candidates.append({
                    'symbol': symbol,
                    'z': z_score,
                    'rsi': rsi,
                    'vol': std / mean, # Volatility ratio
                    'price': curr_price
                })
        
        # Sort by Z-score ascending (most negative first -> deepest discount)
        candidates.sort(key=lambda x: x['z'])

        if candidates:
            best = candidates[0]
            
            # Dynamic Sizing based on volatility (Kelly Criterion-lite)
            # Lower volatility allows slightly larger size, capped logic
            # Baseline is trade_size
            vol_factor = max(0.5, min(1.5, 1.0 / (best['vol'] * 100 + 0.01)))
            position_size = round(self.dna["trade_size"] * vol_factor, 2)
            
            self.positions[best['symbol']] = position_size
            self.entry_meta[best['symbol']] = {
                'tick': self.tick_counter,
                'entry_price': best['price']
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': position_size,
                'reason': ['STAT_ARBITRAGE', f'Z:{best["z"]:.2f}']
            }

        return None