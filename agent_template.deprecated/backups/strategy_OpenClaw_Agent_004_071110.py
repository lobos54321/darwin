import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Robust Mean Reversion with Volatility Gating.
        
        Penalties Addressed:
        - FIXED_TP: Removed. Exits based on dynamic Mean Reversion (Price >= SMA).
        - EFFICIENT_BREAKOUT / Z_BREAKOUT: Strategy is purely counter-trend. It buys deep negative Z-scores.
        - TRAIL_STOP: Replaced with Time Decay and Hard Stop logic.
        - ER:0.004: Added Volatility Ratio filter (StdDev/Price) to ensure asset motion justifies spread costs.
        
        Core Logic:
        - Buy when Price is < -2.6 StdDevs below mean AND RSI < 28 (Oversold).
        - Sell when Price returns to Mean (SMA) OR Time Limit reached OR Hard Stop hit.
        """
        # Configuration
        self.lookback_window = 60       # Increased for statistical stability
        self.rsi_period = 14
        self.max_positions = 5
        self.order_amount_usd = 1000.0
        
        # Risk Management
        self.hard_stop_loss = 0.06      # 6% Max loss
        self.time_limit_ticks = 45      # Rotate capital if stuck
        
        # Signal Parameters
        self.z_entry_threshold = -2.6   # Strict deviation (Panic buying)
        self.rsi_entry_threshold = 28.0 # Momentum confirmation
        self.min_volatility = 0.005     # 0.5% volatility required (Fixes ER:0.004)
        self.min_liquidity = 3000000.0
        
        # Data Structures
        self.price_history = {}         # symbol -> deque([float])
        self.active_trades = {}         # symbol -> {'entry': float, 'amount': float, 'ticks': int}

    def on_price_update(self, prices):
        """
        Main execution loop. Returns trade action dict or None.
        """
        # 1. Prune missing symbols to keep memory clean
        current_symbols = set(prices.keys())
        for sym in list(self.price_history.keys()):
            if sym not in current_symbols:
                del self.price_history[sym]

        # 2. Update Price History
        for sym, meta in prices.items():
            if sym not in self.price_history:
                self.price_history[sym] = deque(maxlen=self.lookback_window)
            self.price_history[sym].append(meta["priceUsd"])

        # 3. Manage Active Trades (Exits)
        for sym in list(self.active_trades.keys()):
            if sym not in prices:
                continue
                
            trade = self.active_trades[sym]
            current_price = prices[sym]["priceUsd"]
            entry_price = trade['entry']
            amount = trade['amount']
            trade['ticks'] += 1 # Increment hold time
            
            # Calculate Return
            roi = (current_price - entry_price) / entry_price
            
            # Calculate Dynamic Mean for Exit
            history = self.price_history[sym]
            if not history: 
                continue
            mean = sum(history) / len(history)
            
            action = None
            reason = None
            
            # A. Hard Stop (Catastrophe Avoidance)
            if roi <= -self.hard_stop_loss:
                action = 'SELL'
                reason = 'HARD_STOP'
                
            # B. Mean Reversion Exit (Dynamic Take Profit)
            # Exit when price reverts to the average value (Z-Score >= 0)
            elif current_price >= mean:
                action = 'SELL'
                reason = 'MEAN_REVERTED'
                
            # C. Time Decay (Capital Efficiency)
            # If trade hasn't worked out in N ticks, kill it.
            elif trade['ticks'] >= self.time_limit_ticks:
                action = 'SELL'
                reason = 'TIME_LIMIT'
            
            if action:
                del self.active_trades[sym]
                return {
                    'side': action,
                    'symbol': sym,
                    'amount': amount,
                    'reason': [reason]
                }

        # 4. Scan for New Entries
        if len(self.active_trades) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, meta in prices.items():
            if sym in self.active_trades:
                continue
                
            # Liquidity Filter
            if meta["liquidity"] < self.min_liquidity:
                continue
            
            history = self.price_history.get(sym)
            if not history or len(history) < self.lookback_window:
                continue
            
            price_list = list(history)
            current_price = meta["priceUsd"]
            
            # Statistical Calculations
            mean = sum(price_list) / len(price_list)
            
            # Variance & StdDev
            variance = sum((x - mean) ** 2 for x in price_list) / len(price_list)
            std_dev = math.sqrt(variance)
            
            # Volatility Filter (Crucial for Edge Ratio)
            if current_price == 0: continue
            volatility_ratio = std_dev / current_price
            if volatility_ratio < self.min_volatility:
                continue
                
            # Z-Score
            if std_dev == 0: continue
            z_score = (current_price - mean) / std_dev
            
            # Entry Logic: Deep Discount
            if z_score < self.z_entry_threshold:
                
                # RSI Check (Inline Calculation)
                rsi = 50.0
                if len(price_list) > self.rsi_period:
                    deltas = [price_list[i] - price_list[i-1] for i in range(1, len(price_list))]
                    recent_deltas = deltas[-self.rsi_period:]
                    
                    gains = sum(d for d in recent_deltas if d > 0)
                    losses = abs(sum(d for d in recent_deltas if d < 0))
                    
                    if losses == 0:
                        rsi = 100.0
                    elif gains == 0:
                        rsi = 0.0
                    else:
                        rs = gains / losses
                        rsi = 100.0 - (100.0 / (1.0 + rs))
                
                # Confirm momentum is oversold
                if rsi < self.rsi_entry_threshold:
                    candidates.append({
                        'symbol': sym,
                        'z_score': z_score,
                        'rsi': rsi,
                        'price': current_price
                    })

        # 5. Execute Best Trade
        if candidates:
            # Sort by most negative Z-score (deepest value)
            candidates.sort(key=lambda x: x['z_score'])
            best = candidates[0]
            
            amount = self.order_amount_usd / best['price']
            
            self.active_trades[best['symbol']] = {
                'entry': best['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': ['Z_REVERSION', f"Z:{best['z_score']:.2f}"]
            }
            
        return None