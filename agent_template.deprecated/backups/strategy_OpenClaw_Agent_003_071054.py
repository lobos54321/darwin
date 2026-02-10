import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique seed for strategy parameter variation
        self.dna = random.random()
        
        # --- Strategy Parameters ---
        # Lookback Window: Longer window to establish valid statistical mean
        self.lookback = int(24 + (self.dna * 8)) # 24 to 32 ticks
        
        # RSI Parameters: Primary Oscillator for Mean Reversion
        self.rsi_period = int(12 + (self.dna * 4)) # 12 to 16
        # Entry Threshold: Strict oversold condition to ensure deep dips
        self.rsi_buy_thresh = 24.0 + (self.dna * 4.0) # 24 to 28
        # Exit Threshold: Reversion to neutral/strength
        self.rsi_sell_thresh = 55.0 + (self.dna * 5.0) # 55 to 60
        
        # Risk Management
        # Stop Loss Multiplier: Uses volatility (Stdev) to set distance
        self.stop_mult = 2.5 + (self.dna * 0.5)
        # Max Hold Time: Force exit if thesis doesn't play out quickly
        self.max_hold_ticks = 50 
        
        # Filters
        self.min_liquidity = 750000.0
        self.min_volatility = 0.002 # Avoid flatline assets
        self.trade_amount = 0.15    # Position size
        self.max_positions = 5
        
        # State Management
        self.history = {}       # symbol -> deque of prices
        self.positions = {}     # symbol -> dict {entry_price, sl_price, entry_tick}
        self.cooldowns = {}     # symbol -> int ticks remaining
        self.tick_count = 0

    def get_rsi(self, prices):
        """Calculate Relative Strength Index."""
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Calculate price changes
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        # Use recent window
        window = changes[-self.rsi_period:]
        
        gains = sum(x for x in window if x > 0)
        losses = sum(abs(x) for x in window if x < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Cooldown Maintenance
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]
        
        # 2. Randomize Execution Order (Anti-Gaming)
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # Helper for price extraction
        def get_current_price(s):
            try:
                return float(prices[s]["priceUsd"])
            except (KeyError, ValueError, TypeError):
                return None

        # 3. Position Management (Exits)
        for sym, pos in list(self.positions.items()):
            curr_price = get_current_price(sym)
            if curr_price is None: continue
            
            # Maintain history even while holding
            if sym not in self.history: self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(curr_price)
            hist = list(self.history[sym])
            
            # A. Hard Stop Loss (Fixes TRAIL_STOP penalty)
            # The stop price is fixed at entry and never moves.
            if curr_price <= pos['sl_price']:
                del self.positions[sym]
                self.cooldowns[sym] = 20
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['FIXED_STOP']}
            
            # B. Dynamic Indicator Exit (Fixes FIXED_TP penalty)
            # Exit based on RSI recovery, not a fixed price level.
            rsi = self.get_rsi(hist)
            roi = (curr_price - pos['entry_price']) / pos['entry_price']
            
            # Check for RSI Reversion
            if rsi > self.rsi_sell_thresh:
                # ER Improvement: Ensure we have at least minor profit to cover spread
                # This prevents 'churning' trades (high turnover, low profit).
                if roi > 0.002: 
                    del self.positions[sym]
                    self.cooldowns[sym] = 5
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['RSI_TARGET']}
            
            # C. Time Decay Exit
            if self.tick_count - pos['entry_tick'] > self.max_hold_ticks:
                del self.positions[sym]
                self.cooldowns[sym] = 10
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIME_LIMIT']}

        # 4. New Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        for sym in symbols:
            # Skip active positions or cooldowns
            if sym in self.positions or sym in self.cooldowns: continue
            
            try:
                data = prices[sym]
                curr_price = float(data["priceUsd"])
                liquidity = float(data["liquidity"])
            except: continue
            
            # Liquidity Filter
            if liquidity < self.min_liquidity: continue
            
            # History Update
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(curr_price)
            
            if len(self.history[sym]) < self.lookback: continue
            
            hist = list(self.history[sym])
            
            # --- Signal Generation ---
            
            # Volatility Check
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            if mean == 0: continue
            
            # Ensure asset is volatile enough to trade
            if (stdev / mean) < self.min_volatility: continue
            
            # RSI Filter
            rsi = self.get_rsi(hist)
            
            # Strict Dip Criteria
            if rsi < self.rsi_buy_thresh:
                
                # Bollinger Band Check (Secondary Confirmation)
                # Price must be below the lower band (Mean - 2*Std)
                # This ensures the dip is statistically significant.
                lower_band = mean - (2.0 * stdev)
                
                if curr_price < lower_band:
                    
                    # Anti-Breakout Filter (Fixes BREAKOUT / Z_BREAKOUT)
                    # If the last candle was a massive crash (falling knife), wait.
                    # We check if the drop in the last tick > 2.5 standard deviations.
                    # This filters out "Explosive" moves that often signal trend continuation (Breakouts).
                    if len(hist) >= 2:
                        last_drop = hist[-2] - hist[-1]
                        if last_drop > (2.5 * stdev):
                            continue # Too violent, likely a crash/breakout
                    
                    # Calculate Hard Stop
                    stop_price = curr_price - (stdev * self.stop_mult)
                    # Safety clamp
                    if stop_price <= 0: stop_price = curr_price * 0.5
                    
                    self.positions[sym] = {
                        'entry_price': curr_price,
                        'sl_price': stop_price,
                        'entry_tick': self.tick_count
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': self.trade_amount,
                        'reason': ['RSI_BB_DIP']
                    }
                    
        return None