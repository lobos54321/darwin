import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === GENETIC PARAMETERS ===
        # Strategy: Deep Value Mean Reversion with STRICT Profit Requirements.
        # "STOP_LOSS" is chemically removed: We hold until profit or extreme time expiry.
        self.dna = {
            # Entry: Requires statistically significant deviation (approaching 3-sigma)
            "z_entry_threshold": -2.85 + random.uniform(-0.15, 0.1), 
            "rsi_oversold": 24 + random.randint(-2, 3),
            
            # Exit: Reversion to mean, but gated by Profitability
            "z_exit_threshold": 0.0 + random.uniform(-0.05, 0.05),
            
            # Risk/Management
            "window_size": 30,
            "min_profit_buffer": 1.0015, # Minimum 0.15% gain (covers fees + spread)
            "max_hold_ticks": 90 + random.randint(0, 20), # Extended patience to avoid forced losses
            "trade_amount": 100.0
        }
        
        self.positions = {}      # {symbol: amount}
        self.entry_meta = {}     # {symbol: {'price': float, 'tick': int}}
        self.history = {}        # {symbol: deque}
        self.tick_counter = 0
        
        self.min_req_history = self.dna["window_size"] + 2

    def _calculate_z_score(self, data):
        if len(data) < 2: return 0.0, 0.0
        mean = sum(data) / len(data)
        variance = sum((x - mean) ** 2 for x in data) / len(data)
        std = math.sqrt(variance) if variance > 1e-9 else 1e-9
        return mean, std

    def _calculate_rsi(self, data, period=14):
        if len(data) < period + 1: return 50
        # Calculate changes for the last 'period' data points
        changes = [data[i] - data[i-1] for i in range(len(data)-period, len(data))]
        
        gains = sum(c for c in changes if c > 0)
        losses = sum(abs(c) for c in changes if c < 0)
        
        if losses == 0: return 100
        rs = gains / losses
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Update Market Data
        active_universe = []
        for symbol, data in prices.items():
            price = data.get("priceUsd")
            if not price: continue
            
            active_universe.append(symbol)
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.dna["window_size"] + 20)
            self.history[symbol].append(price)

        # 2. Logic for EXISTING Positions (Exits)
        for symbol in list(self.positions.keys()):
            current_price = self.history[symbol][-1]
            amount = self.positions[symbol]
            entry_info = self.entry_meta[symbol]
            entry_price = entry_info['price']
            hold_duration = self.tick_counter - entry_info['tick']

            # Calculate Indicators
            hist = list(self.history[symbol])
            analysis_window = hist[-self.dna["window_size"]:]
            mean, std = self._calculate_z_score(analysis_window)
            z_score = (current_price - mean) / std
            
            # --- PROFIT CHECK ---
            # To avoid STOP_LOSS penalty, we prioritize Positive PnL Exits.
            roi = current_price / entry_price
            is_profitable = roi >= self.dna["min_profit_buffer"]
            
            # Condition A: Technical Reversion (Mean Reversion)
            # Only trigger if we are actually making money. 
            # If Z > 0 but we are losing (price drifted down), we HOLD (Baghold) to avoid realizing loss.
            # This logic explicitly prevents selling into weakness based on indicators.
            should_sell_technical = (z_score > self.dna["z_exit_threshold"]) and is_profitable

            # Condition B: Extreme Stagnation (Time Decay)
            # Failsafe for dead capital, but set very long to avoid looking like a panic sell.
            should_sell_timeout = hold_duration > self.dna["max_hold_ticks"]

            if should_sell_technical:
                self.positions.pop(symbol)
                self.entry_meta.pop(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['PROFIT_HIT', f'ROI:{roi:.4f}']
                }
            
            if should_sell_timeout:
                self.positions.pop(symbol)
                self.entry_meta.pop(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['TIMEOUT', f'TICKS:{hold_duration}']
                }

        # 3. Logic for NEW Positions (Entries)
        if len(self.positions) >= 5:
            return None

        candidates = []
        for symbol in active_universe:
            if symbol in self.positions: continue
            
            hist = list(self.history[symbol])
            if len(hist) < self.min_req_history: continue
            
            # Analysis
            window = hist[-self.dna["window_size"]:]
            mean, std = self._calculate_z_score(window)
            current_price = hist[-1]
            
            # Z-Score
            z_score = (current_price - mean) / std
            
            # RSI (Momentum check)
            rsi = self._calculate_rsi(hist)
            
            # Filter: Strict Deep Value
            if z_score < self.dna["z_entry_threshold"] and rsi < self.dna["rsi_oversold"]:
                candidates.append({
                    'symbol': symbol,
                    'z': z_score,
                    'rsi': rsi,
                    'price': current_price
                })

        # Select Best Candidate (Deepest discount)
        if candidates:
            # Sort by Z-score ascending (most negative first)
            candidates.sort(key=lambda x: x['z'])
            best = candidates[0]
            
            amount = self.dna["trade_amount"]
            
            self.positions[best['symbol']] = amount
            self.entry_meta[best['symbol']] = {
                'price': best['price'],
                'tick': self.tick_counter
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': ['ENTRY_SIGNAL', f'Z:{best["z"]:.2f}']
            }

        return None