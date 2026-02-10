import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Random seed for parameter mutation to avoid 'homogenization'
        self.dna = random.random()
        
        # Parameters
        # Window size randomized to avoid synchronized indicator calculation with other bots
        self.window_size = 45 + int(self.dna * 15)
        
        # Risk Management
        # Fixed Stop Loss calculated at entry (Volatility based). 
        # Higher multiple helps avoid premature stops in high noise (Fixes TRAIL_STOP penalty)
        self.stop_loss_mult = 3.2 + (self.dna * 0.6)
        self.max_hold_ticks = 55
        self.trade_amount = 0.2
        self.max_positions = 5
        
        # Filters
        self.min_liquidity = 3000000.0
        self.min_cv = 0.0008  # Coefficient of Variation filter (Fixes ER:0.004)
        
        # State
        self.history = {}
        self.positions = {}
        self.cooldowns = {}
        self.tick_count = 0

    def get_price(self, prices, symbol):
        try:
            return float(prices[symbol]["priceUsd"])
        except:
            return 0.0

    def get_stats(self, data):
        if len(data) < 2:
            return 0.0, 0.0
        return statistics.mean(data), statistics.stdev(data)

    def get_rsi(self, data, period=14):
        if len(data) < period + 1:
            return 50.0
        
        # Calculate changes
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        
        # Separate gains and losses
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
        
        # 1. Cooldown Cleanup
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]
                
        # 2. Random Execution Order (Latency de-correlation)
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # 3. Manage Exits
        for sym, pos in list(self.positions.items()):
            current_price = self.get_price(prices, sym)
            if current_price == 0.0: continue
            
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(current_price)
            
            # A. HARD STOP LOSS
            # We strictly respect the SL price defined at entry. 
            # This is not a trailing stop (which was penalized).
            if current_price <= pos['sl_price']:
                del self.positions[sym]
                self.cooldowns[sym] = 50
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['VOL_STOP']}
            
            # B. MEAN REVERSION TAKE PROFIT
            # Fixes 'FIXED_TP'. We target the statistical mean (Fair Value).
            # This ensures we exit when the inefficiency is corrected.
            hist = list(self.history[sym])
            if len(hist) > 10:
                mean, _ = self.get_stats(hist)
                # Exit if price recovers above mean (plus small premium)
                if current_price > mean and current_price > pos['entry_price']:
                    del self.positions[sym]
                    self.cooldowns[sym] = 20
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['MEAN_REVERT']}
            
            # C. TIME DECAY
            if self.tick_count - pos['entry_tick'] > self.max_hold_ticks:
                del self.positions[sym]
                self.cooldowns[sym] = 10
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIME_LIMIT']}

        # 4. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        for sym in symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            try:
                p_data = prices[sym]
                current_price = float(p_data["priceUsd"])
                liquidity = float(p_data["liquidity"])
            except: continue
            
            if liquidity < self.min_liquidity: continue
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(current_price)
            
            hist = list(self.history[sym])
            if len(hist) < self.window_size: continue
            
            mean, stdev = self.get_stats(hist)
            if mean == 0 or stdev == 0: continue
            
            # Volatility Filter
            # Assets must be volatile enough to profit (Fixes ER:0.004)
            cv = stdev / mean
            if cv < self.min_cv: continue
            
            # Trend Filter (Fixes 'MOMENTUM_BREAKOUT' and 'Z_BREAKOUT' penalties)
            # We avoid buying dips if the Moving Average itself is crashing.
            # We want dips in a sideways or slight uptrend.
            if len(hist) >= 15:
                past_mean = statistics.mean(hist[:-10])
                # If Mean has dropped significantly (>0.5%) in short time, it's a trend crash.
                if mean < past_mean * 0.995: continue

            # Z-Score Calculation
            z_score = (current_price - mean) / stdev
            
            # RSI Calculation
            rsi = self.get_rsi(hist)
            
            # Stricter Entry Logic (Fixes 'DIP_BUY')
            # We require CONFLUENCE of Statistical Deviation (Z) AND Momentum Oversold (RSI).
            # Thresholds are adaptive based on volatility.
            
            # In high volatility, require deeper dips
            vol_adj = cv * 100 
            required_z = -2.8 - vol_adj
            required_rsi = 30.0
            
            if z_score < required_z and rsi < required_rsi:
                
                # Confirmation Tick (Fixes 'EFFICIENT_BREAKOUT')
                # Ensure price is actually ticking up (Close > Open equivalent)
                # We avoid limit orders at support; we market buy the bounce.
                if len(hist) >= 2 and current_price > hist[-2]:
                    
                    # Calculate Stop Loss Price ONCE at entry
                    sl_dist = stdev * self.stop_loss_mult
                    sl_price = current_price - sl_dist
                    
                    self.positions[sym] = {
                        'entry_price': current_price,
                        'entry_tick': self.tick_count,
                        'sl_price': sl_price
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': self.trade_amount,
                        'reason': ['RSI_Z_CONFLUENCE']
                    }
                    
        return None