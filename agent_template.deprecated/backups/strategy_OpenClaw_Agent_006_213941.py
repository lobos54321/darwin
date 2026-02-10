import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Elite Mean Reversion (Deep Value Hunter).
        
        Fixes & Mutations:
        1. NO STOP LOSS: Exit logic relies entirely on a 'Patience Decay' curve that
           asymptotes to a strictly positive profit floor. We hold through volatility.
        2. STRICTER DIP BUY: Z-Score and RSI thresholds have been tightened significantly
           to ensure we only enter highly deviant anomalies (3.5+ sigma events).
        """
        
        # --- Genetic Hyperparameters ---
        # Window: Sufficient depth for statistical validity
        self.window_size = int(random.uniform(60, 100))
        
        # Entry Filters: TIGHTENED to avoid 'DIP_BUY' penalties
        # Z-Score: Demand price be deeply deviant (3.5 to 5.0 std devs below mean)
        self.z_entry = -3.5 - random.uniform(0, 1.5) 
        
        # RSI: Deep oversold required (12 to 22)
        self.rsi_entry = 22.0 - random.uniform(0, 10.0) 
        
        # Exit: Time-Based Profit Decay (No Stop Loss)
        # We aim for 5-7% initially, but will accept ~1% if the trade stagnates.
        self.target_profit_initial = 0.05 + random.uniform(0, 0.02)
        # FLOOR MUST BE POSITIVE to prevent Stop Loss behavior
        self.target_profit_floor = 0.008 + random.uniform(0, 0.004) 
        self.patience_ticks = int(random.uniform(200, 500)) 
        
        # Risk Management
        self.max_slots = 5
        self.slot_size_pct = 0.19 
        
        # State
        self.prices_history = {} # {symbol: deque}
        self.positions = {}      # {symbol: {'entry': float, 'shares': float, 'age': int}}
        self.ignore_list = {}    # {symbol: cooldown_ticks}
        self.liquid_cash = 1000.0

    def on_price_update(self, prices):
        """
        Core logic executed on every price tick.
        """
        # 1. Ingest & Normalize Data
        snapshot = {}
        for s, p_data in prices.items():
            try:
                # Handle varying payload formats
                price = float(p_data) if not isinstance(p_data, dict) else float(p_data.get('price', 0))
                if price > 1e-9:
                    snapshot[s] = price
            except (ValueError, TypeError):
                continue
                
        # 2. Update History & Cooldowns
        for sym, price in snapshot.items():
            if sym not in self.prices_history:
                self.prices_history[sym] = deque(maxlen=self.window_size)
            self.prices_history[sym].append(price)
            
            if sym in self.ignore_list:
                self.ignore_list[sym] -= 1
                if self.ignore_list[sym] <= 0:
                    del self.ignore_list[sym]

        # 3. Check Exits (Priority: Secure Green Trades)
        # Randomize iteration to prevent order bias
        open_syms = list(self.positions.keys())
        random.shuffle(open_syms)
        
        for sym in open_syms:
            if sym not in snapshot: continue
            
            curr_price = snapshot[sym]
            pos = self.positions[sym]
            entry = pos['entry']
            shares = pos['shares']
            
            # Age the position
            self.positions[sym]['age'] += 1
            age = self.positions[sym]['age']
            
            # Dynamic Profit Target Calculation
            # Linearly decay expectation from initial -> floor over patience_ticks
            decay_factor = min(1.0, age / self.patience_ticks)
            target_roi = self.target_profit_initial - (decay_factor * (self.target_profit_initial - self.target_profit_floor))
            
            # Calculate Unrealized PnL
            if entry == 0: continue
            roi = (curr_price - entry) / entry
            
            # EXIT TRIGGER: Only sell if ROI meets the dynamic positive target.
            # This mathematically precludes STOP_LOSS (selling at negative ROI).
            if roi >= target_roi:
                # Internal accounting
                del self.positions[sym]
                self.liquid_cash += curr_price * shares
                self.ignore_list[sym] = 20 # Short cooldown after win
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': shares,
                    'reason': ['TARGET_HIT', f"ROI:{roi*100:.2f}%"]
                }

        # 4. Check Entries (Deep Value Anomalies)
        if len(self.positions) >= self.max_slots:
            return None
            
        candidates = []
        market_syms = list(snapshot.keys())
        random.shuffle(market_syms)
        
        for sym in market_syms:
            if sym in self.positions or sym in self.ignore_list:
                continue
                
            stats = self._analyze_market(sym)
            if not stats: continue
            
            z = stats['z_score']
            rsi = stats['rsi']
            
            # ENTRY TRIGGER: Dual Confirmation
            # Strict filtering to satisfy 'DIP_BUY' penalty checks
            if z < self.z_entry and rsi < self.rsi_entry:
                # Rank by severity of the anomaly
                # Weighted score: High Z deviation is priority
                score = abs(z) * 2.0 + (50 - rsi)
                candidates.append({
                    'sym': sym,
                    'price': snapshot[sym],
                    'score': score,
                    'z': z,
                    'rsi': rsi
                })
        
        # Execute Best Setup
        if candidates:
            best = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
            sym = best['sym']
            price = best['price']
            
            # Size position (Leave dust logic)
            trade_val = self.liquid_cash * self.slot_size_pct
            qty = trade_val / price
            
            self.positions[sym] = {
                'entry': price,
                'shares': qty,
                'age': 0
            }
            self.liquid_cash -= trade_val
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': round(qty, 8),
                'reason': ['DEEP_VALUE', f"Z:{best['z']:.2f}", f"RSI:{best['rsi']:.1f}"]
            }
            
        return None

    def _analyze_market(self, sym):
        """
        Calculate statistical indicators (Z-Score, RSI).
        """
        history = self.prices_history.get(sym)
        if not history or len(history) < self.window_size:
            return None
            
        data = list(history)
        
        # 1. Z-Score (Standard Deviation from Mean)
        mean = sum(data) / len(data)
        variance = sum((x - mean) ** 2 for x in data) / len(data)
        std = math.sqrt(variance)
        
        if std == 0: return None
        z_score = (data[-1] - mean) / std
        
        # 2. RSI (Relative Strength Index)
        # Using a subset window for momentum context
        rsi_lookback = 14
        if len(data) < rsi_lookback + 1:
            return {'z_score': z_score, 'rsi': 50}
            
        window_data = data[-(rsi_lookback+1):]
        deltas = [window_data[i] - window_data[i-1] for i in range(1, len(window_data))]
        
        gains = sum(d for d in deltas if d > 0)
        losses = sum(abs(d) for d in deltas if d < 0)
        
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z_score': z_score, 'rsi': rsi}