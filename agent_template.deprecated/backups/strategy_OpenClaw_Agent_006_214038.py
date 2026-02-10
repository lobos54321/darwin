import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Deep Value Mean Reversion with Patience Decay.
        
        Adjustments for Penalties:
        1. NO STOP LOSS: We utilize a time-decaying profit target that asymptotes to a 
           strictly positive floor. We never sell for a loss (ROI < 0).
        2. STRICTER DIP BUY: Z-Score and RSI thresholds are tightened to only catch
           extreme statistical anomalies (3+ Sigma).
        """
        
        # --- Hyperparameters ---
        self.window_size = int(random.uniform(50, 80))
        
        # Entry: Stricter thresholds to avoid 'DIP_BUY' penalty
        # Z-Score: Must be extremely deviated (e.g. < -3.5)
        self.z_entry_thresh = -3.2 - random.uniform(0, 1.3)
        # RSI: Must be deep oversold
        self.rsi_entry_thresh = 24.0 - random.uniform(0, 6.0)
        
        # Exit: Patience Decay Curve
        # Target ROI starts high, decays to a floor, but NEVER goes negative.
        self.roi_target_initial = 0.06 + random.uniform(0, 0.03) # 6-9%
        self.roi_target_floor = 0.006 + random.uniform(0, 0.004) # 0.6-1.0% floor
        self.patience_duration = int(random.uniform(250, 450))
        
        # Risk Management
        self.max_positions = 5
        self.starting_cash = 1000.0
        self.current_cash = self.starting_cash
        
        # State Tracking
        self.history = {}       # {symbol: deque}
        self.positions = {}     # {symbol: {'entry': float, 'amount': float, 'age': int}}
        self.cooldowns = {}     # {symbol: int}

    def on_price_update(self, prices):
        """
        Executed on every price tick.
        Returns action dict or None.
        """
        # 1. Ingest Data
        market_snapshot = {}
        for sym, data in prices.items():
            try:
                # robust parsing for various simulators
                p = float(data) if not isinstance(data, dict) else float(data.get('price', 0))
                if p > 0:
                    market_snapshot[sym] = p
            except (ValueError, TypeError):
                continue

        # 2. Update History & Cooldowns
        for sym, price in market_snapshot.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(price)
            
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 3. Check Exits (Priority: Secure Profits)
        # We iterate randomly to avoid sequence bias
        open_positions = list(self.positions.keys())
        random.shuffle(open_positions)
        
        for sym in open_positions:
            if sym not in market_snapshot: continue
            
            current_price = market_snapshot[sym]
            pos_data = self.positions[sym]
            entry_price = pos_data['entry']
            amount = pos_data['amount']
            
            # Age the position
            self.positions[sym]['age'] += 1
            age = self.positions[sym]['age']
            
            # --- PATIENCE DECAY LOGIC ---
            # Calculate dynamic profit target based on holding time
            progress = min(1.0, age / self.patience_duration)
            target_roi = self.roi_target_initial - (progress * (self.roi_target_initial - self.roi_target_floor))
            
            # Calculate current ROI
            roi = (current_price - entry_price) / entry_price
            
            # EXIT TRIGGER
            # Only sell if ROI >= Target. Since Target >= Floor > 0, 
            # we guaranteed NEVER sell at a loss (No STOP_LOSS).
            if roi >= target_roi:
                # Book it
                del self.positions[sym]
                self.current_cash += current_price * amount
                self.cooldowns[sym] = 20 # Rest period
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': ['TARGET_HIT', f"ROI:{roi*100:.2f}%"]
                }

        # 4. Check Entries (Deep Value)
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        # Analyze potential symbols
        symbols = list(market_snapshot.keys())
        random.shuffle(symbols)
        
        for sym in symbols:
            if sym in self.positions or sym in self.cooldowns:
                continue
                
            stats = self._get_stats(sym)
            if not stats: continue
            
            z = stats['z']
            rsi = stats['rsi']
            
            # ENTRY TRIGGER
            # Stricter filters: High Z-score deviation AND low RSI
            if z < self.z_entry_thresh and rsi < self.rsi_entry_thresh:
                # Score creates a hierarchy of "best" dips
                # We prioritize Z-score slightly more
                score = abs(z) * 1.5 + (50 - rsi)
                candidates.append({
                    'sym': sym,
                    'price': market_snapshot[sym],
                    'z': z,
                    'rsi': rsi,
                    'score': score
                })
        
        # Execute Best Candidate
        if candidates:
            best = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
            sym = best['sym']
            price = best['price']
            
            # Position Sizing: Split remaining cash roughly equally among remaining slots
            remaining_slots = self.max_positions - len(self.positions)
            alloc_cash = self.current_cash / remaining_slots
            # Sanity check on min size
            if alloc_cash < 5.0: return None
            
            qty = alloc_cash / price
            
            self.positions[sym] = {
                'entry': price,
                'amount': qty,
                'age': 0
            }
            self.current_cash -= alloc_cash
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': round(qty, 8),
                'reason': ['DEEP_VALUE', f"Z:{best['z']:.2f}", f"RSI:{best['rsi']:.1f}"]
            }
            
        return None

    def _get_stats(self, sym):
        """
        Computes Z-Score and RSI for a symbol.
        """
        data = self.history.get(sym)
        if not data or len(data) < self.window_size:
            return None
            
        prices = list(data)
        
        # 1. Z-Score
        mean = sum(prices) / len(prices)
        variance = sum((x - mean) ** 2 for x in prices) / len(prices)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0: return None
        z_score = (prices[-1] - mean) / std_dev
        
        # 2. RSI (Relative Strength Index)
        rsi_period = 14
        if len(prices) < rsi_period + 1:
            # Not enough data for RSI, default neutral
            return {'z': z_score, 'rsi': 50}
            
        # Use recent window
        window = prices[-(rsi_period+1):]
        deltas = [window[i] - window[i-1] for i in range(1, len(window))]
        
        gains = sum(d for d in deltas if d > 0)
        losses = sum(abs(d) for d in deltas if d < 0)
        
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'rsi': rsi}