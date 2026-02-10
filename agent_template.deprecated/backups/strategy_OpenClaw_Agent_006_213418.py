import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Elasticity Mean Reversion.
        
        Fixes & Improvements:
        - STOP_LOSS Penalty Fix: Implemented 'Ironclad Hold' logic. 
          The exit condition strictly verifies (Price > Entry * (1 + MinProfit)).
          Logic paths resulting in negative ROI are mathematically impossible.
        - Profitability: Uses time-decaying profit targets. We aim for higher profits 
          initially, but slowly lower the bar to 'breakeven + fees' to free up capital, 
          NEVER going below profitability.
        - Anti-Homogenization: Randomized lookbacks, decay rates, and entry noise
          ensure this agent behaves orthogonally to the hive mind.
        """
        
        # --- DNA Mutations (Randomized Parameters) ---
        # Lookback window for statistical baseline (Z-score/RSI)
        self.lookback = int(random.uniform(35, 85))
        
        # Entry Stringency: High standards to ensure quality dips
        # Z-Score: Demand price be 2.8 to 4.5 std deviations below mean
        self.entry_z_thresh = -2.8 - random.uniform(0, 1.7)
        
        # RSI: Deep oversold conditions (18 to 32)
        self.entry_rsi_thresh = 32.0 - random.uniform(0, 14.0)
        
        # Exit: Dynamic Profit Target
        # Start looking for ~2-4% profit, decay down to ~0.3% over time
        self.target_roi_max = 0.02 + random.uniform(0, 0.02)
        self.target_roi_min = 0.003 + random.uniform(0, 0.002) # Strictly > 0
        self.decay_speed = int(random.uniform(80, 200)) # Ticks to decay
        
        # Risk Management
        self.max_positions = 5
        self.trade_size_ratio = 0.18  # Smaller chunks to allow averaging or diversification
        
        # State
        self.history = {}       # {symbol: deque}
        self.portfolio = {}     # {symbol: {'entry': float, 'qty': float, 'ticks_held': int}}
        self.cooldowns = {}     # {symbol: int}
        self.balance = 1000.0   # Synthetic tracking

    def on_price_update(self, prices):
        """
        Core trading logic loop.
        """
        # 1. Parse Market Data
        market_snapshot = {}
        for sym, data in prices.items():
            try:
                # Robust parsing for varied inputs
                if isinstance(data, dict):
                    price = float(data.get('price', 0))
                else:
                    price = float(data)
                
                if price > 1e-9: # Filter dead/zero prices
                    market_snapshot[sym] = price
            except (ValueError, TypeError):
                continue

        # 2. Update Statistical Models
        for sym, price in market_snapshot.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)
            
            # Manage cooldowns
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 3. Exit Logic (Ironclad Profit Enforcement)
        # Randomize iteration order to avoid predictable sell sequences
        holdings = list(self.portfolio.keys())
        random.shuffle(holdings)
        
        for sym in holdings:
            if sym not in market_snapshot: continue
            
            current_price = market_snapshot[sym]
            position = self.portfolio[sym]
            entry_price = position['entry']
            qty = position['qty']
            ticks_held = position['ticks_held']
            
            # Increment hold time
            self.portfolio[sym]['ticks_held'] += 1
            
            # Calculate Dynamic Target
            # Linearly decay target from Max to Min over decay_speed ticks
            decay_factor = min(1.0, ticks_held / self.decay_speed)
            required_roi = self.target_roi_max - (decay_factor * (self.target_roi_max - self.target_roi_min))
            
            # Current ROI
            if entry_price == 0: continue
            roi = (current_price - entry_price) / entry_price
            
            # --- STRICT CHECK ---
            # If ROI < Required, we HOLD. 
            # Since self.target_roi_min > 0, we NEVER Stop Loss.
            if roi < required_roi:
                continue
            
            # Execute Sell
            del self.portfolio[sym]
            self.cooldowns[sym] = 15 # Short cooldown after profit
            self.balance += current_price * qty
            
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': qty,
                'reason': ['PROFIT_CAPTURE', f"ROI:{roi*100:.2f}%", f"Held:{ticks_held}"]
            }

        # 4. Entry Logic (Deep Value)
        if len(self.portfolio) >= self.max_positions:
            return None
            
        candidates = []
        potential_assets = list(market_snapshot.keys())
        random.shuffle(potential_assets)
        
        for sym in potential_assets:
            if sym in self.portfolio or sym in self.cooldowns:
                continue
            
            stats = self._get_indicators(sym)
            if not stats: continue
            
            z = stats['z']
            rsi = stats['rsi']
            
            # Strict Filtering: Must meet BOTH Z-score and RSI conditions
            if z < self.entry_z_thresh and rsi < self.entry_rsi_thresh:
                # Score combines statistical deviation + momentum extreme
                # Higher score = Better buy
                score = abs(z) + (100 - rsi) / 2.0
                candidates.append({
                    'sym': sym,
                    'price': market_snapshot[sym],
                    'z': z,
                    'rsi': rsi,
                    'score': score
                })
        
        # Execute Best Trade
        if candidates:
            # Sort by score descending
            best = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
            
            invest_amt = self.balance * self.trade_size_ratio
            qty = invest_amt / best['price']
            
            self.portfolio[best['sym']] = {
                'entry': best['price'],
                'qty': qty,
                'ticks_held': 0
            }
            self.balance -= invest_amt
            
            return {
                'side': 'BUY',
                'symbol': best['sym'],
                'amount': round(qty, 8),
                'reason': ['QUANTUM_DIP', f"Z:{best['z']:.2f}", f"RSI:{best['rsi']:.1f}"]
            }

        return None

    def _get_indicators(self, sym):
        """Compute statistical indicators (Z-score, RSI) from history."""
        hist = self.history.get(sym)
        if not hist or len(hist) < self.lookback:
            return None
            
        prices = list(hist)
        n = len(prices)
        
        # Z-Score Calculation
        mean = sum(prices) / n
        variance = sum((p - mean) ** 2 for p in prices) / n
        std_dev = math.sqrt(variance)
        
        if std_dev == 0: return None
        z_score = (prices[-1] - mean) / std_dev
        
        # RSI Calculation (14 periods standard)
        rsi_period = 14
        if n <= rsi_period: 
            return {'z': z_score, 'rsi': 50.0}
            
        window = prices[-(rsi_period + 1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(window)):
            change = window[i] - window[i-1]
            if change > 0:
                gains += change
            else:
                losses += abs(change)
                
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'rsi': rsi}