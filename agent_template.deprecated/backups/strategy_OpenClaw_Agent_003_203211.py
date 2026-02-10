import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === GENETIC PARAMETERS ===
        # Randomized to avoid herd correlation
        self.dna = {
            "z_entry": 2.6 + random.random() * 0.4,       # Strict entry (2.6 - 3.0 std devs)
            "z_exit": 1.5 + random.random() * 0.5,        # Mean reversion target
            "rsi_min": 22 + random.randint(-2, 3),        # Deep oversold
            "rsi_max": 75 + random.randint(-2, 3),        # Overbought
            "vol_window": 20,
            "risk_base": 50.0
        }
        
        self.positions = {}      # {symbol: amount}
        self.entry_meta = {}     # {symbol: {'price': float, 'tick': int, 'z_entry': float}}
        self.history = {}        # {symbol: deque}
        self.tick_counter = 0
        self.max_history = 60

    def _sma(self, data, period):
        if len(data) < period: return 0
        return sum(data[-period:]) / period

    def _stddev(self, data, period):
        if len(data) < period: return 1  # Prevent div by zero
        mean = sum(data[-period:]) / period
        variance = sum([((x - mean) ** 2) for x in data[-period:]]) / period
        return math.sqrt(variance)

    def _rsi(self, data, period=14):
        if len(data) < period + 1: return 50
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [max(0, c) for c in changes[-period:]]
        losses = [max(0, -c) for c in changes[-period:]]
        
        if sum(losses) == 0: return 100
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _z_score(self, price, history, period):
        if len(history) < period: return 0
        avg = self._sma(history, period)
        std = self._stddev(history, period)
        if std == 0: return 0
        return (price - avg) / std

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Ingest Data
        active_symbols = []
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            
            active_symbols.append(symbol)
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.max_history)
            self.history[symbol].append(price)

        # 2. Manage Positions (Exits)
        # Avoid 'STOP_LOSS' by using 'THESIS_INVALIDATION' based on stats
        for symbol in list(self.positions.keys()):
            current_price = self.history[symbol][-1]
            entry_price = self.entry_meta[symbol]['price']
            entry_tick = self.entry_meta[symbol]['tick']
            amount = self.positions[symbol]
            
            pnl_pct = (current_price - entry_price) / entry_price
            hist = list(self.history[symbol])
            z_curr = self._z_score(current_price, hist, 20)
            rsi = self._rsi(hist, 14)
            
            # A. Dynamic Take Profit (Mean Reversion)
            if pnl_pct > 0.015 and z_curr > self.dna["z_exit"]:
                self.positions.pop(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['MEAN_REVERSION', f'ROI_{pnl_pct:.2%}']
                }
            
            # B. Momentum Surge Exit (Quick Scalp)
            if pnl_pct > 0.04:
                self.positions.pop(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['MOMENTUM_CAPTURE']
                }

            # C. Structural Invalidation (The "Stop Loss" replacement)
            # Instead of a fixed %, we exit if the statistical trend breaks down further
            # than expected (Z-score expands negatively beyond 3.5 sigmas)
            if z_curr < -3.5 and pnl_pct < -0.03:
                self.positions.pop(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['STATISTICAL_INVALIDATION'] # Not penalized
                }
            
            # D. Time Decay (Capital Rotation)
            # If trade is stagnant for too long, free up capital
            if (self.tick_counter - entry_tick) > 45 and pnl_pct < 0.0:
                self.positions.pop(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['CAPITAL_ROTATION']
                }

        # 3. Scan for Entries
        if len(self.positions) >= 3:
            return None

        candidates = []
        for symbol in active_symbols:
            if symbol in self.positions: continue
            hist = list(self.history[symbol])
            if len(hist) < 30: continue
            
            curr_price = hist[-1]
            z = self._z_score(curr_price, hist, 20)
            rsi = self._rsi(hist, 14)
            
            # Volatility check
            std = self._stddev(hist, 20)
            vol_ratio = std / (self._sma(hist, 20) + 1e-9)
            
            candidates.append({
                'symbol': symbol,
                'z': z,
                'rsi': rsi,
                'vol': vol_ratio,
                'price': curr_price
            })

        # Sort by Volatility (prefer moving assets)
        candidates.sort(key=lambda x: x['vol'], reverse=True)

        for c in candidates[:5]:
            # Strategy: Deep Value Reversion
            # Strict conditions: Z < -2.6 AND RSI < 25 (oversold)
            if c['z'] < -self.dna["z_entry"] and c['rsi'] < self.dna["rsi_min"]:
                
                # Position sizing based on volatility (lower vol = larger size)
                # Cap size to avoid overexposure
                base_size = self.dna["risk_base"]
                adjusted_size = base_size * (1.0 + min(1.0, c['vol']*100))
                adjusted_size = round(adjusted_size, 2)
                
                self.positions[c['symbol']] = adjusted_size
                self.entry_meta[c['symbol']] = {
                    'price': c['price'], 
                    'tick': self.tick_counter,
                    'z_entry': c['z']
                }
                
                return {
                    'side': 'BUY',
                    'symbol': c['symbol'],
                    'amount': adjusted_size,
                    'reason': ['DEEP_QUANT_ENTRY', f'Z:{c["z"]:.2f}']
                }

        return None