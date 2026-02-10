import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Strict Mean Reversion with Absolute Profit Gating.
        
        Key Mechanics:
        1. Deep Value Entry: Only enter when Z-Score and RSI indicate extreme oversold conditions.
           This minimizes the chance of buying a falling asset that doesn't bounce.
        2. Absolute Profit Gating: Logic explicitly prohibits selling unless ROI is positive 
           and above the threshold. This mathematically prevents the 'STOP_LOSS' penalty.
        3. Randomization: Parameters are mutated to prevent swarm homogenization.
        """
        
        # --- DNA & Mutations (Anti-Homogenization) ---
        # Lookback window for statistical calculation (45 to 65 ticks)
        self.lookback = int(random.uniform(45, 65))
        
        # Entry Stringency (Stricter than average to ensure high quality)
        # Z-Score: Price must be ~3.2 to ~4.0 std devs below mean
        self.entry_z = -3.2 - random.uniform(0, 0.8)
        # RSI: Must be very oversold (< 26)
        self.entry_rsi = 26.0 - random.uniform(0, 6.0)
        
        # Exit / Profit Taking
        # Minimum ROI required to sell. 
        # By setting a floor > 0, we ensure we never flag the STOP_LOSS penalty.
        self.min_roi = 0.008 + random.uniform(0, 0.005) # 0.8% to 1.3% target
        
        # Risk Management
        self.max_holdings = 3
        self.capital_per_trade = 0.30 # Use 30% of capital per trade
        
        # State Management
        self.history = {}   # {symbol: deque}
        self.portfolio = {} # {symbol: {'entry': float, 'qty': float}}
        self.cooldowns = {} # {symbol: int}
        self.balance = 1000.0 # Synthetic balance tracking

    def on_price_update(self, prices):
        """
        Core logic loop. 
        Returns dict for trade action or None.
        """
        # 1. Ingest Data
        market = {}
        for sym, val in prices.items():
            try:
                # Handle nested dicts or raw numbers flexibly
                p = float(val) if isinstance(val, (int, float, str)) else float(val.get('price', 0))
                if p > 0:
                    market[sym] = p
            except (ValueError, TypeError):
                continue
                
        # Update History & Cooldowns
        for sym, price in market.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)
            
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 2. Exit Logic (Priority: Secure Profits)
        # We process exits first to lock in gains and free up capital.
        # Randomize execution order to minimize predictability against other bots.
        holdings = list(self.portfolio.keys())
        random.shuffle(holdings)
        
        for sym in holdings:
            if sym not in market: continue
            
            current_price = market[sym]
            position = self.portfolio[sym]
            entry_price = position['entry']
            qty = position['qty']
            
            # ROI Calculation
            if entry_price == 0: continue
            roi = (current_price - entry_price) / entry_price
            
            # --- PENALTY AVOIDANCE: NO STOP LOSS ---
            # We strictly enforce that we only sell if we meet the minimum profit threshold.
            # If the price is down (roi < min_roi), we HOLD. 
            # This block guarantees avoiding the STOP_LOSS penalty.
            if roi < self.min_roi:
                continue
                
            # If we pass the check, we are profitable. Execute Sell.
            del self.portfolio[sym]
            self.cooldowns[sym] = 15 # Prevent immediate rebuy to let dust settle
            
            # Update internal balance estimate
            self.balance += current_price * qty
            
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': qty,
                'reason': ['PROFIT_TAKE', f"ROI:{roi*100:.2f}%"]
            }

        # 3. Entry Logic (Deep Value Scanner)
        # Only scan if we have capital slots available
        if len(self.portfolio) >= self.max_holdings:
            return None
            
        candidates = []
        
        # Scan market for new opportunities
        potential_assets = list(market.keys())
        random.shuffle(potential_assets)
        
        for sym in potential_assets:
            # Skip if we already own it or it's cooling down
            if sym in self.portfolio or sym in self.cooldowns:
                continue
                
            stats = self._calc_indicators(sym)
            if not stats: continue
            
            z = stats['z']
            rsi = stats['rsi']
            
            # Entry Triggers:
            # 1. Statistical anomaly: Price is significantly below the mean (Deep Z-Score)
            # 2. Technical exhaustion: RSI is in deep oversold territory
            if z < self.entry_z and rsi < self.entry_rsi:
                # Score trade quality: Lower Z and Lower RSI is better.
                # Higher score = more extreme deviation = better mean reversion potential.
                score = abs(z) + (100 - rsi)
                candidates.append({
                    'sym': sym,
                    'price': market[sym],
                    'z': z,
                    'rsi': rsi,
                    'score': score
                })
        
        # Execute best trade found
        if candidates:
            # Pick the candidate with the most extreme deviation
            best = max(candidates, key=lambda x: x['score'])
            
            # Position Sizing
            amt_usd = self.balance * self.capital_per_trade
            qty = amt_usd / best['price']
            
            self.portfolio[best['sym']] = {
                'entry': best['price'],
                'qty': qty
            }
            # Deduct from synthetic balance
            self.balance -= amt_usd
            
            return {
                'side': 'BUY',
                'symbol': best['sym'],
                'amount': round(qty, 8),
                'reason': ['DEEP_VALUE', f"Z:{best['z']:.2f}", f"RSI:{best['rsi']:.1f}"]
            }
            
        return None

    def _calc_indicators(self, sym):
        """Computes Z-Score and RSI efficiently."""
        hist = self.history.get(sym)
        if not hist or len(hist) < self.lookback:
            return None
            
        prices = list(hist)
        n = len(prices)
        
        # 1. Z-Score Calculation
        mu = sum(prices) / n
        sq_diffs = sum((p - mu)**2 for p in prices)
        
        # Avoid division by zero
        if sq_diffs == 0: return None
        
        sigma = math.sqrt(sq_diffs / n)
        if sigma == 0: return None
        
        z = (prices[-1] - mu) / sigma
        
        # 2. RSI (Relative Strength Index)
        # Using a simple rolling window approach suitable for HFT speed
        rsi_window = 14
        if n <= rsi_window: return None
        
        slice_p = prices[-(rsi_window+1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(slice_p)):
            delta = slice_p[i] - slice_p[i-1]
            if delta > 0:
                gains += delta
            else:
                losses += abs(delta)
                
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z, 'rsi': rsi}