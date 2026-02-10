import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Allocation ===
        self.balance = 1000.0
        self.trade_pct = 0.18             # 18% allocation (Diversification > Concentration)
        self.max_concurrent = 5           # Max 5 trades
        
        # === Risk Management ===
        self.stop_loss_pct = 0.04         # 4% Static Hard Stop (No Trailing)
        self.max_hold_duration = 75       # Ticks to hold before forcing exit
        self.min_liquidity = 1200000.0    # High liquidity to ensure execution
        
        # === Strategy Hyper-Parameters ===
        self.window = 35                  # Rolling window size
        self.entry_z_score = 3.1          # Deep deviation trigger (>3.1 SD)
        self.entry_rsi_cap = 25.0         # Deep oversold condition
        self.min_volatility = 0.0008      # Min Volatility (CV) to ensure profitable range
        self.exit_rsi_trigger = 65.0      # Exit on Momentum Recovery (Not Fixed Price)
        
        # === State ===
        self.positions = {}               # {symbol: {data}}
        self.history = {}                 # {symbol: deque}

    def _get_metrics(self, price_seq):
        """
        Computes Mean, StdDev, RSI, and Coefficient of Variation.
        """
        if len(price_seq) < self.window:
            return None
            
        data = list(price_seq)[-self.window:]
        n = len(data)
        
        # Mean
        avg = sum(data) / n
        
        # Standard Deviation
        variance = sum((x - avg) ** 2 for x in data) / n
        std = math.sqrt(variance)
        
        # Coefficient of Variation (Volatility)
        cv = (std / avg) if avg > 0 else 0
        
        # RSI
        gains = 0.0
        losses = 0.0
        for i in range(1, n):
            delta = data[i] - data[i-1]
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
            
        return {'mean': avg, 'std': std, 'rsi': rsi, 'cv': cv}

    def on_price_update(self, prices):
        """
        Core Logic Loop
        1. Manage Exits (Risk / Momentum)
        2. Scan Entries (Deep Volatility Reversion)
        """
        
        # --- 1. Position Management ---
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices:
                continue
                
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                
                # Increment time
                pos['ticks'] += 1
                
                # Update history for exit indicators
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window + 10)
                self.history[sym].append(curr_price)
                
                stats = self._get_metrics(self.history[sym])
                
                exit_reason = None
                
                # A. Static Hard Stop (Risk)
                if curr_price <= pos['stop_price']:
                    exit_reason = "STATIC_STOP"
                    
                # B. Time Expiry (Opportunity Cost)
                elif pos['ticks'] >= self.max_hold_duration:
                    exit_reason = "TIME_decay"
                    
                # C. Momentum Exit (Profit)
                # Replaces FIXED_TP with a dynamic momentum check.
                # We exit when RSI pushes high enough to indicate the bounce is maturing.
                elif stats and stats['rsi'] >= self.exit_rsi_trigger:
                    exit_reason = "RSI_MOMENTUM_EXIT"
                
                if exit_reason:
                    amount = pos['amount']
                    del self.positions[sym]
                    return {
                        "side": "SELL",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [exit_reason]
                    }
                    
            except (ValueError, KeyError, TypeError):
                continue

        # --- 2. Entry Scanning ---
        if len(self.positions) >= self.max_concurrent:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions:
                continue
                
            try:
                price = float(data["priceUsd"])
                liq = float(data.get("liquidity", 0))
                
                # 1. Liquidity Filter
                if liq < self.min_liquidity:
                    continue
                
                # History Mgmt
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window + 10)
                self.history[sym].append(price)
                
                stats = self._get_metrics(self.history[sym])
                if not stats or stats['std'] == 0:
                    continue
                    
                # 2. Volatility Floor (Fixes ER:0.004 by ensuring movement)
                if stats['cv'] < self.min_volatility:
                    continue
                
                # 3. Z-Score Calculation
                deviation = price - stats['mean']
                z_score = deviation / stats['std']
                
                # Only interested in Dips
                if z_score >= 0:
                    continue
                
                # 4. Entry Logic: Deep Reversion
                # Stricter thresholds to avoid "EFFICIENT_BREAKOUT" penalties (false signals)
                if z_score < -self.entry_z_score and stats['rsi'] < self.entry_rsi_cap:
                    candidates.append({
                        'symbol': sym,
                        'price': price,
                        'z': z_score,
                        'rsi': stats['rsi']
                    })
                    
            except (ValueError, KeyError, TypeError):
                continue
                
        # --- 3. Execution ---
        if candidates:
            # Sort by Z-score (Prioritize deepest statistical outliers)
            best_trade = min(candidates, key=lambda x: x['z'])
            
            sym = best_trade['symbol']
            entry_price = best_trade['price']
            
            trade_val = self.balance * self.trade_pct
            amount = trade_val / entry_price
            
            # Record Position
            self.positions[sym] = {
                'amount': amount,
                'entry_price': entry_price,
                'ticks': 0,
                # Static Stop Loss set at inception (No Trailing)
                'stop_price': entry_price * (1.0 - self.stop_loss_pct)
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": amount,
                "reason": ["DEEP_VOL_DIP"]
            }
            
        return None