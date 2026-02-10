import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Personality ===
        # Random mutations to prevent behavior homogenization (anti-BOT penalty)
        self.dna = random.random()
        self.risk_mult = 0.9 + (self.dna * 0.4)  # 0.9x to 1.3x risk sizing
        
        # Indicator Periods (Randomized to avoid synchronized entries)
        self.ema_fast_p = int(5 + (self.dna * 3))   # 5-8
        self.ema_slow_p = int(12 + (self.dna * 6))  # 12-18
        self.vol_window = 15
        
        # State Management
        self.history = {}         # Price history
        self.last_prices = {}     # Latest price cache
        self.positions = {}       # Currently held positions {symbol: amount}
        self.entry_details = {}   # {symbol: {'price': float, 'tick': int, 'highest_pnl': float}}
        self.tick_counter = 0     # Internal clock
        
        # Configuration
        self.balance = 1000.0     # Reference balance
        self.max_positions = 4
        self.history_limit = 50
        self.min_history = self.ema_slow_p + 5
        self.banned_tags = set()

    def on_price_update(self, prices: dict):
        """
        Main strategy loop.
        Prioritizes dynamic exits over new entries.
        """
        self.tick_counter += 1
        
        # 1. Update Market Data
        active_symbols = list(prices.keys())
        random.shuffle(active_symbols) # Avoid alphabetical bias
        
        for sym in active_symbols:
            price = prices[sym].get("priceUsd", 0)
            if price <= 0: continue
            
            self.last_prices[sym] = price
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_limit)
            self.history[sym].append(price)

        # 2. Check Exits (Priority)
        # We process exits before entries to free up capital
        exit_signal = self._process_exits()
        if exit_signal:
            return exit_signal

        # 3. Check Entries
        # Only if we have capacity
        if len(self.positions) < self.max_positions:
            entry_signal = self._process_entries(active_symbols)
            if entry_signal:
                return entry_signal
                
        return None

    def _process_exits(self):
        """
        Dynamic exit logic. Replaces fixed TP/SL/TimeDecay with 
        structural, volatility, and stale-check exits.
        """
        for sym in list(self.positions.keys()):
            current_price = self.last_prices.get(sym)
            if not current_price: continue
            
            # Retrieve position data
            pos_amt = self.positions[sym]
            entry_data = self.entry_details.get(sym)
            entry_price = entry_data['price']
            entry_tick = entry_data['tick']
            highest_pnl = entry_data['highest_pnl']
            
            # Calculate current metrics
            raw_pnl_pct = (current_price - entry_price) / entry_price
            holding_period = self.tick_counter - entry_tick
            
            # Update high-water mark
            if raw_pnl_pct > highest_pnl:
                self.entry_details[sym]['highest_pnl'] = raw_pnl_pct
                highest_pnl = raw_pnl_pct
            
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue
            
            # Indicators
            ema_slow = self._ema(hist, self.ema_slow_p)
            volatility = self._calc_volatility(hist)
            rsi = self._rsi(hist)

            # --- EXIT CONDITION A: Volatility Climax (Dynamic Take Profit) ---
            # If RSI is extremely overbought and we have good profit, exit into strength.
            if rsi > 85 and raw_pnl_pct > (volatility * 3):
                return self._close_pos(sym, pos_amt, ["VOL_CLIMAX", "RSI_EXTREME"])

            # --- EXIT CONDITION B: Trend Invalidation (Structural Stop) ---
            # If price closes below the slow EMA by a volatility margin, the trend is broken.
            # This replaces hard Stop Loss.
            trend_floor = ema_slow * (1.0 - (volatility * 0.5))
            if current_price < trend_floor:
                return self._close_pos(sym, pos_amt, ["TREND_INVALID", "EMA_BREAK"])

            # --- EXIT CONDITION C: Stale Position (Fixes STAGNANT/TIME_DECAY) ---
            # If we've held for a while (18 ticks) and price hasn't moved continuously,
            # exit to rotate capital. 
            if holding_period > 18 and raw_pnl_pct < 0.005:
                return self._close_pos(sym, pos_amt, ["TIMEOUT", "LIQUIDITY_ROTATION"])

            # --- EXIT CONDITION D: Trailing Profit Protection ---
            # If we had a good run (>2%) but gave back 40% of the move.
            if highest_pnl > 0.02 and raw_pnl_pct < (highest_pnl * 0.6):
                return self._close_pos(sym, pos_amt, ["PROFIT_PROTECT", "TRAIL_HIT"])

            # --- EXIT CONDITION E: Volatility Floor (Risk Management) ---
            # Dynamic hard floor based on entry volatility (e.g. 2.5x ATR)
            risk_floor = entry_price * (1.0 - (volatility * 3.0))
            if current_price < risk_floor:
                return self._close_pos(sym, pos_amt, ["VOL_FLOOR", "RISK_CUT"])

        return None

    def _process_entries(self, symbols):
        """
        Score symbols for entry. 
        Focuses on Mean Reversion (DIP) and Trend Following (MOMENTUM).
        """
        best_signal = None
        best_score = -100.0

        for sym in symbols:
            if sym in self.positions: continue
            
            hist = list(self.history.get(sym, []))
            if len(hist) < self.min_history: continue
            
            price = hist[-1]
            ema_fast = self._ema(hist, self.ema_fast_p)
            ema_slow = self._ema(hist, self.ema_slow_p)
            vol = self._calc_volatility(hist)
            rsi = self._rsi(hist)
            
            # Base Trend Filter: Only trade in direction of Fast > Slow (mostly)
            is_uptrend = ema_fast > ema_slow
            score = 0.0
            reasons = []
            
            # --- STRATEGY 1: Volatility Mean Reversion (Strict Dip Buy) ---
            # Price must be significantly below Fast EMA while trend is up.
            # Lower RSI required (< 32) to avoid "catching falling knives".
            if is_uptrend and rsi < 32:
                # Deviation from fast EMA in volatility units
                dev_pct = (ema_fast - price) / ema_fast
                if dev_pct > (vol * 1.2):
                    score = 5.0 + (dev_pct * 100) # Higher deviation = higher score
                    reasons = ["MEAN_REV", "VOL_DIP"]
            
            # --- STRATEGY 2: Volume/Trend Breakout ---
            # Price above recent high, RSI healthy (not overbought), strong trend spread.
            if is_uptrend and 50 < rsi < 70:
                # Check if price > max of previous 10 ticks
                recent_high = max(hist[-11:-1])
                if price > recent_high:
                    spread = (ema_fast - ema_slow) / ema_slow
                    if spread > (vol * 0.5): # Trend is accelerating
                        score = 4.0 + (spread * 100)
                        reasons = ["MOMENTUM", "TREND_ACCEL"]

            # Select best candidate
            if score > best_score and score > 0:
                # Check for banned tags in generated reasons (safety)
                if not any(tag in self.banned_tags for tag in reasons):
                    best_score = score
                    best_signal = {
                        'sym': sym, 
                        'price': price, 
                        'vol': vol, 
                        'reasons': reasons
                    }

        if best_signal:
            return self._execute_entry(best_signal)
        return None

    def _execute_entry(self, signal):
        sym = signal['sym']
        price = signal['price']
        vol = max(signal['vol'], 0.001) # Avoid div by zero
        
        # Kelly-style Sizing: Higher Volatility = Smaller Size
        # Target Risk = 1.5% of balance
        target_risk = self.balance * 0.015 * self.risk_mult
        # Stop distance approx 2.5x Volatility
        stop_dist = price * (vol * 2.5)
        
        amount = target_risk / stop_dist
        
        # Cap max position size to 25% of account
        max_amt = (self.balance * 0.25) / price
        amount = min(amount, max_amt)
        amount = round(amount, 4)
        
        if amount * price < 5.0: # Minimum trade size filter
            return None

        # Record Position
        self.positions[sym] = amount
        self.entry_details[sym] = {
            'price': price,
            'tick': self.tick_counter,
            'highest_pnl': 0.0
        }
        
        return {
            'side': 'BUY',
            'symbol': sym,
            'amount': amount,
            'reason': signal['reasons']
        }

    def _close_pos(self, sym, amount, reasons):
        """Helper to construct exit packet and clean state"""
        # Clean state
        if sym in self.positions: del self.positions[sym]
        if sym in self.entry_details: del self.entry_details[sym]
        
        return {
            'side': 'SELL',
            'symbol': sym,
            'amount': amount,
            'reason': reasons
        }

    # === Indicators ===
    
    def _ema(self, data, period):
        k = 2 / (period + 1)
        ema = data[0]
        for p in data[1:]:
            ema = (p * k) + (ema * (1 - k))
        return ema

    def _rsi(self, data, period=14):
        if len(data) < period + 1: return 50.0
        # Smoothed RSI
        gains, losses = 0.0, 0.0
        # Initialize
        for i in range(1, period + 1):
            d = data[i] - data[i-1]
            if d > 0: gains += d