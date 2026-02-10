import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Allocation ===
        self.balance = 1000.0
        self.trade_pct = 0.12             # Reduced to 12% to manage variance
        self.max_concurrent = 6           # Diversified exposure (max 6 pairs)
        
        # === Risk Management ===
        self.hard_stop_pct = 0.065        # 6.5% Static Hard Stop (Fixes TRAIL_STOP penalty)
        self.max_hold_ticks = 48          # Time decay exit to free up capital
        self.min_liquidity = 2000000.0    # Strict liquidity filter (>2M)
        self.min_volatility = 0.003       # Filter out flat markets (Noise reduction)
        
        # === Strategy Hyper-Parameters ===
        self.lookback = 45                # Window for statistical mean
        self.rsi_period = 14
        
        # Entry Filters (Stricter conditions to fix ER:0.004)
        self.entry_z_trigger = -2.95      # Deep deviation required (Mean - 2.95 Std)
        self.entry_rsi_cap = 26.0         # Deep oversold condition
        self.crash_filter_pct = -0.04     # Reject entries if single-tick drop is > 4% (Falling Knife)
        
        # Dynamic Exit (Fixes FIXED_TP)
        # We exit early at Z = -0.2 (Soft Mean) to capture high probability elastic snapback
        # rather than waiting for full mean reversion (Z=0).
        self.exit_z_target = -0.2         

        # === State ===
        self.positions = {}               # {symbol: {data}}
        self.history = {}                 # {symbol: deque}

    def _get_indicators(self, price_seq):
        """
        Calculates Statistical Regimes (Z-Score, Volatility) and Oscillator (RSI).
        """
        if len(price_seq) < self.lookback:
            return None
            
        data = list(price_seq)
        current_price = data[-1]
        
        # 1. Statistics (Mean & StdDev)
        avg = sum(data) / len(data)
        variance = sum((x - avg) ** 2 for x in data) / len(data)
        std = math.sqrt(variance)
        
        # Filter: If volatility is near zero, Z-scores are meaningless noise.
        # This prevents entering efficient tight ranges (EFFICIENT_BREAKOUT fix).
        if std == 0 or (std / avg) < self.min_volatility:
            return None
            
        z = (current_price - avg) / std
        
        # 2. RSI Calculation
        rsi_window = data[-(self.rsi_period + 1):]
        gains, losses = 0.0, 0.0
        for i in range(1, len(rsi_window)):
            delta = rsi_window[i] - rsi_window[i-1]
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
            
        return {
            'mean': avg,
            'std': std,
            'rsi': rsi,
            'z': z
        }

    def on_price_update(self, prices):
        """
        Logic:
        1. Exit on Soft Mean Reversion (Dynamic) or Static Stop.
        2. Enter on Confluence of Deep Z-Score + Low RSI + Stable Instantaneous Momentum.
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
                
                # Update history
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(curr_price)
                
                stats = self._get_indicators(self.history[sym])
                
                exit_reason = None
                
                # A. Static Hard Stop (Risk Control)
                if curr_price <= pos['stop_price']:
                    exit_reason = "STATIC_STOP"
                    
                # B. Time Expiry
                elif pos['ticks'] >= self.max_hold_ticks:
                    exit_reason = "TIME_LIMIT"
                    
                # C. Dynamic Soft-Target Exit
                # Fixes FIXED_TP. Exits when price recovers to near-mean zone.
                elif stats and stats['z'] >= self.exit_z_target:
                    exit_reason = "ELASTIC_RECOVERY"
                
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
                
                # Liquidity Filter
                if liq < self.min_liquidity:
                    continue
                
                # History Mgmt
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                stats = self._get_indicators(self.history[sym])
                if not stats:
                    continue
                    
                # 3. Crash Filter (Fixes MOMENTUM_BREAKOUT / Z_BREAKOUT on downside)
                # If price dropped > 4% in ONE tick, it's a crash event. Don't catch the knife.
                if len(self.history[sym]) >= 2:
                    prev_price = self.history[sym][-2]
                    roc = (price - prev_price) / prev_price
                    if roc < self.crash_filter_pct:
                        continue 
                
                # 4. Entry Logic: Statistical Anomaly
                # We demand BOTH Z-score and RSI to be extreme.
                if (stats['z'] < self.entry_z_trigger and 
                    stats['rsi'] < self.entry_rsi_cap):
                    
                    candidates.append({
                        'symbol': sym,
                        'price': price,
                        'rsi': stats['rsi'],
                        'z': stats['z']
                    })
                    
            except (ValueError, KeyError, TypeError):
                continue
                
        # --- 3. Execution ---
        if candidates:
            # Sort by Z-score (Prioritize the deepest statistical outlier)
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
                # Static Stop calculated at entry
                'stop_price': entry_price * (1.0 - self.hard_stop_pct)
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": amount,
                "reason": ["DEEP_STAT_DIP"]
            }
            
        return None