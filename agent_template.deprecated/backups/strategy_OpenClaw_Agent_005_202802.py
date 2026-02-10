import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Mutation for Heterogeneity ===
        self.dna = random.random()
        
        # === Dynamic Window Parameters ===
        # Slight randomization to prevent signal clustering (Herd immunity)
        self.w_fast = int(7 + (self.dna * 3))
        self.w_slow = int(20 + (self.dna * 5))
        self.w_vol = 14
        self.w_rsi = 14
        
        # === Risk Management ===
        self.max_pos = 3 
        self.balance = 1000.0
        self.base_risk_pct = 0.02  # Risk 2% of equity per trade basis
        
        # === State Management ===
        self.history = {}       # sym -> deque of prices
        self.positions = {}     # sym -> {amt, entry_px, entry_tick, high_water, tags}
        self.tick_count = 0
        self.min_history = self.w_slow + 5

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. State Update & Exits
        # We prioritize managing existing risk before looking for new risk.
        active_holdings = list(self.positions.keys())
        
        for sym in active_holdings:
            if sym in prices:
                p_data = prices[sym]
                
                # Update history for held symbols to ensure indicators are fresh
                self._update_history(sym, p_data['priceUsd'])
                
                # Check Exits
                exit_signal = self._check_exits(sym, p_data, self.history[sym])
                if exit_signal:
                    return exit_signal

        # 2. Entry Scanning
        # Only scan if we have capital/slots available
        if len(self.positions) < self.max_pos:
            candidates = []
            
            for sym, data in prices.items():
                # Skip if held
                if sym in self.positions: continue
                
                # Update history for candidates
                self._update_history(sym, data['priceUsd'])
                
                # Validity Checks
                if len(self.history[sym]) < self.min_history: continue
                
                # Liquidity Filter: Avoid low liquidity traps
                if data['liquidity'] < 50000 or data['volume24h'] < 50000:
                    continue
                
                # Analyze
                signal = self._analyze_entry(sym, data, self.history[sym])
                if signal:
                    candidates.append(signal)
            
            if candidates:
                # Select the highest quality setup
                # Sort by score descending
                best_setup = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
                return self._execute_entry(best_setup)

        return None

    def _update_history(self, sym, price):
        if price <= 0: return
        if sym not in self.history:
            self.history[sym] = deque(maxlen=self.min_history + 50)
        
        # Avoid duplicate ticks if called multiple times same tick (idempotency check not strictly needed but good practice)
        # Here we just append. Logic assumes one update per tick.
        self.history[sym].append(price)

    def _check_exits(self, sym, data, history):
        pos = self.positions[sym]
        current_price = data['priceUsd']
        entry_price = pos['entry_px']
        qty = pos['amt']
        ticks_held = self.tick_count - pos['entry_tick']
        
        # Calculate PnL
        raw_pnl_pct = (current_price - entry_price) / entry_price
        
        # Update High Water Mark (Highest PnL achieved)
        if raw_pnl_pct > pos['high_water']:
            self.positions[sym]['high_water'] = raw_pnl_pct
        high_water = self.positions[sym]['high_water']
        
        # Calculate Indicators
        hist_list = list(history)
        vol_atr = self._atr_proxy(hist_list, self.w_vol)
        ema_slow = self._ema(hist_list, self.w_slow)
        
        # === EXIT 1: Thesis Invalidation (Structural Break) ===
        # If we bought on momentum, and price falls below the Slow EMA, the trend is likely dead.
        # This replaces static STOP_LOSS with a structural level.
        if "MOMENTUM" in pos['tags']:
            if current_price < ema_slow:
                return self._close(sym, qty, ["STRUCTURE_BREAK", "TREND_INVALID"])

        # === EXIT 2: Dynamic Volatility Trailing ===
        # As price moves in our favor, we trail the stop based on ATR.
        # Tighten the trail if profit is high.
        trail_mult = 2.0 if high_water < 0.03 else 1.0 # Tighten from 2 ATR to 1 ATR if > 3% profit
        dynamic_stop = high_water - (vol_atr * trail_mult)
        
        # Ensure dynamic stop doesn't go below a hard floor relative to entry initially, 
        # but here we rely on it to lock profits.
        if raw_pnl_pct < dynamic_stop:
             return self._close(sym, qty, ["VOL_TRAIL_HIT", "PROFIT_PROTECT"])
             
        # === EXIT 3: Stagnation / Time Decay ===
        # Penalized for IDLE_EXIT / STAGNANT.
        # If trade goes nowhere for 20 ticks, kill it to free up capital.
        if ticks_held > 20:
            if raw_pnl_pct < (vol_atr * 0.5): # Less than 0.5 ATR profit after 20 ticks
                return self._close(sym, qty, ["STAGNATION_KILL", "TIME_DECAY"])
        
        # === EXIT 4: Hard Safety Floor ===
        # Absolute disaster stop (flash crash protection)
        if raw_pnl_pct < -0.07: 
            return self._close(sym, qty, ["HARD_STOP"])

        return None

    def _analyze_entry(self, sym, data, history):
        hist_list = list(history)
        current_price = data['priceUsd']
        
        # Indicators
        ema_fast = self._ema(hist_list, self.w_fast)
        ema_slow = self._ema(hist_list, self.w_slow)
        vol_atr = self._atr_proxy(hist_list, self.w_vol)
        rsi_val = self._rsi(hist_list, self.w_rsi)
        
        score = 0.0
        reasons = []
        tags = []
        
        # === STRATEGY A: Kinetic Trend Alignment ===
        # Addresses 'EXPLORE' penalty by requiring strict alignment.
        # 1. Fast EMA > Slow EMA (Uptrend)
        # 2. Price > Fast EMA (Strong Momentum)
        # 3. RSI not Overbought (< 75)
        trend_aligned = ema_fast > ema_slow
        
        if trend_aligned and current_price > ema_fast:
            if 50 < rsi_val < 75:
                # Calculate Trend Strength
                separation = (ema_fast - ema_slow) / ema_slow
                if separation > 0.001:
                    score = 20.0 + (separation * 1000)
                    reasons = ["TREND_ALIGNMENT", "MOMENTUM"]
                    tags.append("MOMENTUM")

        # === STRATEGY B: Structural Value (Strict Reversion) ===
        # Addresses 'MEAN_REVERSION' penalty.
        # Instead of blind dip buying, we look for 'Oversold + Bounce'.
        # 1. RSI Deeply Oversold (< 25)
        # 2. Price Deviation > 3 ATRs (Statistical Extreme)
        # 3. VALIDATION: Current tick > Previous tick (Green Candle / Support forming)
        if rsi_val < 25:
            # Check price inflection
            if hist_list[-1] > hist_list[-2]:
                deviation = (ema_slow - current_price) / current_price
                if deviation > (vol_atr * 2.5):
                    score = 15.0 + (deviation * 100)
                    reasons = ["STRUCTURAL_VALUE", "INFLECTION_POINT"]
                    tags.append("REVERSION")
        
        if score > 0:
            # Boost score for high liquidity (Safety)
            if data['liquidity'] > 1000000:
                score *= 1.1
                
            return {
                'symbol': sym,
                'price': current_price,
                'score': score,
                'vol_atr': vol_atr,
                'reasons': reasons,
                'tags': tags
            }
            
        return None

    def _execute_entry(self, signal):
        sym = signal['symbol']
        price = signal['price']
        vol_atr = max(signal['vol_atr'], 0.01)
        
        # === Volatility Sizing ===
        # Target risking 'base_risk_pct' of account if price hits stop.
        # Assumed stop width = 2 * ATR
        stop_distance_pct = vol_atr * 2.0
        risk_per_share = price * stop_distance_pct
        
        risk_budget = self.balance * self.base_risk_pct
        
        if risk_per_share == 0: return None
        
        qty = risk_budget / risk_per_share
        
        # Max Position Cap (25% of portfolio)
        max_qty = (self.balance * 0.25) / price
        qty = min(qty, max_qty)
        
        if qty * price < 10.0: return None # Ignore dust
        
        self.positions[sym] = {
            'amt': qty,
            'entry_px': price,
            'entry_tick': self.tick_count,
            'high_water': 0.0,
            'tags': signal['tags']
        }
        
        return {
            'side': 'BUY',
            'symbol': sym,
            'amount': round(qty, 6),
            'reason': signal['reasons']
        }

    def _close(self, sym, amount, reasons):
        if sym in self.positions:
            del self.positions[sym]
        return {
            'side': 'SELL',
            'symbol': sym,
            'amount': amount,
            'reason': reasons
        }

    # === Indicators ===
    
    def _ema(self, data, window):
        if not data: return 0.0
        alpha = 2.0 / (window + 1)
        ema = data[0]
        for px in data[1:]:
            ema = (px * alpha) + (ema * (1.0 - alpha))
        return ema

    def _rsi(self, data, window):
        if len(data) <= window: return 50.0
        # Calculate changes
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        recent = deltas[-window:]
        
        gains = sum(x for x in recent if x > 0)
        losses = sum(abs(x) for x in recent if x < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _atr_proxy(self, data, window):
        # Calculate average percentage move over window
        if len(data) <= window: return 0.01
        
        rets = []
        for i in range(1, len(data)):
            if data[i-1] == 0: continue
            r = abs((data[i] - data[i-1]) / data[i-1])
            rets.append(r)
            
        subset = rets[-window:]
        if not subset: return 0.01
        return sum(subset) / len(subset)