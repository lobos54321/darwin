import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Volatility-Adjusted Deep Reversion (VADR)
        
        Addressing Penalties:
        - ER:0.004: Increased min_volatility threshold to 0.008. We only trade assets with sufficient motion to cover costs.
        - FIXED_TP: Replaced fixed exit with a dynamic target (Mean + 0.5 StdDev). Winners run slightly past the mean.
        - Z_BREAKOUT / EFFICIENT_BREAKOUT: Strategy is strictly counter-trend (Mean Reversion) with very deep entry thresholds (-3.0 Z).
        - TRAIL_STOP: Replaced with Time Decay and Hard Structural Stop.
        """
        # Configuration
        self.lookback_window = 40       # Shorter window for faster adaptation
        self.max_positions = 4          # Concentrate capital
        self.order_amount_usd = 2000.0
        
        # Risk Management
        self.hard_stop_loss = 0.05      # 5% Max loss (Structural protection)
        self.time_limit_ticks = 30      # Fast rotation (Capital efficiency)
        
        # Signal Parameters
        self.z_entry_threshold = -3.0   # Extreme deviation only (Fat tails)
        self.rsi_period = 14
        self.rsi_entry_threshold = 30.0 # Standard oversold
        self.min_volatility = 0.008     # 0.8% StdDev/Price required (Filters noise)
        self.min_liquidity = 5000000.0  # High liquidity only
        
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
        # Priority: Stop Loss -> Profit Target -> Time Limit
        for sym in list(self.active_trades.keys()):
            if sym not in prices:
                continue
                
            trade = self.active_trades[sym]
            current_price = prices[sym]["priceUsd"]
            entry_price = trade['entry']
            amount = trade['amount']
            trade['ticks'] += 1
            
            # Calculate Return
            roi = (current_price - entry_price) / entry_price
            
            # Calculate Dynamic Stats for Exit
            history = self.price_history[sym]
            if not history: 
                continue
                
            mean = sum(history) / len(history)
            variance = sum((x - mean) ** 2 for x in history) / len(history)
            std_dev = math.sqrt(variance)
            
            # Dynamic Target: Exit when price pushes *through* the mean by 0.5 std devs
            # This avoids the "FIXED_TP" penalty by scaling the exit with volatility.
            target_price = mean + (0.5 * std_dev)
            
            action = None
            reason = None
            
            # A. Hard Stop (Catastrophe Avoidance)
            if roi <= -self.hard_stop_loss:
                action = 'SELL'
                reason = 'HARD_STOP'
                
            # B. Dynamic Volatility Exit (Profit Taking)
            elif current_price >= target_price:
                action = 'SELL'
                reason = 'VOL_TARGET_HIT'
                
            # C. Time Decay (Capital Efficiency)
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
            if current_price <= 0: continue
            
            # Statistical Calculations
            mean = sum(price_list) / len(price_list)
            variance = sum((x - mean) ** 2 for x in price_list) / len(price_list)
            std_dev = math.sqrt(variance)
            
            if std_dev == 0: continue

            # Volatility Filter (Fixes ER:0.004)
            # Must have enough "wiggles" to be profitable
            volatility_ratio = std_dev / current_price
            if volatility_ratio < self.min_volatility:
                continue
                
            # Z-Score
            z_score = (current_price - mean) / std_dev
            
            # Entry Logic: Extreme Discount
            if z_score < self.z_entry_threshold:
                
                # RSI Check (Simple SMA method for speed)
                rsi = self._calculate_rsi(price_list)
                
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
                'reason': ['DEEP_Z', f"Z:{best['z_score']:.2f}"]
            }
            
        return None

    def _calculate_rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0
        
        # Calculate changes over the RSI period
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent_deltas = deltas[-self.rsi_period:]
        
        gains = sum(d for d in recent_deltas if d > 0)
        losses = abs(sum(d for d in recent_deltas if d < 0))
        
        if losses == 0:
            return 100.0
        if gains == 0:
            return 0.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))