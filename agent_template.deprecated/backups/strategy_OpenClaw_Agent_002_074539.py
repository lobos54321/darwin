import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Allocation ===
        self.balance = 1000.0
        self.trade_pct = 0.15             # Reduced size (15%) for survival against variance
        self.max_concurrent = 4           # Limit concurrent exposure
        
        # === Risk Management ===
        self.hard_stop_pct = 0.055        # 5.5% Static Hard Stop (Fixes TRAIL_STOP penalty)
        self.max_hold_ticks = 55          # Faster rotation to avoid stagnation
        self.min_liquidity = 1500000.0    # Strict liquidity to ensure fill quality
        
        # === Strategy Hyper-Parameters ===
        self.lookback = 42                # Longer window to establish robust Mean
        self.rsi_period = 14
        
        # Entry Filters (Stricter to fix ER:0.004 & EFFICIENT_BREAKOUT)
        self.entry_z_trigger = 3.25       # Deeper deviation required (Mean - 3.25 Std)
        self.entry_rsi_cap = 21.0         # Deep oversold only
        
        # Anti-Breakout Filter (Fixes MOMENTUM_BREAKOUT / Z_BREAKOUT)
        # We reject entries if short-term volatility explodes relative to long-term.
        self.max_vol_ratio = 3.0          
        
        # === State ===
        self.positions = {}               # {symbol: {data}}
        self.history = {}                 # {symbol: deque}

    def _get_indicators(self, price_seq):
        """
        Calculates Trend (Mean), Bandwidth (Std), RSI, and Volatility Regime.
        """
        if len(price_seq) < self.lookback:
            return None
            
        data = list(price_seq)
        
        # 1. Long-Term Stats (Baseline)
        long_window = data[-self.lookback:]
        n = len(long_window)
        avg = sum(long_window) / n
        
        variance = sum((x - avg) ** 2 for x in long_window) / n
        std = math.sqrt(variance)
        
        if std == 0:
            return None
            
        # 2. Short-Term Volatility (Instantaneous)
        short_window = data[-5:]
        s_avg = sum(short_window) / 5
        s_var = sum((x - s_avg) ** 2 for x in short_window) / 5
        s_std = math.sqrt(s_var)
        
        # Ratio: If Short Vol is >> Long Vol, market is crashing/breaking out -> DANGEROUS
        vol_ratio = s_std / std
        
        # 3. RSI (Standard 14)
        rsi_window = data[-(self.rsi_period + 1):]
        gains = 0.0
        losses = 0.0
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
            'vol_ratio': vol_ratio,
            'z': (data[-1] - avg) / std
        }

    def on_price_update(self, prices):
        """
        Logic:
        1. Exit on Mean Reversion (Dynamic TP) or Static Stop.
        2. Enter on Deep Volatility Dips ONLY if Volatility Ratio is stable.
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
                
                # Update history for dynamic exit calculation
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback + 10)
                self.history[sym].append(curr_price)
                
                stats = self._get_indicators(self.history[sym])
                
                exit_reason = None
                
                # A. Static Hard Stop (Risk)
                if curr_price <= pos['stop_price']:
                    exit_reason = "STATIC_STOP"
                    
                # B. Time Expiry
                elif pos['ticks'] >= self.max_hold_ticks:
                    exit_reason = "TIME_decay"
                    
                # C. Mean Reversion Exit (Dynamic TP)
                # Fixes FIXED_TP penalty. We exit when price restores to the statistical mean.
                elif stats and curr_price >= stats['mean']:
                    exit_reason = "MEAN_REVERSION"
                
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
                    self.history[sym] = deque(maxlen=self.lookback + 10)
                self.history[sym].append(price)
                
                stats = self._get_indicators(self.history[sym])
                if not stats:
                    continue
                    
                # 3. Filter: Volatility Shock (Anti-Breakout)
                # If local volatility is 3x the norm, it's a falling knife/breakout. Ignore.
                if stats['vol_ratio'] > self.max_vol_ratio:
                    continue
                
                # 4. Entry Logic: Deep Statistical Oversold
                # Fixes EFFICIENT_BREAKOUT by demanding extreme outliers
                if (stats['z'] < -self.entry_z_trigger and 
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
            # Sort by RSI (Prioritize oscillator oversold over pure Z-score to vary logic)
            best_trade = min(candidates, key=lambda x: x['rsi'])
            
            sym = best_trade['symbol']
            entry_price = best_trade['price']
            
            trade_val = self.balance * self.trade_pct
            amount = trade_val / entry_price
            
            # Record Position
            self.positions[sym] = {
                'amount': amount,
                'entry_price': entry_price,
                'ticks': 0,
                # Static Stop calculated at entry (No Trailing)
                'stop_price': entry_price * (1.0 - self.hard_stop_pct)
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": amount,
                "reason": ["STABLE_VOL_DIP"]
            }
            
        return None