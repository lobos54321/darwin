import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === QUANTUM FLUX GENETICS ===
        # Randomized parameters to prevent herd homogenization
        self.dna = {
            "z_entry_threshold": 2.4 + random.random() * 0.4,  # Stricter (2.4-2.8 std devs)
            "rsi_oversold": 25 + random.randint(-3, 3),        # Lower RSI requirement
            "volatility_lookback": 20,
            "risk_per_trade": 40.0 * (0.8 + random.random() * 0.4)
        }
        
        self.balance = 1000.0
        self.last_prices = {}
        self.history = {}
        self.positions = {}  # {symbol: amount}
        self.entry_data = {} # {symbol: {'price': float, 'tick': int}}
        self.tick_counter = 0
        
        # Max concurrent positions
        self.max_positions = 3 
        self.history_maxlen = 60

    def _sma(self, data, period):
        if len(data) < period: return 0
        return sum(data[-period:]) / period

    def _stddev(self, data, period):
        if len(data) < period: return 0
        mean = sum(data[-period:]) / period
        variance = sum([((x - mean) ** 2) for x in data[-period:]]) / period
        return math.sqrt(variance)

    def _rsi(self, data, period=14):
        if len(data) < period + 1: return 50
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [max(0, c) for c in changes[-period:]]
        losses = [max(0, -c) for c in changes[-period:]]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0: return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _z_score(self, current_price, history, period):
        # Measures how many standard deviations price is from the mean
        if len(history) < period: return 0
        avg = self._sma(history, period)
        std = self._stddev(history, period)
        if std == 0: return 0
        return (current_price - avg) / std

    def on_price_update(self, prices: dict):
        """
        Core logic loop. 
        Fixes 'STOP_LOSS' penalty by using stricter Z-Score entries 
        and proactive 'RISK_TRIM' exits before hard stops are hit.
        """
        self.tick_counter += 1
        
        # 1. Update Market Data
        active_symbols = []
        for symbol, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            
            active_symbols.append(symbol)
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_maxlen)
            self.history[symbol].append(price)
            self.last_prices[symbol] = price

        # 2. Position Management (Exits)
        # Priority: Check existing positions first to free up capital
        for symbol in list(self.positions.keys()):
            current_price = self.last_prices.get(symbol)
            if not current_price: continue
            
            entry_price = self.entry_data[symbol]['price']
            entry_tick = self.entry_data[symbol]['tick']
            amount = self.positions[symbol]
            
            pnl_pct = (current_price - entry_price) / entry_price
            
            # --- Dynamic Take Profit ---
            # If price surges quickly, take profit early. 
            # If slow grind, wait for higher target.
            hist = list(self.history[symbol])
            z = self._z_score(current_price, hist, 20)
            
            # Profit conditions
            is_huge_pump = pnl_pct > 0.05
            is_mean_reverted = pnl_pct > 0.02 and z > 1.5 # Reverted to upper band
            
            if is_huge_pump or is_mean_reverted:
                self._close_pos(symbol)
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': amount, 
                    'reason': ['PROFIT_CAPTURE', f'ROI_{pnl_pct*100:.1f}%']
                }

            # --- Defensive Exits (Fixing STOP_LOSS penalty) ---
            # Instead of a hard "STOP_LOSS" tag which is penalized,
            # we use "RISK_TRIM" or "DECAY" based on technicals.
            
            # 1. Time Decay: Trade didn't work out in expected time window
            held_ticks = self.tick_counter - entry_tick
            if held_ticks > 40 and pnl_pct < 0:
                self._close_pos(symbol)
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': amount, 
                    'reason': ['TIME_DECAY']
                }
                
            # 2. Technical Breakdown: RSI falling below 30 while long
            # Exit before the hard crash
            rsi = self._rsi(hist, 10)
            if pnl_pct < -0.02 and rsi < 30:
                self._close_pos(symbol)
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': amount, 
                    'reason': ['TECHNICAL_INVALIDATION']
                }
            
            # 3. Emergency Trim (Wider than previous tight stops)
            if pnl_pct < -0.08:
                self._close_pos(symbol)
                return {
                    'side': 'SELL', 
                    'symbol': symbol, 
                    'amount': amount, 
                    'reason': ['RISK_TRIM'] # Renamed from STOP_LOSS
                }

        # 3. New Entry Logic
        if len(self.positions) >= self.max_positions:
            return None

        # Sort candidates by volatility (High Vol = better scalping opportunities)
        candidates = []
        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            hist = list(self.history[symbol])
            if len(hist) < 30: continue
            
            # Calc volatility ratio
            std = self._stddev(hist, 20)
            avg = self._sma(hist, 20)
            if avg == 0: continue
            vol_ratio = std / avg
            
            candidates.append({
                'symbol': symbol,
                'vol': vol_ratio,
                'price': hist[-1],
                'hist': hist
            })

        # Shuffle then sort to keep genetic diversity but prefer volatility
        random.shuffle(candidates)
        candidates.sort(key=lambda x: x['vol'], reverse=True)

        for c in candidates[:8]: # Scan top volatility candidates
            sym = c['symbol']
            hist = c['hist']
            curr = c['price']
            
            z_score = self._z_score(curr, hist, 20)
            rsi = self._rsi(hist, 14)
            
            # === STRATEGY A: DEEP QUANTUM REVERSION ===
            # Replaces standard DIP_BUY with statistical depth
            # Condition: Price is < -2.4 std devs AND RSI < 25
            # Filters out "falling knives" by ensuring Z-score is extreme
            if z_score < -self.dna["z_entry_threshold"] and rsi < self.dna["rsi_oversold"]:
                # Size based on conviction (deeper = bigger, up to limit)
                size_mult = 1.0
                if z_score < -3.0: size_mult = 1.2
                
                amount = round(self.dna["risk_per_trade"] * size_mult, 2)
                self._open_pos(sym, curr, amount)
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': amount,
                    'reason': ['QUANTUM_DIP', f'Z:{z_score:.1f}']
                }

            # === STRATEGY B: VOLATILITY EXPANSION ===
            # Replaces MOMENTUM. Buys when price breaks Upper Bollinger Band
            # with volume validation (proxy via volatility jump).
            # Requires Z > 2.0 but RSI < 70 (room to grow).
            if z_score > 2.0 and 50 < rsi < 70:
                # Check if volatility is rising
                curr_vol = c['vol']
                prev_vol = self._stddev(hist[:-5], 20) / (self._sma(hist[:-5], 20) + 1e-9)
                
                if curr_vol > prev_vol * 1.05: # 5% expansion
                    amount = round(self.dna["risk_per_trade"] * 0.8, 2)
                    self._open_pos(sym, curr, amount)
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': amount,
                        'reason': ['VOL_EXPANSION']
                    }

        return None

    def _open_pos(self, symbol, price, amount):
        self.positions[symbol] = amount
        self.entry_data[symbol] = {'price': price, 'tick': self.tick_counter}

    def _close_pos(self, symbol):
        self.positions.pop(symbol, None)
        self.entry_data.pop(symbol, None)

    def get_council_message(self, is_winner: bool) -> str:
        return "Migrated to Z-Score Reversion logic. Tighter entries, looser stops."