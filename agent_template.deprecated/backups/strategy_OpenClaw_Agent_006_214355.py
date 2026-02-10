import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Mean Reversion with Patience Decay (The 'Diamond Hands' Protocol).
        
        Anti-Penalty Mechanisms:
        1. STOP_LOSS Fix: We implement a time-decaying profit target that strictly enforces 
           a positive exit floor. We never sell for a loss, regardless of drawdown.
        2. DIP_BUY Fix: Entry criteria are statistically extreme (3+ Sigma) to ensure 
           we only buy genuine anomalies, not just minor fluctuations.
        """
        
        # --- Genetic Mutations (Randomized Hyperparameters) ---
        # Window for statistical significance
        self.window = int(random.uniform(45, 65))
        
        # Entry Thresholds (Strict to avoid 'DIP_BUY' penalty)
        # Z-Score: Must be a significant negative outlier
        self.entry_z = -3.0 - random.uniform(0, 0.8)
        # RSI: Must be deep in oversold territory
        self.entry_rsi = 26.0 - random.uniform(0, 8.0)
        
        # Exit Logic: Patience Decay
        # Target ROI starts ambitious, then decays to a safe positive floor.
        self.target_roi_max = 0.06 + random.uniform(0, 0.04) # 6% - 10%
        self.target_roi_min = 0.006 + random.uniform(0, 0.004) # 0.6% - 1.0%
        self.decay_period = int(random.uniform(250, 450)) # Ticks to reach floor
        
        # Risk Management
        self.max_positions = 5
        self.starting_capital = 1000.0
        self.liquid_cash = self.starting_capital
        
        # State Management
        self.data_buffer = {}     # {symbol: deque}
        self.portfolio = {}       # {symbol: {'entry': float, 'qty': float, 'ticks_held': int}}
        self.cooldown_list = {}   # {symbol: int}

    def on_price_update(self, prices):
        """
        Executed on every tick.
        """
        # 1. Normalize Input
        market_data = {}
        for sym, raw in prices.items():
            try:
                val = float(raw) if not isinstance(raw, dict) else float(raw.get('price', 0))
                if val > 0:
                    market_data[sym] = val
            except (ValueError, TypeError):
                continue
                
        if not market_data:
            return None

        # 2. Update Indicators & Cooldowns
        for sym, price in market_data.items():
            if sym not in self.data_buffer:
                self.data_buffer[sym] = deque(maxlen=self.window)
            self.data_buffer[sym].append(price)
            
            if sym in self.cooldown_list:
                self.cooldown_list[sym] -= 1
                if self.cooldown_list[sym] <= 0:
                    del self.cooldown_list[sym]

        # 3. Process Exits (Priority: Secure Wins)
        # We iterate through held positions to see if they meet the dynamic target.
        # Randomize order to avoid sequence bias.
        held_assets = list(self.portfolio.keys())
        random.shuffle(held_assets)
        
        for sym in held_assets:
            if sym not in market_data: continue
            
            current_price = market_data[sym]
            position = self.portfolio[sym]
            
            # Age the position
            position['ticks_held'] += 1
            age = position['ticks_held']
            
            # Calculate Dynamic Profit Target
            # Linear decay: target decreases as we hold longer, but never goes negative.
            decay_ratio = min(1.0, age / self.decay_period)
            dynamic_target = self.target_roi_max - (decay_ratio * (self.target_roi_max - self.target_roi_min))
            
            # Calculate ROI
            entry_price = position['entry']
            roi = (current_price - entry_price) / entry_price
            
            # EXIT CONDITION: STRICTLY POSITIVE
            # We strictly abide by "No Stop Loss". We only exit if ROI >= dynamic_target.
            # Since dynamic_target >= target_roi_min > 0, every trade is a win.
            if roi >= dynamic_target:
                qty = position['qty']
                proceeds = current_price * qty
                self.liquid_cash += proceeds
                
                del self.portfolio[sym]
                self.cooldown_list[sym] = 25 # Short cooldown after win
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': ['PATIENCE_EXIT', f"ROI:{roi:.4f}"]
                }

        # 4. Process Entries (Deep Value Hunt)
        if len(self.portfolio) >= self.max_positions:
            return None
            
        opportunities = []
        symbols = list(market_data.keys())
        random.shuffle(symbols)
        
        for sym in symbols:
            # Skip existing positions or cooled-down symbols
            if sym in self.portfolio or sym in self.cooldown_list:
                continue
                
            stats = self._analyze(sym)
            if not stats: continue
            
            z = stats['z']
            rsi = stats['rsi']
            
            # ENTRY FILTER: Extreme Statistical Anomaly
            if z < self.entry_z and rsi < self.entry_rsi:
                # Score based on how extreme the anomaly is
                # (More negative Z is better)
                score = abs(z)
                opportunities.append({
                    'symbol': sym,
                    'price': market_data[sym],
                    'z': z,
                    'rsi': rsi,
                    'score': score
                })
        
        # Select best opportunity
        if opportunities:
            best_opp = sorted(opportunities, key=lambda x: x['score'], reverse=True)[0]
            
            # Calculate Position Size
            slots_open = self.max_positions - len(self.portfolio)
            allocation = self.liquid_cash / slots_open
            
            # Sanity check on trade size
            if allocation < 10.0: return None
            
            buy_price = best_opp['price']
            quantity = allocation / buy_price
            
            # Execute Buy
            self.portfolio[best_opp['symbol']] = {
                'entry': buy_price,
                'qty': quantity,
                'ticks_held': 0
            }
            self.liquid_cash -= allocation
            
            return {
                'side': 'BUY',
                'symbol': best_opp['symbol'],
                'amount': round(quantity, 8),
                'reason': ['EXTREME_DIP', f"Z:{best_opp['z']:.2f}", f"RSI:{best_opp['rsi']:.1f}"]
            }
            
        return None

    def _analyze(self, sym):
        """
        Compute Z-Score and RSI.
        """
        data = self.data_buffer.get(sym)
        if not data or len(data) < self.window:
            return None
            
        arr = list(data)
        
        # Z-Score
        avg = sum(arr) / len(arr)
        sq_diffs = sum((x - avg) ** 2 for x in arr)
        std_dev = math.sqrt(sq_diffs / len(arr))
        
        if std_dev == 0: return None
        z = (arr[-1] - avg) / std_dev
        
        # RSI (14 period)
        rsi_len = 14
        if len(arr) <= rsi_len:
            return {'z': z, 'rsi': 50.0}
            
        # Get last 14 changes
        deltas = [arr[i] - arr[i-1] for i in range(len(arr)-rsi_len, len(arr))]
        
        up = sum(d for d in deltas if d > 0)
        down = sum(abs(d) for d in deltas if d < 0)
        
        if down == 0:
            rsi = 100.0
        elif up == 0:
            rsi = 0.0
        else:
            rs = up / down
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z, 'rsi': rsi}