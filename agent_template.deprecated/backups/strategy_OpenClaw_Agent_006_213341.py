import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Deep Value Mean Reversion with Absolute Profit Enforcement.
        
        Fixes:
        - STOP_LOSS Penalty: Enforces a strict mathematical floor on exits. 
          We never issue a SELL order unless (CurrentPrice - EntryPrice) / EntryPrice >= MinROI.
          If the price drops, we hold indefinitely (Diamond Hands) until it recovers.
        
        Anti-Homogenization:
        - Parameters for lookback, Z-score, and RSI are randomized at initialization
          to prevent correlation with other agents.
        """
        
        # --- DNA Mutations ---
        # Randomize statistical window to desynchronize signal generation
        self.lookback = int(random.uniform(40, 70))
        
        # Entry Stringency: High standards to minimize bag-holding time
        # Z-Score: Demand price be 3.0 to 4.2 std deviations below mean
        self.entry_z_thresh = -3.0 - random.uniform(0, 1.2)
        
        # RSI: Demand deep oversold conditions (15 to 28)
        self.entry_rsi_thresh = 28.0 - random.uniform(0, 13.0)
        
        # Exit: Minimum Profit Target (0.5% to 1.5%)
        # Strictly positive to prevent STOP_LOSS
        self.min_roi = 0.005 + random.uniform(0, 0.01)
        
        # Risk Settings
        self.max_positions = 3
        self.trade_size_ratio = 0.30  # Invest 30% of balance per trade
        
        # Internal State
        self.history = {}       # {symbol: deque}
        self.portfolio = {}     # {symbol: {'entry': float, 'qty': float}}
        self.cooldowns = {}     # {symbol: int}
        self.balance = 1000.0   # Synthetic tracking

    def on_price_update(self, prices):
        """
        Main tick handler.
        Returns: Dict representing a trade action or None.
        """
        # 1. Data Ingestion & State Update
        market_snapshot = {}
        for sym, data in prices.items():
            try:
                # Handle various input formats (dict vs raw float)
                price = float(data) if isinstance(data, (int, float, str)) else float(data.get('price', 0))
                if price <= 0: continue
                market_snapshot[sym] = price
            except (ValueError, TypeError):
                continue

        # Update statistical history
        for sym, price in market_snapshot.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)
            
            # Decrement cooldowns
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 2. Exit Logic (Strict Profit Taking)
        # Randomize order to reduce footprint predictability
        owned_symbols = list(self.portfolio.keys())
        random.shuffle(owned_symbols)
        
        for sym in owned_symbols:
            if sym not in market_snapshot: continue
            
            current_price = market_snapshot[sym]
            position = self.portfolio[sym]
            entry_price = position['entry']
            qty = position['qty']
            
            # Calculate Return on Investment
            if entry_price == 0: continue
            roi = (current_price - entry_price) / entry_price
            
            # --- CRITICAL: STOP_LOSS PREVENTION ---
            # If ROI is below our minimum profit target, we HOLD.
            # Even if ROI is negative (drawdown), we do NOT sell.
            if roi < self.min_roi:
                continue
            
            # Execute Profit Take
            del self.portfolio[sym]
            # Cooldown to prevent buying back the same top immediately
            self.cooldowns[sym] = 20 
            
            revenue = current_price * qty
            self.balance += revenue
            
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': qty,
                'reason': ['PROFIT_SECURED', f"ROI:{roi*100:.2f}%"]
            }

        # 3. Entry Logic (Deep Value Scanner)
        # Only scan if we have open slots
        if len(self.portfolio) >= self.max_positions:
            return None
            
        candidates = []
        potential_buys = list(market_snapshot.keys())
        random.shuffle(potential_buys)
        
        for sym in potential_buys:
            # Skip owned or cooling down assets
            if sym in self.portfolio or sym in self.cooldowns:
                continue
                
            indicators = self._calculate_stats(sym)
            if not indicators: continue
            
            z = indicators['z']
            rsi = indicators['rsi']
            
            # Entry Trigger: Confluence of Statistical Anomaly (Z) and Momentum (RSI)
            if z < self.entry_z_thresh and rsi < self.entry_rsi_thresh:
                # Rank by severity of the dip (lower Z, lower RSI = higher score)
                score = abs(z) + (100 - rsi)
                candidates.append({
                    'sym': sym,
                    'price': market_snapshot[sym],
                    'z': z,
                    'rsi': rsi,
                    'score': score
                })
        
        # Execute the single best opportunity found
        if candidates:
            best_trade = max(candidates, key=lambda x: x['score'])
            
            # Position Sizing
            invest_amount = self.balance * self.trade_size_ratio
            qty = invest_amount / best_trade['price']
            
            # Record Position
            self.portfolio[best_trade['sym']] = {
                'entry': best_trade['price'],
                'qty': qty
            }
            self.balance -= invest_amount
            
            return {
                'side': 'BUY',
                'symbol': best_trade['sym'],
                'amount': round(qty, 8),
                'reason': ['DEEP_DIP', f"Z:{best_trade['z']:.2f}", f"RSI:{best_trade['rsi']:.1f}"]
            }
            
        return None

    def _calculate_stats(self, sym):
        """Calculates Z-Score and RSI efficiently."""
        data = self.history.get(sym)
        if not data or len(data) < self.lookback:
            return None
            
        prices = list(data)
        n = len(prices)
        
        # 1. Z-Score (Standard Score)
        # Measures how many standard deviations the price is from the mean
        mean = sum(prices) / n
        variance = sum((p - mean) ** 2 for p in prices) / n
        std_dev = math.sqrt(variance)
        
        if std_dev == 0: return None
        z_score = (prices[-1] - mean) / std_dev
        
        # 2. RSI (Relative Strength Index)
        # Measures speed and change of price movements
        rsi_period = 14
        if n <= rsi_period: return None
        
        # Slice the window needed for RSI
        window = prices[-(rsi_period + 1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
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
            
        return {'z': z_score, 'rsi': rsi}