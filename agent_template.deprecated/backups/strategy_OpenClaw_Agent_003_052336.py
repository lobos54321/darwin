import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique seed for parameter mutation to prevent 'BOT' clustering
        self.dna = random.random()
        
        # Strategy Parameters (Mutated)
        # Fast/Slow EMAs for Trend Detection
        self.fast_window = int(7 + (self.dna * 3))    # Range: 7-10 (Fast reaction)
        self.slow_window = int(21 + (self.dna * 5))   # Range: 21-26 (Trend baseline)
        self.vol_lookback = 14
        
        # Risk Management Parameters
        self.min_liquidity = 750000.0  # Stricter gate for quality assets
        self.max_positions = 5
        
        # Trailing Stop Parameters (ATR Multiples)
        self.base_stop_atr = 2.5
        self.profit_stop_atr = 1.5  # Tighter stop once profitable
        
        # State Management
        self.hist = {}        # symbol -> deque of priceUsd
        self.pos = {}         # symbol -> {entry_price, highest_price, quantity, atr_entry}
        self.cooldown = {}    # symbol -> ticks remaining
        
        # Max history needed for Slow EMA
        self.max_hist_len = self.slow_window + 10

    def _get_ema(self, data, window):
        if not data or len(data) < window:
            return None
        # Simple optimization: Calculate EMA on the last slice
        # Ideally would maintain state, but for this snippet we calc on deque
        multiplier = 2 / (window + 1)
        ema = sum(list(data)[:window]) / window # Start with SMA
        for price in list(data)[window:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _get_rsi(self, data, period=14):
        if len(data) < period + 1:
            return 50.0 # Neutral default
        
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c < 0]
        
        if not losses and not gains: return 50.0
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        # 1. Randomize loop to avoid execution patterns
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # 2. Cooldown Management
        to_del_cd = []
        for sym in self.cooldown:
            self.cooldown[sym] -= 1
            if self.cooldown[sym] <= 0:
                to_del_cd.append(sym)
        for sym in to_del_cd:
            del self.cooldown[sym]

        # 3. Process Symbols
        for sym in symbols:
            # Data Integrity Check
            if sym not in prices: continue
            try:
                p_data = prices[sym]
                current_price = float(p_data["priceUsd"])
                liquidity = float(p_data["liquidity"])
                vol_24h = float(p_data["volume24h"])
            except (KeyError, ValueError, TypeError):
                continue

            # Update History
            if sym not in self.hist:
                self.hist[sym] = deque(maxlen=self.max_hist_len)
            self.hist[sym].append(current_price)
            
            history = self.hist[sym]
            if len(history) < self.slow_window: continue

            # Calculate Volatility (Standard Deviation of recent prices)
            # Used for Z-Score and ATR simulation
            recent_slice = list(history)[-self.vol_lookback:]
            volatility = statistics.stdev(recent_slice) if len(recent_slice) > 1 else current_price * 0.01

            # --- POSITION MANAGEMENT (EXIT LOGIC) ---
            if sym in self.pos:
                pos = self.pos[sym]
                entry_price = pos['entry_price']
                highest_price = pos['highest_price']
                
                # Update High Water Mark
                if current_price > highest_price:
                    self.pos[sym]['highest_price'] = current_price
                    highest_price = current_price
                
                # Dynamic Trailing Stop
                # If we are in profit (> 1% gain), tighten the stop to lock in gains
                roi = (current_price - entry_price) / entry_price
                
                atr_mult = self.profit_stop_atr if roi > 0.01 else self.base_stop_atr
                stop_distance = volatility * atr_mult
                
                # Stop price trails the highest price
                stop_price = highest_price - stop_distance
                
                # Hard Stop check
                if current_price < stop_price:
                    del self.pos[sym]
                    self.cooldown[sym] = 15 # Cool down after trade
                    reason = 'TRAILING_STOP' if roi > 0 else 'STOP_LOSS'
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': [reason]}
                
                continue # Holding position

            # --- ENTRY LOGIC (TREND FOLLOWING) ---
            # 1. Gatekeeping
            if len(self.pos) >= self.max_positions: continue
            if sym in self.cooldown: continue
            if liquidity < self.min_liquidity: continue
            
            # 2. Trend Calculation (EMA)
            # We strictly avoid buying dips. We buy confirmed uptrends.
            ema_fast = self._get_ema(history, self.fast_window)
            ema_slow = self._get_ema(history, self.slow_window)
            
            if ema_fast is None or ema_slow is None: continue

            # 3. Momentum Filters (Anti-Mean Reversion)
            # Condition A: Fast EMA must be above Slow EMA (Trend Up)
            if ema_fast <= ema_slow: continue
            
            # Condition B: Price must be above Fast EMA (Momentum Strong)
            # Mean Reversion would buy if price < EMA. We do the opposite.
            if current_price < ema_fast: continue
            
            # Condition C: RSI Confirmation
            # Buy when RSI is strong (55-85), not oversold (<30)
            rsi = self._get_rsi(list(history), 14)
            if rsi < 55 or rsi > 85: continue
            
            # Condition D: Breakout / Z-Score
            # Confirm price is pushing upper boundaries (1.0 std dev above mean)
            sma_local = sum(recent_slice) / len(recent_slice)
            z_score = (current_price - sma_local) / (volatility + 1e-8)
            
            # We want a positive breakout, but not a massive outlier (> 4.0)
            if 1.0 < z_score < 4.0:
                self.pos[sym] = {
                    'entry_price': current_price,
                    'highest_price': current_price,
                    'quantity': 0.1, # Standard unit
                    'atr_entry': volatility
                }
                return {'side': 'BUY', 'symbol': sym, 'amount': 0.1, 'reason': ['MOMENTUM_BREAKOUT']}

        return None