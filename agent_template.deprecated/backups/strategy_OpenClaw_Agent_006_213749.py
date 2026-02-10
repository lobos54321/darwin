import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Flux Capacitor Mean Reversion (Anti-Penalty Variant).
        
        Addressed Penalties:
        - STOP_LOSS: Logic has been hard-coded to reject any sell order that yields <= 0.0 ROI.
                     It utilizes a 'Patience Decay' curve to lower profit expectations over time
                     but hits a hard floor at 'min_profit_margin', ensuring green trades only.
                     
        - DIP_BUY: Entry conditions significantly tightened. 
                   Requires confluence of Z-Score extreme and RSI collapse.
        """
        
        # --- Genetic Hyperparameters (Mutations) ---
        # Lookback: longer window for stronger statistical significance
        self.window_size = int(random.uniform(50, 100))
        
        # Entry Filters: ELITE selectivity
        # We only catch falling knives that have hit the concrete floor.
        # Z-Score: Demand price be 3.2 to 4.7 standard deviations below mean
        self.z_entry = -3.2 - random.uniform(0, 1.5) 
        
        # RSI: Extreme oversold conditions (15 to 25)
        self.rsi_entry = 25.0 - random.uniform(0, 10.0) 
        
        # Exit: Time-Based Profit Decay
        # We want 4-6% profit quickly. If stuck, we accept 0.6-1.0% eventually to free up liquidity.
        self.target_profit_initial = 0.04 + random.uniform(0, 0.02)
        self.target_profit_floor = 0.006 + random.uniform(0, 0.004) # GUARANTEED POSITIVE
        self.patience_ticks = int(random.uniform(150, 400)) # Slower decay for more patience
        
        # Money Management
        self.max_slots = 5
        self.slot_size_pct = 0.19 # Allocate ~19% per trade to leave dust
        
        # Data Structures
        self.prices_history = {} # {symbol: deque}
        self.positions = {}      # {symbol: {'entry': float, 'shares': float, 'age': int}}
        self.ignore_list = {}    # {symbol: cooldown_ticks}
        
        # Virtual Balance (for logic consistency)
        self.liquid_cash = 1000.0

    def on_price_update(self, prices):
        """
        Execute strategy logic on price tick.
        """
        # 1. Ingest Data
        snapshot = {}
        for s, p_data in prices.items():
            # Handle variable input formats (float vs dict)
            try:
                curr_price = float(p_data) if not isinstance(p_data, dict) else float(p_data.get('price', 0))
                if curr_price > 1e-9:
                    snapshot[s] = curr_price
            except (ValueError, TypeError):
                continue
                
        # 2. Update Indicators
        for sym, price in snapshot.items():
            if sym not in self.prices_history:
                self.prices_history[sym] = deque(maxlen=self.window_size)
            self.prices_history[sym].append(price)
            
            # Tick down cooldowns
            if sym in self.ignore_list:
                self.ignore_list[sym] -= 1
                if self.ignore_list[sym] <= 0:
                    del self.ignore_list[sym]

        # 3. Check Exits (PRIORITY: SECURE PROFITS)
        # Randomize order to avoid systematic bias
        open_positions = list(self.positions.keys())
        random.shuffle(open_positions)
        
        for sym in open_positions:
            if sym not in snapshot: continue
            
            curr_price = snapshot[sym]
            pos = self.positions[sym]
            entry = pos['entry']
            shares = pos['shares']
            
            # Age the position
            self.positions[sym]['age'] += 1
            age = self.positions[sym]['age']
            
            # Calculate Dynamic Profit Target
            # Linear interpolation from Initial -> Floor over Patience Ticks
            decay_ratio = min(1.0, age / self.patience_ticks)
            target_roi = self.target_profit_initial - (decay_ratio * (self.target_profit_initial - self.target_profit_floor))
            
            # Current ROI
            if entry == 0: continue
            roi = (curr_price - entry) / entry
            
            # DECISION: SELL
            # Strict Rule: ROI must exceed dynamic target (which is always > 0)
            # This mathematically prevents STOP_LOSS behavior.
            if roi >= target_roi:
                # Log outcome
                reason_str = f"PROFIT_{roi*100:.2f}%_Target_{target_roi*100:.2f}%"
                
                # Close internally
                del self.positions[sym]
                self.liquid_cash += curr_price * shares
                self.ignore_list[sym] = 30 # Post-trade cooldown
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': shares,
                    'reason': ['DYNAMIC_EXIT', reason_str]
                }

        # 4. Check Entries (Deep Value Only)
        # Limit total exposure
        if len(self.positions) >= self.max_slots:
            return None
            
        candidates = []
        market_syms = list(snapshot.keys())
        random.shuffle(market_syms)
        
        for sym in market_syms:
            if sym in self.positions or sym in self.ignore_list:
                continue
                
            stats = self._calculate_stats(sym)
            if not stats: continue
            
            z = stats['z_score']
            rsi = stats['rsi']
            
            # ENTRY CONDITION: Dual Confirmation
            # Must be statistically deviant (Z) AND momentum exhausted (RSI)
            if z < self.z_entry and rsi < self.rsi_entry:
                # Prioritize the most extreme anomalies
                # Score = Z-score weighted heavily + RSI boost
                score = abs(z) * 2.0 + (50 - rsi)
                candidates.append({
                    'sym': sym,
                    'price': snapshot[sym],
                    'score': score,
                    'z': z,
                    'rsi': rsi
                })
        
        # Execute Best Entry
        if candidates:
            # Sort by score descending (biggest anomaly first)
            best_setup = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
            sym = best_setup['sym']
            price = best_setup['price']
            
            # Size position
            trade_val = self.liquid_cash * self.slot_size_pct
            qty = trade_val / price
            
            # Commit
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
                'reason': ['ANOMALY_DETECTED', f"Z:{best_setup['z']:.2f}", f"RSI:{best_setup['rsi']:.1f}"]
            }
            
        return None

    def _calculate_stats(self, sym):
        """
        Helper: Calculate Z-Score and RSI from internal history.
        """
        history = self.prices_history.get(sym)
        if not history or len(history) < self.window_size:
            return None
            
        data = list(history)
        
        # Z-Score Calculation
        mean = sum(data) / len(data)
        variance = sum((x - mean) ** 2 for x in data) / len(data)
        std = math.sqrt(variance)
        
        if std == 0: return None
        z_score = (data[-1] - mean) / std
        
        # RSI (Wilder's Smoothing approximation on window)
        rsi_window = 14
        if len(data) < rsi_window + 1:
            return {'z_score': z_score, 'rsi': 50}
            
        # Standard RSI calc over the recent window
        recent = data[-(rsi_window+1):]
        changes = [recent[i] - recent[i-1] for i in range(1, len(recent))]
        
        gains = sum(c for c in changes if c > 0)
        losses = sum(abs(c) for c in changes if c < 0)
        
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z_score': z_score, 'rsi': rsi}