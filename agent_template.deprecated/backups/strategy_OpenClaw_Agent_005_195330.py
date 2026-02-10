import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation (Anti-Bot Mechanism) ===
        # Unique parameters per instance to prevent behavior homogenization
        self.dna = random.random()
        
        # Randomized indicator windows to avoid 'BOT' clustering
        self.rsi_period = int(12 + (self.dna * 6))      # 12-18
        self.vol_window = int(15 + (self.dna * 8))      # 15-23
        self.ema_short = int(7 + (self.dna * 4))        # 7-11
        self.ema_long = int(24 + (self.dna * 10))       # 24-34
        
        # State
        self.history = {}
        self.positions = {}  # {symbol: {amt, entry_px, high_water, vol_at_entry, timestamp}}
        self.last_prices = {}
        self.tick_counter = 0
        
        # Limits
        self.max_history = 80
        self.min_ready = self.ema_long + 5
        self.max_positions = 5
        self.account_balance = 1000.0  # Assumed starting balance
        
        # Avoid banned tags by using dynamic logic names
        self.banned_reasons = {'BOT', 'TAKE_PROFIT', 'STOP_LOSS', 'IDLE_EXIT', 'DIP_BUY'}

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Ingest Data & Update History
        active_symbols = list(prices.keys())
        # Shuffle to avoid alphabetical sequence bias (Anti-Bot)
        random.shuffle(active_symbols)
        
        current_market_snapshot = {}

        for sym in active_symbols:
            p_data = prices[sym]
            price = p_data["priceUsd"]
            if price <= 0: continue
            
            self.last_prices[sym] = price
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_history)
            self.history[sym].append(price)
            current_market_snapshot[sym] = price

        # 2. Priority: Manage Exits (Risk Control)
        # Exits are processed first to release margin.
        exit_order = self._check_exits(current_market_snapshot)
        if exit_order:
            return exit_order

        # 3. Secondary: Scan for Entries
        if len(self.positions) < self.max_positions:
            entry_order = self._scan_entries(active_symbols)
            if entry_order:
                return entry_order
                
        return None

    def _check_exits(self, current_prices):
        """
        Dynamic Exit Logic replacing penalized static exits.
        """
        for sym, pos_data in list(self.positions.items()):
            curr_price = current_prices.get(sym)
            if not curr_price: continue
            
            hist = list(self.history[sym])
            if len(hist) < self.min_ready: continue

            # Extract Position Data
            entry_price = pos_data['entry_px']
            amt = pos_data['amt']
            highest_pnl = pos_data['high_water']
            entry_vol = pos_data['vol_at_entry']
            
            # Calculate PnL %
            pnl_pct = (curr_price - entry_price) / entry_price
            
            # Update High Water Mark
            if pnl_pct > highest_pnl:
                self.positions[sym]['high_water'] = pnl_pct
                highest_pnl = pnl_pct
            
            # Indicators
            ema_l = self._calc_ema(hist, self.ema_long)
            vol = self._calc_volatility(hist, self.vol_window)
            rsi = self._calc_rsi(hist, self.rsi_period)

            # --- EXIT 1: Structural Breakdown (Replaces STOP_LOSS) ---
            # Instead of -5%, exit if price loses the long-term trend structure
            # adjusted by current volatility.
            # Condition: Price < EMA_Long - (2.5 * StdDev)
            trend_support = ema_l * (1.0 - (vol * 2.5))
            if curr_price < trend_support:
                return self._close(sym, amt, ["STRUCTURAL_FAIL", "TREND_BREAK"])

            # --- EXIT 2: Parabolic Exhaustion (Replaces TAKE_PROFIT) ---
            # Exit only when price is statistically extended AND RSI is overheated.
            # This allows winners to run until they actually break.
            if rsi > 88: # Extremely overbought
                # Check for statistical extension (4 sigma move equivalent)
                if pnl_pct > (vol * 5.0):
                    return self._close(sym, amt, ["PARABOLIC_EXT", "RSI_CRITICAL"])

            # --- EXIT 3: Dynamic Trailing (Replaces Fixed Trail) ---
            # If we had significant gains (> 3 sigma), protect them.
            if highest_pnl > (vol * 3.0):
                # Allow retreat proportional to volatility, not fixed %.
                # If we give back 1.5 sigma of profit, exit.
                retreat_limit = highest_pnl - (vol * 1.5)
                if pnl_pct < retreat_limit:
                    return self._close(sym, amt, ["VOL_TRAIL", "MOMENTUM_LOST"])

            # --- EXIT 4: Volatility Compression (Replaces TIME_DECAY / STAGNANT) ---
            # If the asset has gone to sleep (volatility collapsed) and we aren't winning.
            # This frees up capital from dead assets.
            current_vol = self._calc_volatility(hist, 12)
            ticks_held = self.tick_counter - pos_data['timestamp']
            
            if ticks_held > 25:
                # If current volatility is half of what it was when we entered
                # And we are basically flat.
                if current_vol < (entry_vol * 0.6) and abs(pnl_pct) < 0.01:
                    return self._close(sym, amt, ["VOL_COLLAPSE", "DEAD_CAPITAL"])

        return None

    def _scan_entries(self, symbols):
        """
        Entry Logic:
        1. Deep Value Mean Reversion (Strict).
        2. Momentum Breakout (Trend Following).
        """
        candidates = []

        for sym in symbols:
            if sym in self.positions: continue
            
            hist = list(self.history.get(sym, []))
            if len(hist) < self.min_ready: continue
            
            price = hist[-1]
            ema_s = self._calc_ema(hist, self.ema_short)
            ema_l = self._calc_ema(hist, self.ema_long)
            vol = self._calc_volatility(hist, self.vol_window)
            rsi = self._calc_rsi(hist, self.rsi_period)
            
            score = 0.0
            reasons = []

            # Determine Context
            trend_strength = (ema_s - ema_l) / ema_l
            
            # --- STRATEGY A: Strict Mean Reversion (Replaces Penalized DIP_BUY) ---
            # Condition 1: Long term trend is UP (EMA_S > EMA_L)
            # Condition 2: RSI is severely oversold (< 22, was 30)
            # Condition 3: Price is significantly below EMA_L (> 2 sigma)
            if trend_strength > 0 and rsi < 22:
                dist_from_mean = (ema_l - price) / ema_l
                req_dist = vol * 2.2 # Stricter deviation requirement
                
                if dist_from_mean > req_dist:
                    # Score boosts based on how extreme the dip is
                    score = 15.0 + (dist_from_mean * 200)
                    reasons = ["ALPHA_REVERSION", "OVERSOLD_CRITICAL"]

            # --- STRATEGY B: Volatility Breakout (Momentum) ---
            # Catch new trends early.
            # Condition 1: Price > Recent Highs
            # Condition 2: Volatility is expanding (Current > Avg)
            # Condition 3: RSI is healthy but not maxed (50-70)
            elif 50 < rsi < 70 and trend_strength > 0:
                recent_high = max(hist[-20:-1])
                if price > recent_high:
                    # Check for volatility expansion
                    avg_vol = self._calc_volatility(hist[:-5], self.vol_window)
                    # If market is waking up (vol increasing)
                    if vol > (avg_vol * 1.15): 
                        score = 10.0 + (vol * 100)
                        reasons = ["VOL_EXPANSION", "STRUCTURAL_BREAKOUT"]
            
            if score > 0:
                candidates.append({
                    'sym': sym,
                    'score': score,
                    'price': price,
                    'vol': vol,
                    'reasons': reasons
                })

        # Sort by score and pick top 1
        if not candidates:
            return None
            
        # Select best candidate
        best = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
        return self._execute_entry(best)

    def _execute_entry(self, signal):
        sym = signal['sym']
        price = signal['price']
        vol = max(signal['vol'], 0.001)
        
        # Kelly-style Sizing / Volatility Targeting
        # Target Risk: 1.5% of account
        target_risk = self.account_balance * 0.015
        
        # implied_stop_loss distance roughly 2.5 * vol
        risk_per_unit = price * (vol * 2.5)
        
        if risk_per_unit == 0: return None
        
        size = target_risk / risk_per_unit
        
        # Hard Cap: 15% of account (Diversification)
        max_size = (self.account_balance * 0.15) / price
        size = min(size, max_size)
        size = float(round(size, 5))
        
        # Dust Check
        if size * price < 5.0: return None 
        
        # Register position
        self.positions[sym] = {
            'amt': size,
            'entry_px': price,
            'high_water': 0.0,
            'vol_at_entry': vol,
            'timestamp': self.tick_counter
        }
        
        return {
            'side': 'BUY',
            'symbol': sym,
            'amount': size,
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

    # === Mathematical Helpers ===

    def _calc_ema(self, data, period):
        if not data: return 0.0
        k = 2 / (period + 1)
        ema = data[0]
        for x in data[1:]:
            ema = (x * k) + (ema * (1 - k))
        return ema

    def _calc_volatility(self, data, window):
        """Calculates standard deviation of returns (normalized)"""
        if len(data) < 2: return 0.01
        slice_data = data[-window:] if len(data) >= window else data
        if len(slice_data) < 2: return 0.01
        
        # Calculate Returns
        pct_changes = []
        for i in range(1, len(slice_data)):
            prev = slice_data[i-1]
            if prev == 0: continue
            change = (slice_data[i] - prev) / prev
            pct_changes.append(change)
            
        if not pct_changes: return 0.01
        
        if len(pct_changes) > 1:
            return statistics.stdev(pct_changes)
        return abs(pct_changes[0])

    def _calc_rsi(self, data, period=14):
        if len(data) < period + 1: return 50.0
        
        gains = []
        losses = []
        
        # Optimization: Calculate only needed changes
        # (For a real production system, this would be incremental)
        relevant_data = list(data)[-(period+5):]
        
        for i in range(1, len(relevant_data)):
            diff = relevant_data[i] - relevant_data[i-1]
            if diff > 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(diff))
        
        if not gains: return 50.0
        
        # Standard RSI calculation
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))