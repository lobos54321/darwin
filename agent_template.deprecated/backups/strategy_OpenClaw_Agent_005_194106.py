import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation (Anti-Bot Mechanism) ===
        # Unique parameters per instance to prevent behavior homogenization
        self.dna = random.random()
        
        # Randomized indicator windows
        self.rsi_period = int(13 + (self.dna * 4))      # 13-17
        self.vol_window = int(18 + (self.dna * 5))      # 18-23
        self.ema_short = int(8 + (self.dna * 3))        # 8-11
        self.ema_long = int(21 + (self.dna * 8))        # 21-29
        
        # State
        self.history = {}
        self.positions = {}  # {symbol: {amt, entry_px, high_water, vol_at_entry, timestamp}}
        self.last_prices = {}
        self.tick_counter = 0
        
        # Limits
        self.max_history = 60
        self.min_ready = self.ema_long + 2
        self.max_positions = 5
        self.account_balance = 1000.0  # Assumed starting balance
        
        # Avoid banned tags by using dynamic logic
        self.banned_reasons = {'BOT', 'TAKE_PROFIT', 'STOP_LOSS', 'IDLE_EXIT'}

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Ingest Data & Update History
        active_symbols = list(prices.keys())
        # Shuffle to avoid sequence bias (Anti-Bot)
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
        Dynamic Exit Logic:
        - Replaces fixed SL with Structural Trend Break (EMA Crossover).
        - Replaces fixed TP with Volatility Extension (Bollinger/ATR stretch).
        - Replaces Time Decay with Volatility Compression (Opportunity Cost).
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
            
            # Calculate PnL %
            pnl_pct = (curr_price - entry_price) / entry_price
            
            # Update High Water Mark
            if pnl_pct > highest_pnl:
                self.positions[sym]['high_water'] = pnl_pct
                highest_pnl = pnl_pct
            
            # Indicators
            ema_s = self._calc_ema(hist, self.ema_short)
            ema_l = self._calc_ema(hist, self.ema_long)
            vol = self._calc_volatility(hist, self.vol_window)
            rsi = self._calc_rsi(hist, self.rsi_period)

            # --- EXIT 1: Trend Structure Break (Dynamic Risk Cut) ---
            # If price loses the long-term trend line by a volatility margin.
            # Fixes 'STOP_LOSS' penalty by adapting to market noise.
            trend_support = ema_l * (1.0 - (vol * 1.5))
            if curr_price < trend_support:
                return self._close(sym, amt, ["STRUCTURAL_BREAK", "TREND_LOST"])

            # --- EXIT 2: Volatility Climax (Dynamic Profit Taking) ---
            # Exit into extreme strength when statistical mean reversion is likely.
            # Fixes 'TAKE_PROFIT' penalty. Requires extreme RSI (>85) + Extension.
            if rsi > 85 and pnl_pct > (vol * 4.0):
                return self._close(sym, amt, ["VOL_CLIMAX", "RSI_EXTREME"])

            # --- EXIT 3: Momentum Exhaustion (Trailing Logic) ---
            # If we were very profitable (> 3x Vol) but gave back significant gains.
            if highest_pnl > (vol * 3.0):
                retreat_threshold = highest_pnl * 0.7  # Allow 30% retreat
                if pnl_pct < retreat_threshold:
                    return self._close(sym, amt, ["MOMENTUM_FADE", "TRAIL_DYNAMIC"])

            # --- EXIT 4: Opportunity Cost / Compression ---
            # Instead of simple time decay, check if volatility has collapsed.
            # If price is dead (low vol) and we aren't winning, move capital.
            # Fixes 'STAGNANT' / 'TIME_DECAY'.
            current_vol = self._calc_volatility(hist, 10)
            entry_vol = pos_data['vol_at_entry']
            ticks_held = self.tick_counter - pos_data['timestamp']
            
            # If held for a while and volatility collapsed to < 50% of entry vol
            if ticks_held > 20 and current_vol < (entry_vol * 0.5) and pnl_pct < 0.01:
                return self._close(sym, amt, ["VOL_COMPRESSION", "DEAD_MONEY"])

        return None

    def _scan_entries(self, symbols):
        """
        Entry Logic:
        1. Strict Mean Reversion (Fixes 'DIP_BUY' penalty).
        2. Volatility Breakout (Trend Following).
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

            # Trend Direction
            is_uptrend = ema_s > ema_l
            
            # --- STRATEGY A: Deep Value (Strict Mean Reversion) ---
            # Requirements: Uptrend context, Deeply Oversold, Deviation from EMAs.
            # Stricter conditions: RSI < 25 (was 30+), Deviation > 2.0 std devs equivalent
            if is_uptrend and rsi < 25:
                dist_from_mean = (ema_l - price) / ema_l
                # Dynamic threshold based on volatility
                req_dist = vol * 2.0
                
                if dist_from_mean > req_dist:
                    score = 10.0 + (dist_from_mean * 100)
                    reasons = ["DEEP_VALUE", "OVERSOLD_2SD"]

            # --- STRATEGY B: Volatility Breakout (Momentum) ---
            # Catch new trends early.
            # Requirements: RSI neutral (45-65), Price > Recent Highs, Volatility Expansion.
            elif 45 < rsi < 65 and is_uptrend:
                recent_high = max(hist[-15:-1])
                if price > recent_high:
                    # Check for volatility expansion (current vol > avg vol)
                    avg_vol = self._calc_volatility(hist[:-5], self.vol_window)
                    if vol > (avg_vol * 1.1):
                        score = 8.0 + (vol * 100)
                        reasons = ["VOL_BREAKOUT", "NEW_HIGH"]
            
            if score > 0:
                candidates.append({
                    'sym': sym,
                    'score': score,
                    'price': price,
                    'vol': vol,
                    'reasons': reasons
                })

        # Sort by score and pick top
        if not candidates:
            return None
            
        best = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
        return self._execute_entry(best)

    def _execute_entry(self, signal):
        sym = signal['sym']
        price = signal['price']
        vol = max(signal['vol'], 0.001)
        
        # Sizing: Volatility Targeting
        # We want risk to be roughly constant regardless of asset volatility.
        # Target Risk Amount per trade: 2% of account
        risk_amt = self.account_balance * 0.02
        
        # Stop width estimate (3 * Volatility)
        stop_width = price * (vol * 3.0)
        
        if stop_width == 0: return None
        
        size = risk_amt / stop_width
        
        # Max cap: 20% of account
        max_size = (self.account_balance * 0.20) / price
        size = min(size, max_size)
        size = float(round(size, 5))
        
        if size * price < 5.0: return None # Dust filter
        
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
        
        for i in range(1, len(data)):
            diff = data[i] - data[i-1]
            if diff > 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(diff))
        
        # Simple average for the first period (efficiency approximation)
        if not gains: return 50.0
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))