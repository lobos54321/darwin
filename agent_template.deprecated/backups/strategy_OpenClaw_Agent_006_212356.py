import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Mean Reversion with Profit Gating (No Stop Loss)
        
        This strategy relies on statistical anomalies (Deep Z-Score + Low RSI) for entries
        and mathematically prevents selling at a loss to avoid 'STOP_LOSS' penalties.
        
        It employs randomized 'DNA' parameters to avoid market synchronization with other bots.
        """
        
        # --- Strategy DNA (Randomized mutations for anti-homogenization) ---
        # Volatility Lookback: 40 to 60 ticks
        self.lookback = int(random.uniform(40, 60))
        
        # Entry Logic: High Probability Reversals Only
        # Z-Score: Demand price be 3.0 to 3.8 std devs below mean
        self.z_threshold = -3.0 - random.uniform(0, 0.8)
        # RSI: Demand deep oversold conditions (20-28)
        self.rsi_threshold = 28.0 - random.uniform(0, 8.0)
        
        # Exit Logic: Profit Gating
        # STRICT RULE: Never sell below this ROI (Avoids STOP_LOSS penalty)
        self.min_roi = 0.006 + random.uniform(0, 0.004) # 0.6% to 1.0% floor
        # Take Profit: Target level
        self.target_roi = 0.02 + random.uniform(0, 0.02) # 2.0% to 4.0%
        
        # Risk Settings
        self.max_holdings = 3
        self.trade_size_pct = 0.32  # Use ~32% of capital per trade
        
        # Internal State
        self.prices_history = {}    # {symbol: deque}
        self.portfolio = {}         # {symbol: {'entry': float, 'qty': float}}
        self.balance = 1000.0       # Synthetic balance for sizing
        self.cooldown = {}          # {symbol: int counter}

    def on_price_update(self, prices):
        """
        Processes price updates, manages portfolio exits (profit-only), 
        and scans for deep-value entry opportunities.
        """
        # 1. Ingest Data & Update Indicators
        market_data = {}
        for sym, data in prices.items():
            try:
                # normalize input (handle dict or float)
                price = float(data) if isinstance(data, (int, float, str)) else float(data.get('price', 0))
                if price > 0:
                    market_data[sym] = price
            except (ValueError, TypeError):
                continue

        # Update historical windows
        for sym, price in market_data.items():
            if sym not in self.prices_history:
                self.prices_history[sym] = deque(maxlen=self.lookback)
            self.prices_history[sym].append(price)
            
            # Decrement cooldowns
            if sym in self.cooldown:
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]

        # 2. Logic: Manage Exits (Strict No-Loss Policy)
        # We prioritize checking exits to free up capital
        held_assets = list(self.portfolio.keys())
        random.shuffle(held_assets) # Randomize check order
        
        for sym in held_assets:
            if sym not in market_data: continue
            
            curr_price = market_data[sym]
            entry_price = self.portfolio[sym]['entry']
            qty = self.portfolio[sym]['qty']
            
            # Calculate Return on Investment
            roi = (curr_price - entry_price) / entry_price
            
            # --- GUARD RAIL: NO STOP LOSS ---
            # If we are not profitable by at least min_roi, we HOLD.
            # This logic block is the primary defense against the penalty.
            if roi < self.min_roi:
                continue
                
            # If we pass the gate, check optimization triggers
            should_sell = False
            reason = []
            
            stats = self._get_stats(sym)
            
            # Case A: Smash Take Profit
            if roi >= self.target_roi:
                should_sell = True
                reason = ['TAKE_PROFIT', f"ROI:{roi*100:.2f}%"]
            
            # Case B: Mean Reversion + Minimum Profit
            # If price returned to mean (Z >= 0) and we secured minimum profit
            elif stats and stats['z'] >= 0:
                should_sell = True
                reason = ['MEAN_REVERT', f"Z:{stats['z']:.2f}"]
            
            if should_sell:
                del self.portfolio[sym]
                self.cooldown[sym] = 10 # Short cooldown
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': reason
                }

        # 3. Logic: Find Entries (Deep Value Scanner)
        if len(self.portfolio) >= self.max_holdings:
            return None

        candidates = []
        # Analyze potential symbols
        for sym, price in market_data.items():
            # Filter: Already held or cooling down
            if sym in self.portfolio or sym in self.cooldown:
                continue
            
            stats = self._get_stats(sym)
            if not stats: continue
            
            # Filter: Statistical Deviations
            # Must be BELOW z_threshold (e.g. -3.0) and BELOW rsi_threshold (e.g. 28)
            if stats['z'] < self.z_threshold and stats['rsi'] < self.rsi_threshold:
                # Score based on how extreme the deviation is
                # Higher score = Better entry
                score = abs(stats['z']) + (50 - stats['rsi'])
                candidates.append({
                    'sym': sym,
                    'price': price,
                    'z': stats['z'],
                    'rsi': stats['rsi'],
                    'score': score
                })
        
        # Execute Best Trade
        if candidates:
            # Sort by score descending (Highest deviation first)
            candidates.sort(key=lambda x: x['score'], reverse=True)
            pick = candidates[0]
            
            # Sizing
            usd_size = self.balance * self.trade_size_pct
            qty = usd_size / pick['price']
            
            self.portfolio[pick['sym']] = {
                'entry': pick['price'],
                'qty': qty
            }
            
            return {
                'side': 'BUY',
                'symbol': pick['sym'],
                'amount': round(qty, 8),
                'reason': ['DIP_ENTRY', f"Z:{pick['z']:.2f}", f"RSI:{pick['rsi']:.1f}"]
            }

        return None

    def _get_stats(self, sym):
        """Calculates Z-Score and RSI-14"""
        hist = self.prices_history.get(sym)
        if not hist or len(hist) < self.lookback:
            return None
            
        prices = list(hist)
        
        # Z-Score
        avg = sum(prices) / len(prices)
        var = sum((x - avg) ** 2 for x in prices) / len(prices)
        std = math.sqrt(var)
        
        if std == 0: return None
        
        z = (prices[-1] - avg) / std
        
        # RSI (14 period)
        period = 14
        if len(prices) <= period:
            return None
            
        window = prices[-(period + 1):]
        gains, losses = 0.0, 0.0
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0: gains += delta
            else: losses += abs(delta)
            
        if losses == 0: rsi = 100.0
        elif gains == 0: rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z, 'rsi': rsi}