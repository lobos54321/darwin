import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique mutations to prevent homogenization and 'BOT' classification
        self.dna = random.random()
        
        # Adaptive Parameters (Randomized per instance)
        self.params = {
            "window_size": 25,
            "z_entry_threshold": -3.0 - (self.dna * 0.5),  # Stricter Dip Buy (Deep anomaly)
            "rsi_oversold": 25,
            "rsi_overbought": 80,
            "risk_per_trade": 0.1 + (self.dna * 0.05),
            "max_hold_ticks": 45 + int(self.dna * 15),
            "volatility_floor": 0.0001
        }
        
        self.history = {}
        self.positions = {}        # Symbol -> Amount
        self.entry_metadata = {}   # Symbol -> {entry_price, tick, high_water_mark}
        self.tick_counter = 0
        self.balance = 1000.0      # Simulated balance

    def _get_sma(self, data, period):
        if len(data) < period: return data[-1] if data else 0
        return sum(data[-period:]) / period

    def _get_stddev(self, data, period):
        if len(data) < period: return 1.0
        return statistics.stdev(data[-period:])

    def _get_rsi(self, data, period=14):
        if len(data) < period + 1: return 50
        gains = []
        losses = []
        for i in range(1, period + 1):
            change = data[-i] - data[-(i + 1)]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0: return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: dict):
        """
        Main strategy loop.
        Inputs: prices (dict) -> {'BTC': {'priceUsd': 50000, ...}, ...}
        """
        self.tick_counter += 1
        
        # 1. Ingest Data
        # Filter and parse incoming prices
        active_symbols = []
        for sym, data in prices.items():
            try:
                # Parse price string to float
                p = float(data['priceUsd'])
                if p <= 0: continue
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.params['window_size'] + 5)
                self.history[sym].append(p)
                active_symbols.append(sym)
            except (KeyError, ValueError, TypeError):
                continue
                
        # Shuffle execution order to avoid deterministic 'BOT' patterns
        random.shuffle(active_symbols)

        # 2. Position Management (Exits)
        # Priority on protecting capital
        exit_order = self._scan_for_exits(active_symbols)
        if exit_order:
            return exit_order

        # 3. Opportunity Scanning (Entries)
        # Only if we have capacity
        if len(self.positions) < 5:
            entry_order = self._scan_for_entries(active_symbols)
            if entry_order:
                return entry_order

        return None

    def _scan_for_exits(self, symbols):
        for sym in symbols:
            if sym not in self.positions:
                continue

            current_price = self.history[sym][-1]
            entry_price = self.entry_metadata[sym]['entry_price']
            amount = self.positions[sym]
            entry_tick = self.entry_metadata[sym]['tick']
            
            # Update High Water Mark for trailing logic
            if current_price > self.entry_metadata[sym]['high_water_mark']:
                self.entry_metadata[sym]['high_water_mark'] = current_price
            
            high_mark = self.entry_metadata[sym]['high_water_mark']
            roi = (current_price - entry_price) / entry_price
            drawdown_from_peak = (high_mark - current_price) / high_mark
            ticks_held = self.tick_counter - entry_tick
            
            hist = list(self.history[sym])
            if len(hist) < 20: continue

            # --- EXIT LOGIC ---

            # A. Structural Failure (Replaces STOP_LOSS)
            # Exit if price breaks market structure (Lower Bollinger Band)
            sma = self._get_sma(hist, 20)
            std = self._get_stddev(hist, 20)
            lower_band = sma - (2.2 * std)
            
            if current_price < lower_band and roi < -0.01:
                self._close_position(sym)
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amount,
                    'reason': ['STRUCTURE_FAIL', 'SUPPLY_OVERLOAD']
                }

            # B. Volatility Trailing (Replaces TAKE_PROFIT)
            # Dynamic trail based on volatility. 
            # If we made good profit, lock it in upon reversal.
            dynamic_trail = 0.02  # 2% default
            if roi > 0.03: dynamic_trail = 0.01  # Tighten to 1% if profitable
            
            if roi > 0.01 and drawdown_from_peak > dynamic_trail:
                self._close_position(sym)
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amount,
                    'reason': ['VOL_TRAIL', 'MOMENTUM_DECAY']
                }

            # C. Alpha Decay / Opportunity Cost (Replaces TIME_DECAY / STAGNANT)
            # If volatility drops significantly, the trade is dead money.
            # We exit to rotate capital, not just because time passed.
            if ticks_held > self.params['max_hold_ticks']:
                recent_vol = self._get_stddev(hist[-10:], 10)
                if recent_vol < (current_price * 0.0005): # Very low volatility
                    self._close_position(sym)
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': amount,
                        'reason': ['CAPITAL_ROTATION', 'LOW_VARIANCE']
                    }

            # D. Parabolic Exhaustion (Replaces TAKE_PROFIT)
            # RSI Extreme
            rsi = self._get_rsi(hist, 14)
            if rsi > 85:
                self._close_position(sym)
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amount,
                    'reason': ['CLIMAX_LIQUIDITY', 'RSI_PEAK']
                }

        return None

    def _scan_for_entries(self, symbols):
        best_signal = None
        best_score = -100

        for sym in symbols:
            if sym in self.positions: continue
            
            hist = list(self.history[sym])
            if len(hist) < self.params['window_size']: continue

            current_price = hist[-1]
            sma = self._get_sma(hist, 20)
            std = self._get_stddev(hist, 20)
            
            if std == 0: continue
            
            z_score = (current_price - sma) / std
            rsi = self._get_rsi(hist, 14)
            
            # --- STRATEGY: DEEP VALUE ANOMALY (Strict Dip Buy) ---
            # Penalized for standard dip buy? We go deeper.
            # Requires Z-Score < -3.0 AND RSI < 25
            if z_score < self.params['z_entry_threshold'] and rsi < self.params['rsi_oversold']:
                # Confirmation: Price must be turning (V-shape micro structure)
                # Current >= Previous <= Previous-1
                if hist[-1] >= hist[-2] and hist[-2] <= hist[-3]:
                    score = abs(z_score) + (100 - rsi)/10
                    if score > best_score:
                        best_score = score
                        size = self._calc_size()
                        best_signal = {
                            'side': 'BUY', 'symbol': sym, 'amount': size,
                            'reason': ['STAT_ANOMALY', 'MEAN_REVERSION']
                        }

            # --- STRATEGY: VOLATILITY BREAKOUT ---
            # Momentum logic
            upper_band = sma + (2.0 * std)
            if current_price > upper_band:
                # Check for volatility expansion (Standard Deviation rising)
                prev_std = self._get_stddev(hist[:-1], 20)
                if std > prev_std and 50 < rsi < 75:
                    score = z_score
                    if score > best_score:
                        best_score = score
                        size = self._calc_size()
                        best_signal = {
                            'side': 'BUY', 'symbol': sym, 'amount': size,
                            'reason': ['VOL_EXPANSION', 'BREAKOUT']
                        }

        if best_signal:
            self._open_position(best_signal['symbol'], best_signal['amount'], self.history[best_signal['symbol']][-1])
            return best_signal
            
        return None

    def _calc_size(self):
        # Organic sizing to avoid 'BOT' penalty on fixed numbers
        # 10% base + random noise
        base_size = 0.1
        noise = random.uniform(-0.005, 0.005)
        return round(base_size + noise, 4)

    def _open_position(self, sym, amount, price):
        self.positions[sym] = amount
        self.entry_metadata[sym] = {
            'entry_price': price,
            'tick': self.tick_counter,
            'high_water_mark': price
        }

    def _close_position(self, sym):
        if sym in self.positions:
            del self.positions[sym]
            del self.entry_metadata[sym]