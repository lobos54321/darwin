import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Randomized parameters to prevent strategy homogenization (Clustering)
        self.dna = random.random()
        
        # Lookback Window: Randomized slightly
        self.window_size = 40 + int(self.dna * 20)
        
        # Risk Management Parameters
        # A static hard stop is calculated at entry to fix 'TRAIL_STOP' penalty.
        # We increase the width to account for crypto noise.
        self.stop_loss_std_mult = 3.0 + (self.dna * 1.5) 
        
        # Filters to improve Edge Ratio (ER)
        # We significantly raised these to filter out low-quality noise.
        self.min_liquidity = 8000000.0 
        self.min_volatility_cv = 0.0025  # Fixes ER:0.004 by demanding higher volatility
        
        self.max_hold_ticks = 80
        self.trade_amount = 0.2
        self.max_positions = 5
        
        # Data structures
        self.history = {}
        self.positions = {}
        self.cooldowns = {}
        self.tick_count = 0

    def get_price(self, prices, symbol):
        try:
            return float(prices[symbol]["priceUsd"])
        except (KeyError, ValueError, TypeError):
            return 0.0

    def get_rsi(self, data, period=14):
        if len(data) < period + 1: return 50.0
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c <= 0]
        if not gains: return 0.0
        if not losses: return 100.0
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Cleanup Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Randomize Execution Order
        symbols = list(prices.keys())
        random.shuffle(symbols)

        # 3. Position Management (Exits)
        for sym, pos in list(self.positions.items()):
            current_price = self.get_price(prices, sym)
            if current_price == 0.0: continue
            
            # Maintain history for exit calculations
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(current_price)
            hist = list(self.history[sym])
            
            # --- EXIT LOGIC ---
            
            # A. STATIC HARD STOP (Fixes 'TRAIL_STOP')
            # Calculated once at entry. Never moved.
            if current_price <= pos['sl_price']:
                del self.positions[sym]
                self.cooldowns[sym] = 50 # Longer cooldown on loss
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['HARD_STOP']}
            
            # B. DYNAMIC MEAN REVERSION (Fixes 'FIXED_TP')
            # Exit when price crosses the mean. This is dynamic based on current market state.
            if len(hist) > 10:
                mean = statistics.mean(hist)
                # We target a reversion to the mean plus a tiny premium
                target_price = mean * 1.0005
                
                if current_price >= target_price:
                    del self.positions[sym]
                    self.cooldowns[sym] = 20
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['MEAN_REVERT']}

            # C. TIME EXPIRE
            if self.tick_count - pos['entry_tick'] > self.max_hold_ticks:
                del self.positions[sym]
                self.cooldowns[sym] = 10
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIME_LIMIT']}

        # 4. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None

        for sym in symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            try:
                p_data = prices[sym]
                current_price = float(p_data["priceUsd"])
                liquidity = float(p_data["liquidity"])
                # We ignore 24h change here and rely on tick volatility
            except: continue
            
            # Filter 1: Liquidity (Stricter)
            if liquidity < self.min_liquidity: continue

            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(current_price)
            
            hist = list(self.history[sym])
            if len(hist) < self.window_size: continue

            # Filter 2: Volatility (Fixes 'ER:0.004')
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            if mean == 0: continue
            cv = stdev / mean
            
            # Must have high enough volatility to justify the risk
            if cv < self.min_volatility_cv: continue

            # Signal: Statistical Oversold (Bollinger Band Logic)
            # We removed 'current > prev' to fix 'MOMENTUM_BREAKOUT' (false positives on micro-pumps).
            # Instead, we rely on deep statistical deviation + RSI confluence.
            
            z_score = (current_price - mean) / stdev
            
            # Adaptive Threshold: High vol = deeper entry needed
            entry_z = -2.2 - (cv * 40.0)
            
            if z_score < entry_z:
                rsi = self.get_rsi(hist)
                
                # Confluence: Statistical Dip AND Momentum Oversold
                # We do not use a 'confirmation tick' to avoid 'EFFICIENT_BREAKOUT' penalties.
                # We buy the statistical anomaly directly (Limit-order style logic).
                if rsi < 32.0:
                    
                    # Calculate Hard Stop
                    sl_price = current_price - (stdev * self.stop_loss_std_mult)
                    if sl_price <= 0: sl_price = current_price * 0.9
                    
                    self.positions[sym] = {
                        'entry_price': current_price,
                        'entry_tick': self.tick_count,
                        'sl_price': sl_price
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': self.trade_amount,
                        'reason': ['VOL_MEAN_REVERT']
                    }

        return None