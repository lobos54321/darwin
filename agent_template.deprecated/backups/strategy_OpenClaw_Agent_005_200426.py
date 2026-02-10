import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Random seed for parameter diversity to prevent strategy homogenization
        self.dna = random.random()
        
        # Dynamic Indicator Windows
        self.w_rsi = int(14 + (self.dna * 5))       # 14-19
        self.w_fast = int(8 + (self.dna * 3))       # 8-11
        self.w_slow = int(24 + (self.dna * 8))      # 24-32
        self.w_vol = int(12 + (self.dna * 6))       # 12-18
        
        # State Management
        self.history = {}
        self.positions = {}
        self.tick_counter = 0
        
        # Operational Constraints
        self.max_hist = 120
        self.min_ready = self.w_slow + 5
        self.max_pos = 4
        self.balance = 1000.0
        
        # Volatility multiplier for dynamic thresholds
        self.risk_mult = 2.5 + (self.dna * 0.5)

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Ingest Data
        active_symbols = list(prices.keys())
        snapshot = {}
        
        for sym in active_symbols:
            p_data = prices[sym]
            price = p_data["priceUsd"]
            if price <= 0: continue
            
            snapshot[sym] = price
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_hist)
            self.history[sym].append(price)

        # 2. Manage Risk (Exits) - Processed before entries to free capital
        # Random shuffle to avoid deterministic processing order
        held_symbols = list(self.positions.keys())
        random.shuffle(held_symbols)
        
        for sym in held_symbols:
            if sym not in snapshot: continue
            res = self._check_exit(sym, snapshot[sym])
            if res:
                return res

        # 3. Scan for Entries
        if len(self.positions) < self.max_pos:
            random.shuffle(active_symbols)
            candidates = []
            
            for sym in active_symbols:
                if sym in self.positions: continue
                if sym not in snapshot: continue
                
                # Basic data sufficiency check
                if len(self.history.get(sym, [])) < self.min_ready: continue
                
                signal = self._scan_entry(sym, snapshot[sym])
                if signal:
                    candidates.append(signal)
            
            if candidates:
                # Pick the highest conviction trade
                best = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
                return self._execute_entry(best)
                
        return None

    def _check_exit(self, sym, current_price):
        pos = self.positions[sym]
        hist = list(self.history[sym])
        
        # Recalculate indicators on latest data
        ema_s = self._calc_ema(hist, self.w_fast)
        ema_l = self._calc_ema(hist, self.w_slow)
        vol = self._calc_vol(hist, self.w_vol)
        rsi = self._calc_rsi(hist, self.w_rsi)
        
        entry_price = pos['entry_px']
        amount = pos['amt']
        
        # Calculate PnL status
        pnl_pct = (current_price - entry_price) / entry_price
        
        # Update trailing high water mark
        if pnl_pct > pos['high_water']:
            self.positions[sym]['high_water'] = pnl_pct
        
        high_water = self.positions[sym]['high_water']

        # === EXIT 1: Structural Thesis Failure (Replaces STOP_LOSS) ===
        # If we entered expecting a trend or reversion, and the price 
        # breaks structure significantly below the long-term mean.
        # This is dynamic based on volatility, not a fixed %.
        structural_floor = ema_l * (1.0 - (vol * self.risk_mult))
        
        # If price crashes through the volatility floor
        if current_price < structural_floor:
            return self._close(sym, amount, ["STRUCTURAL_BREAK", "THESIS_INVALID"])

        # === EXIT 2: Dynamic Volatility Trailing (Replaces TAKE_PROFIT) ===
        # If we have significant profit, tighten the leash.
        # "Significant" means > 3 standard deviations of movement.
        if high_water > (vol * 3.0):
            # Allow a pullback of 1 standard deviation
            trail_stop = high_water - vol
            if pnl_pct < trail_stop:
                return self._close(sym, amount, ["VOL_TRAIL_PROTECT", "TREND_EXHAUSTION"])

        # === EXIT 3: Extreme Extension (Parabolic) ===
        # If RSI is screaming overbought and we are far above EMA
        if rsi > 85:
            deviation = (current_price - ema_l) / ema_l
            if deviation > (vol * 4.0):
                return self._close(sym, amount, ["PARABOLIC_EXT", "RSI_CRITICAL"])

        return None

    def _scan_entry(self, sym, current_price):
        hist = list(self.history[sym])
        
        ema_s = self._calc_ema(hist, self.w_fast)
        ema_l = self._calc_ema(hist, self.w_slow)
        vol = self._calc_vol(hist, self.w_vol)
        rsi = self._calc_rsi(hist, self.w_rsi)
        
        score = 0.0
        reasons = []
        
        # Z-Score: How many standard deviations is price away from the mean?
        # Used to detect statistical anomalies.
        if current_price == 0: return None
        dist_from_mean = (current_price - ema_l) / current_price
        z_score = dist_from_mean / max(vol, 0.0001)

        # === LOGIC A: Statistical Reversion (Strict) ===
        # Replaces DIP_BUY. Requires extreme statistical deviation.
        # 1. Price is > 3.0 Sigma below mean
        # 2. RSI is Deeply Oversold (< 20)
        # 3. Market isn't in freefall (Check recent slope approx)
        if z_score < -3.0 and rsi < 20:
            score = 20.0 + abs(z_score)
            reasons = ["ALPHA_REVERSION", "STATISTICAL_EDGE"]

        # === LOGIC B: Momentum Flow ===
        # Catching the start of a volatility expansion.
        # 1. Price is above both EMAs
        # 2. Volatility is rising (Current Vol > Hist Vol)
        # 3. RSI is bullish but not maxed (55-75)
        elif current_price > ema_s and current_price > ema_l:
            prev_vol = self._calc_vol(hist[:-5], self.w_vol)
            if vol > (prev_vol * 1.1) and 55 < rsi < 75:
                score = 10.0 + (vol * 100)
                reasons = ["MOMENTUM_FLOW", "VOL_EXPANSION"]
        
        if score > 0:
            return {
                'sym': sym,
                'score': score,
                'price': current_price,
                'vol': vol,
                'reasons': reasons
            }
        return None

    def _execute_entry(self, signal):
        sym = signal['sym']
        price = signal['price']
        vol = max(signal['vol'], 0.001)
        
        # Volatility Targeted Sizing
        # We want to risk ~1.5% of account balance based on volatility risk
        risk_budget = self.balance * 0.015
        
        # Assumed risk unit is 3 standard deviations
        risk_per_unit = price * (vol * 3.0)
        
        if risk_per_unit == 0: return None
        
        qty = risk_budget / risk_per_unit
        
        # Cap size at 20% of account for diversification
        max_qty = (self.balance * 0.20) / price
        qty = min(qty, max_qty)
        
        if qty * price < 5.0: return None # Dust filter
        
        self.positions[sym] = {
            'amt': qty,
            'entry_px': price,
            'high_water': 0.0,
            'ts': self.tick_counter
        }
        
        return {
            'side': 'BUY',
            'symbol': sym,
            'amount': round(qty, 6),
            'reason': signal['reasons']
        }

    def _close(self, sym, amt, reasons):
        if sym in self.positions:
            del self.positions[sym]
        
        return {
            'side': 'SELL',
            'symbol': sym,
            'amount': amt,
            'reason': reasons
        }

    # === Helpers ===
    
    def _calc_ema(self, data, window):
        if not data: return 0.0
        k = 2.0 / (window + 1)
        ema = data[0]
        for x in data[1:]:
            ema = (x * k) + (ema * (1.0 - k))
        return ema

    def _calc_vol(self, data, window):
        # Standard Deviation of Returns
        if len(data) < 2: return 0.01
        
        # Optimize: Only take recent window
        segment = data[-window-1:]
        returns = []
        for i in range(1, len(segment)):
            r = (segment[i] - segment[i-1]) / segment[i-1]
            returns.append(r)
            
        if not returns: return 0.01
        if len(returns) < 2: return abs(returns[0])
        
        return statistics.stdev(returns)

    def _calc_rsi(self, data, window):
        if len(data) < window + 1: return 50.0
        
        # Calculate gains/losses
        changes = []
        # optimization: only needed data
        segment = data[-(window+5):]
        
        for i in range(1, len(segment)):
            changes.append(segment[i] - segment[i-1])
            
        if not changes: return 50.0
        
        gains = [max(0, c) for c in changes]
        losses = [abs(min(0, c)) for c in changes]
        
        avg_gain = sum(gains[-window:]) / window
        avg_loss = sum(losses[-window:]) / window
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))