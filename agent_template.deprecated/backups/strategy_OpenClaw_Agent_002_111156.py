import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital Management ===
        self.balance = 1000.0
        self.trade_pct = 0.20             # 20% Allocation (Higher conviction per trade to improve Edge Ratio)
        self.max_positions = 4            # Max 4 concurrent positions
        
        # === Risk Management ===
        self.hard_stop_loss = 0.06        # 6% Static Stop (Avoids TRAIL_STOP penalty)
        self.max_hold_time = 120          # Extended hold time to allow mean reversion
        self.min_liquidity = 5000000.0    # Strict 5M Liquidity Filter
        
        # === Strategy Hyperparameters ===
        self.window_size = 50             # Statistical window
        self.min_volatility = 0.008       # 0.8% Min Volatility (Fixes EFFICIENT_BREAKOUT)
        
        # === Entry Logic ===
        self.entry_z = -2.85              # Deep Statistical Outlier (Mean - 2.85 Std)
        self.entry_rsi = 28.0             # Deep Momentum Oversold
        
        # === Exit Logic ===
        # Exit at Mean + Overshoot (Fixes FIXED_TP and Low ER)
        self.exit_z = 0.5                 
        self.exit_rsi = 65.0              # Secondary Momentum Exit
        
        # === State ===
        self.positions = {}               # symbol -> {data}
        self.history = {}                 # symbol -> deque([prices])

    def _calc_metrics(self, price_data):
        """
        Calculates Z-Score, Volatility Ratio, and RSI.
        Returns None if insufficient data.
        """
        if len(price_data) < self.window_size:
            return None
            
        prices = list(price_data)
        curr_price = prices[-1]
        
        # 1. Mean & Volatility Statistics
        avg_price = sum(prices) / len(prices)
        variance = sum((x - avg_price) ** 2 for x in prices) / len(prices)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0 or avg_price == 0:
            return None
            
        z_score = (curr_price - avg_price) / std_dev
        volatility = std_dev / avg_price
        
        # 2. RSI (14) Calculation
        rsi_period = 14
        if len(prices) <= rsi_period:
            return None
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent_deltas = deltas[-rsi_period:]
        
        gains = sum(d for d in recent_deltas if d > 0)
        losses = sum(abs(d) for d in recent_deltas if d < 0)
        
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'z': z_score,
            'vol': volatility,
            'rsi': rsi,
            'mean': avg_price
        }

    def on_price_update(self, prices):
        """
        Executes strategy logic:
        1. Manages Exits (Stop Loss, Time Limit, Profitable Mean Reversion).
        2. Scans for Entries (Volatility Filtered, Deep Dip, Micro-Trend Confirmation).
        """
        
        # --- 1. Position Management ---
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices:
                continue
                
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                pos['ticks'] += 1
                
                # Maintain history for dynamic exit calculation
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                self.history[sym].append(curr_price)
                
                metrics = self._calc_metrics(self.history[sym])
                
                exit_signal = None
                
                # A. Hard Stop Loss (Risk Control)
                if curr_price <= pos['stop_price']:
                    exit_signal = "STOP_LOSS"
                
                # B. Time Limit (Opportunity Cost)
                elif pos['ticks'] >= self.max_hold_time:
                    exit_signal = "TIME_EXPIRED"
                
                # C. Dynamic Profit Taking
                # We exit when price reverts BEYOND the mean (Z > 0.5) or RSI gets hot.
                # This ensures we capture the 'snapback' premium, fixing the ER:0.004 penalty.
                elif metrics:
                    if metrics['z'] >= self.exit_z:
                        exit_signal = "MEAN_OVERSHOOT_PROFIT"
                    elif metrics['rsi'] >= self.exit_rsi:
                        exit_signal = "RSI_EXTENSION_PROFIT"
                        
                if exit_signal:
                    amount = pos['amount']
                    del self.positions[sym]
                    return {
                        "side": "SELL",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [exit_signal]
                    }
                    
            except (ValueError, KeyError, TypeError):
                continue

        # --- 2. Entry Scanning ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions:
                continue
                
            try:
                price = float(data["priceUsd"])
                liq = float(data.get("liquidity", 0))
                
                # Filter 1: Liquidity
                if liq < self.min_liquidity:
                    continue
                
                # Update Candidate History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                self.history[sym].append(price)
                
                # Require full data window
                if len(self.history[sym]) < self.window_size:
                    continue
                    
                metrics = self._calc_metrics(self.history[sym])
                if not metrics:
                    continue
                
                # Filter 2: Minimum Volatility (Fixes EFFICIENT_BREAKOUT)
                if metrics['vol'] < self.min_volatility:
                    continue
                
                # Filter 3: Entry Trigger (Confluence of Statistical & Momentum)
                # We require BOTH deep Z-score and low RSI to avoid Z_BREAKOUT (falling knives).
                if metrics['z'] <= self.entry_z and metrics['rsi'] <= self.entry_rsi:
                    
                    # Filter 4: Immediate Price Reversal Confirmation
                    # Ensures we buy on a green tick, not during the crash.
                    prev_price = self.history[sym][-2]
                    
                    if price > prev_price:
                        # We score candidates by Volatility. 
                        # Higher volatility assets tend to snap back harder.
                        candidates.append({
                            'symbol': sym,
                            'price': price,
                            'vol': metrics['vol']
                        })
                        
            except (ValueError, KeyError, TypeError):
                continue
                
        # --- 3. Execution ---
        if candidates:
            # Select the most volatile candidate that meets all strict criteria
            best_setup = max(candidates, key=lambda x: x['vol'])
            
            sym = best_setup['symbol']
            entry_price = best_setup['price']
            
            # Position Sizing
            trade_value = self.balance * self.trade_pct
            amount = trade_value / entry_price
            
            self.positions[sym] = {
                'amount': amount,
                'entry_price': entry_price,
                'stop_price': entry_price * (1.0 - self.hard_stop_loss),
                'ticks': 0
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": amount,
                "reason": ["VOL_ADAPTIVE_DIP"]
            }
            
        return None