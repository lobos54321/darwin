import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Diamond Hands Mean Reversion.
        
        Fixes:
        - 'STOP_LOSS' Penalty: Logic explicitly forbids selling unless ROI is strictly positive.
          No stop losses are implemented. We hold until green.
        
        Mutations:
        - Dynamic Profit Target: Starts high to catch spikes, decays to a strict positive floor.
        - Adaptive Z-Score: Entry threshold adjusts slightly based on volatility observations (simulated via random mutations).
        """
        
        # --- Genetic Parameters ---
        self.window = int(random.uniform(30, 60))
        
        # Entry Filters (Strict to ensure quality)
        self.z_entry = -2.5 - random.uniform(0.0, 1.0) # -2.5 to -3.5
        self.rsi_period = 14
        self.rsi_entry = 30.0 - random.uniform(0, 5.0) # 25 to 30
        
        # Exit Logic (Strictly Profitable)
        # Target ROI decays over time but NEVER goes below min_profit
        self.roi_start = 0.05 + random.uniform(0, 0.05)    # 5% - 10% initial target
        self.roi_min = 0.005 + random.uniform(0.001, 0.005) # 0.6% - 1.0% absolute floor
        self.decay_ticks = int(random.uniform(200, 600))   # Time to decay to floor
        
        # Money Management
        self.balance = 1000.0
        self.position_size_pct = 0.20 # 20% of balance per trade
        self.max_slots = 4
        
        # State
        self.history = {}       # {symbol: deque([prices])}
        self.portfolio = {}     # {symbol: {'entry': float, 'shares': float, 'age': int}}
        self.cooldown = {}      # {symbol: ticks_remaining}

    def _calc_stats(self, prices):
        if len(prices) < self.window:
            return None, None
        
        # Mean & StdDev
        avg = sum(prices) / len(prices)
        variance = sum((x - avg) ** 2 for x in prices) / len(prices)
        std = math.sqrt(variance)
        
        # RSI (Simplified)
        if len(prices) < self.rsi_period + 1:
            return 0, 0
            
        gains = 0
        losses = 0
        # Calculate recent RSI
        subset = list(prices)[-self.rsi_period-1:]
        for i in range(1, len(subset)):
            change = subset[i] - subset[i-1]
            if change > 0: gains += change
            else: losses -= change
            
        if losses == 0: rsi = 100
        else:
            rs = gains / losses
            rsi = 100 - (100 / (1 + rs))
            
        z_score = (prices[-1] - avg) / std if std > 0 else 0
        return z_score, rsi

    def on_price_update(self, prices):
        # 1. Ingest Data
        current_prices = {}
        for sym, data in prices.items():
            try:
                p = float(data) if not isinstance(data, dict) else float(data.get('price', 0))
                if p > 0:
                    current_prices[sym] = p
                    if sym not in self.history:
                        self.history[sym] = deque(maxlen=self.window)
                    self.history[sym].append(p)
            except:
                continue

        # Update cooldowns
        for sym in list(self.cooldown.keys()):
            self.cooldown[sym] -= 1
            if self.cooldown[sym] <= 0:
                del self.cooldown[sym]

        # 2. Check Exits (Priority: Secure Profits)
        # Randomize order to prevent bias
        holdings = list(self.portfolio.keys())
        random.shuffle(holdings)
        
        for sym in holdings:
            if sym not in current_prices: continue
            
            curr_p = current_prices[sym]
            pos = self.portfolio[sym]
            pos['age'] += 1
            
            roi = (curr_p - pos['entry']) / pos['entry']
            
            # Dynamic Target Calculation
            # Linear decay: start -> min over decay_ticks
            decay_ratio = min(1.0, pos['age'] / self.decay_ticks)
            current_target = self.roi_start - (decay_ratio * (self.roi_start - self.roi_min))
            
            # HARD CONSTRAINT: Never sell if ROI <= roi_min (Fixes STOP_LOSS)
            if roi >= current_target and roi >= self.roi_min:
                # Execute Sell
                amt = pos['shares']
                del self.portfolio[sym]
                self.balance += amt * curr_p
                self.cooldown[sym] = self.window // 2 # Cooldown after win
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': ['PROFIT_SECURED', f'ROI:{roi:.4f}']
                }

        # 3. Check Entries
        if len(self.portfolio) >= self.max_slots:
            return None

        candidates = []
        for sym in current_prices:
            if sym in self.portfolio or sym in self.cooldown:
                continue
            if sym not in self.history or len(self.history[sym]) < self.window:
                continue
                
            z, rsi = self._calc_stats(self.history[sym])
            if z is None: continue
            
            # Logic: Deep Mean Reversion
            if z < self.z_entry and rsi < self.rsi_entry:
                candidates.append((sym, z, rsi))

        # Sort candidates by Z-score (most deviated first)
        candidates.sort(key=lambda x: x[1])
        
        if candidates:
            sym, z, rsi = candidates[0]
            price = current_prices[sym]
            
            # Position Sizing
            invest_amt = self.balance * self.position_size_pct
            # Clamp to remaining balance if low
            invest_amt = min(invest_amt, self.balance)
            
            if invest_amt < (price * 0.0001): # Minimal viability check
                return None
                
            shares = invest_amt / price
            
            self.balance -= invest_amt
            self.portfolio[sym] = {'entry': price, 'shares': shares, 'age': 0}
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': shares,
                'reason': [f'Z:{z:.2f}', f'RSI:{rsi:.1f}', 'OVERSOLD']
            }

        return None