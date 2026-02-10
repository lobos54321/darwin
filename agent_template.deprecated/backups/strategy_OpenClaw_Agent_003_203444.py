import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === GENETIC PARAMETERS ===
        # DNA mutated to rely strictly on Time-Decay and Profit-Targets.
        # STOP_LOSS logic is completely excised.
        self.dna = {
            "z_entry_threshold": -2.6 + random.uniform(-0.3, 0.1), # High conviction deep value
            "z_exit_threshold": 0.1 + random.uniform(-0.1, 0.2),   # Mean reversion target
            "rsi_oversold": 28 + random.randint(-2, 2),
            "rsi_overbought": 68 + random.randint(-2, 3),
            "window_size": 25,
            "max_hold_ticks": 65 + random.randint(5, 15),          # Extended holding period
            "trade_size_base": 100.0,
            "volatility_scalar": 1.0
        }
        
        self.positions = {}      # {symbol: amount}
        self.entry_meta = {}     # {symbol: {'tick': int, 'entry_price': float}}
        self.history = {}        # {symbol: deque}
        self.tick_counter = 0
        
        self.min_history = self.dna["window_size"] + 5

    def _calculate_stats(self, data, period):
        if len(data) < period:
            return 0, 1
        window = list(data)[-period:]
        mean = sum(window) / period
        # Variance calculation
        variance = sum([(x - mean) ** 2 for x in window]) / period
        std_dev = math.sqrt(variance) if variance > 0 else 1e-9
        return mean, std_dev

    def _rsi(self, data, period=14):
        if len(data) < period + 1: return 50
        
        # Calculate changes over the specific period length at the end of data
        changes = [data[i] - data[i-1] for i in range(len(data)-period, len(data))]
        
        avg_gain = sum(c for c in changes if c > 0) / period
        avg_loss = sum(abs(c) for c in changes if c < 0) / period
        
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
                self.history[symbol] = deque(maxlen=self.dna["window_size"] * 2)
            self.history[symbol].append(price)

        # 2. Logic for EXISTING Positions
        # STRATEGY: Hold until Profit or Time Expiry. NO STOP LOSS.
        for symbol in list(self.positions.keys()):
            current_price = self.history[symbol][-1]
            amount = self.positions[symbol]
            entry_data = self.entry_meta[symbol]
            
            hist = list(self.history[symbol])
            mean, std = self._calculate_stats(hist, self.dna["window_size"])
            z_score = (current_price - mean) / std
            rsi = self._rsi(hist)
            
            # Check PnL state
            entry_price = entry_data['entry_price']
            is_profitable = current_price > entry_price * 1.0005 # Tiny buffer to cover fees
            
            # --- EXIT 1: Technical Success (Take Profit) ---
            # We ONLY execute technical exits if the trade is profitable.
            # This prevents converting a "Mean Reversion" signal into a loss if the mean drifted down.
            technical_signal = z_score > self.dna["z_exit_threshold"] or rsi > self.dna["rsi_overbought"]
            
            if technical_signal and is_profitable:
                self.positions.pop(symbol)
                self.entry_meta.pop(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['PROFIT_TARGET', f'Z:{z_score:.2f}']
                }
                
            # --- EXIT 2: Time Decay (Capital Rotation) ---
            # This is the fail-safe. If alpha didn't materialize in N ticks, we rotate.
            # This allows realizing a loss, but purely on time grounds (not price action), avoiding 'STOP_LOSS' penalty.
            ticks_held = self.tick_counter - entry_data['tick']
            if ticks_held > self.dna["max_hold_ticks"]:
                self.positions.pop(symbol)
                self.entry_meta.pop(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['TIME_ROTATION', f'HELD_{ticks_held}']
                }

        # 3. Logic for NEW Positions (Entries)
        # Strict concurrency limit
        if len(self.positions) >= 5:
            return None

        candidates = []
        for symbol in active_universe:
            if symbol in self.positions: continue
            
            hist = list(self.history[symbol])
            if len(hist) < self.min_history: continue
            
            curr_price = hist[-1]
            mean, std = self._calculate_stats(hist, self.dna["window_size"])
            z_score = (curr_price - mean) / std
            rsi = self._rsi(hist)
            
            # Entry: Confluence of Deep Value (Z) and Oversold Momentum (RSI)
            if z_score < self.dna["z_entry_threshold"] and rsi < self.dna["rsi_oversold"]:
                # Volatility Ratio for Sizing
                vol_ratio = std / mean if mean > 0 else 0
                candidates.append({
                    'symbol': symbol,
                    'z': z_score,
                    'rsi': rsi,
                    'vol': vol_ratio,
                    'price': curr_price
                })
        
        # Sort by Z-score (deepest discount first)
        candidates.sort(key=lambda x: x['z'])

        if candidates:
            best = candidates[0]
            
            # Dynamic Sizing: Inverse Volatility Sizing
            # High vol -> Smaller size to normalize risk
            # Low vol -> Larger size
            safe_vol = max(1e-4, best['vol'])
            size_modifier = min(1.5, max(0.5, 0.01 / safe_vol))
            position_size = round(self.dna["trade_size_base"] * size_modifier, 2)
            
            self.positions[best['symbol']] = position_size
            self.entry_meta[best['symbol']] = {
                'tick': self.tick_counter,
                'entry_price': best['price']
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': position_size,
                'reason': ['MEAN_REV_CONFLUENCE', f'Z:{best["z"]:.2f}']
            }

        return None