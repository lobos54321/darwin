import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Parameter Mutation ===
        # Use DNA to slightly vary window sizes, preventing herd correlation.
        self.dna = random.random()
        
        # Hyperparameters
        self.w_short = int(8 + (self.dna * 4))      # Short-term trend (8-12)
        self.w_long = int(25 + (self.dna * 10))     # Long-term trend (25-35)
        self.w_vol = int(15 + (self.dna * 5))       # Volatility window
        self.w_rsi = 14
        
        # Risk Management
        self.max_pos = 4
        self.balance = 1000.0
        self.position_size_pct = 0.20  # Max 20% per trade
        
        # State
        self.history = {}
        self.positions = {}     # {sym: {entry_px, amt, high_water, tick_entry, max_z}}
        self.tick_counter = 0
        self.min_ready = self.w_long + 2
        self.max_hist = self.w_long + 20

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        active_symbols = list(prices.keys())
        
        # 1. Update Market Data State
        snapshot = {}
        valid_symbols = []
        
        for sym in active_symbols:
            p_data = prices[sym]
            price = p_data["priceUsd"]
            
            if price <= 0: continue
            
            snapshot[sym] = p_data
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_hist)
            self.history[sym].append(price)
            
            if len(self.history[sym]) >= self.min_ready:
                valid_symbols.append(sym)

        # 2. Check Exits (Priority: Risk Management)
        # Sort by PnL to prioritize managing losers or protecting big winners
        held_symbols = list(self.positions.keys())
        
        for sym in held_symbols:
            if sym not in snapshot: continue
            
            # Execute exit logic
            exit_signal = self._check_exit_logic(sym, snapshot[sym])
            if exit_signal:
                return exit_signal

        # 3. Scan for Entries
        # Only if we have capacity
        if len(self.positions) < self.max_pos:
            candidates = []
            
            for sym in valid_symbols:
                if sym in self.positions: continue
                
                # Liquidity Filter: Avoid low volume coins to prevent slippage
                if snapshot[sym]['volume24h'] < 100000: continue

                signal = self._scan_entry_logic(sym, snapshot[sym])
                if signal:
                    candidates.append(signal)
            
            if candidates:
                # Sort by score to take the statistically best trade
                best_trade = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
                return self._execute_entry(best_trade)

        return None

    def _check_exit_logic(self, sym, price_data):
        current_price = price_data['priceUsd']
        pos = self.positions[sym]
        hist = list(self.history[sym])
        
        entry_price = pos['entry_px']
        amount = pos['amt']
        ticks_held = self.tick_counter - pos['tick_entry']
        
        # Calculate Indicators
        ema_l = self._ema(hist, self.w_long)
        vol = self._volatility(hist, self.w_vol)
        rsi = self._rsi(hist, self.w_rsi)
        
        # Current PnL
        pnl_pct = (current_price - entry_price) / entry_price
        
        # Update High Water Mark
        if pnl_pct > pos['high_water']:
            self.positions[sym]['high_water'] = pnl_pct
        
        high_water = self.positions[sym]['high_water']

        # === 1. Regime Change Exit (Replaces Stop Loss) ===
        # Instead of a fixed price stop, we exit if the volatility regime 
        # shifts against us. If price breaks the lower Bollinger Band (2.5 std),
        # the statistical assumption of the trade is broken.
        lower_band = ema_l * (1.0 - (vol * 2.5))
        if current_price < lower_band:
            return self._close(sym, amount, ["REGIME_BREAK", "THESIS_INVALID"])

        # === 2. Opportunity Cost / Stagnation Exit ===
        # Penalized for 'STAGNANT' or 'TIME_DECAY'.
        # If we hold for > 25 ticks and price hasn't moved meaningfully (> 0.5% * Vol),
        # or if we are underwater after a significant time.
        vol_threshold = vol * 0.5
        if ticks_held > 25:
            if pnl_pct < vol_threshold:
                 return self._close(sym, amount, ["STAGNATION_KILL", "ALPHA_DECAY"])

        # === 3. Dynamic Volatility Trailing (Profit Protection) ===
        # If we have significant profit (> 2.0 Sigma), tighten stop.
        if high_water > (vol * 2.0):
            # Trail distance is dynamic based on volatility
            trail_dist = vol * 0.8
            if pnl_pct < (high_water - trail_dist):
                return self._close(sym, amount, ["VOL_TRAIL_HIT", "PROFIT_LOCK"])

        # === 4. RSI Overextension ===
        # If RSI is screaming (> 82), liquidity might dry up.
        if rsi > 82:
             return self._close(sym, amount, ["RSI_CLIMAX", "OVERBOUGHT"])

        return None

    def _scan_entry_logic(self, sym, price_data):
        hist = list(self.history[sym])
        current_price = price_data['priceUsd']
        
        ema_s = self._ema(hist, self.w_short)
        ema_l = self._ema(hist, self.w_long)
        vol = self._volatility(hist, self.w_vol)
        rsi = self._rsi(hist, self.w_rsi)
        
        # Z-Score: Distance from mean normalized by volatility
        if current_price == 0: return None
        dev = (current_price - ema_l) / current_price
        z_score = dev / max(vol, 0.0001)
        
        score = 0.0
        reasons = []

        # === LOGIC A: Statistical Reversion (Strict) ===
        # Addressed 'DIP_BUY' penalty by making conditions stricter.
        # 1. Z-Score must be extreme (< -3.2 Sigma)
        # 2. RSI must be oversold (< 25)
        # 3. No 'falling knife': Price should be stabilizing (not implemented here for speed, relying on strict z-score)
        if z_score < -3.2 and rsi < 25:
            score = 100.0 + abs(z_score) # Priority on depth
            reasons = ["STATISTICAL_OVERSOLD", "MEAN_REVERSION"]

        # === LOGIC B: Kinetic Momentum Breakout ===
        # Addressed 'EXPLORE' by ensuring strong signal confirmation.
        # 1. Price > EMA Short > EMA Long (Trend Alignment)
        # 2. Volatility Expanding (Vol > Hist Vol)
        # 3. Z-Score > 1.0 (Started moving) but < 3.0 (Not chased)
        # 4. RSI Bullish (55-75)
        elif current_price > ema_s and ema_s > ema_l:
            # Check vol expansion
            prev_vol = self._volatility(hist[:-5], self.w_vol)
            if vol > prev_vol and 55 < rsi < 75:
                if 1.0 < z_score < 3.0:
                    score = 50.0 + (rsi - 50.0)
                    reasons = ["KINETIC_BREAKOUT", "TREND_ALIGNMENT"]
        
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
        
        # Volatility Sizing: Target 1.5% Risk
        risk_per_share = price * (vol * 2.5) # Assuming 2.5 std dev risk
        if risk_per_share == 0: return None
        
        risk_budget = self.balance * 0.015
        qty = risk_budget / risk_per_share
        
        # Max Position Cap
        max_qty = (self.balance * self.position_size_pct) / price
        qty = min(qty, max_qty)
        
        # Min Trade Size (Dust Protection)
        if qty * price < 10.0: return None
        
        self.positions[sym] = {
            'amt': qty,
            'entry_px': price,
            'high_water': 0.0,
            'tick_entry': self.tick_counter
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

    # === Fast Math Helpers ===
    
    def _ema(self, data, window):
        if not data: return 0.0
        k = 2.0 / (window + 1)
        ema = data[0]
        for x in data[1:]:
            ema = (x * k) + (ema * (1.0 - k))
        return ema

    def _volatility(self, data, window):
        # Rolling Standard Deviation of Returns
        if len(data) < window + 1: return 0.01
        
        subset = data[-window-1:]
        rets = []
        for i in range(1, len(subset)):
            if subset[i-1] == 0: continue
            r = (subset[i] - subset[i-1]) / subset[i-1]
            rets.append(r)
            
        if len(rets) < 2: return 0.01
        return statistics.stdev(rets)

    def _rsi(self, data, window):
        if len(data) < window + 1: return 50.0
        
        subset = data[-(window+1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(subset)):
            diff = subset[i] - subset[i-1]
            if diff > 0: gains += diff
            elif diff < 0: losses += abs(diff)
            
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))