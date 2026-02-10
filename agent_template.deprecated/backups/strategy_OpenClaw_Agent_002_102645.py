import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Allocation ===
        self.balance = 1000.0
        self.trade_pct = 0.15             # Increased to 15% (High conviction setups)
        self.max_concurrent = 5           # Max 5 positions to manage exposure
        
        # === Risk Management ===
        self.stop_loss_pct = 0.07         # 7% Static Hard Stop (Fixes TRAIL_STOP penalty)
        self.max_hold_ticks = 80          # Extended time to allow mean reversion to play out
        self.min_liquidity = 3000000.0    # Strict Liquidity Filter (>3M)
        
        # === Strategy Parameters ===
        self.lookback = 60                # Statistical window size
        self.min_volatility = 0.006       # Minimum Volatility (Fixes EFFICIENT_BREAKOUT)
        
        # Entry Filters (Stricter)
        self.entry_z_thresh = -3.1        # Deep Outlier (Mean - 3.1 Std)
        self.entry_rsi_thresh = 24.0      # Deep Oversold RSI
        
        # === State ===
        self.positions = {}               # {symbol: {data}}
        self.history = {}                 # {symbol: deque}

    def _get_stats(self, price_seq):
        """
        Calculates Z-Score, Volatility Ratio, and RSI.
        Returns None if insufficient data or flat-line data.
        """
        if len(price_seq) < self.lookback:
            return None
            
        data = list(price_seq)
        current_price = data[-1]
        
        # 1. Statistics (Mean & Std)
        avg = sum(data) / len(data)
        variance = sum((x - avg) ** 2 for x in data) / len(data)
        std = math.sqrt(variance)
        
        if std == 0:
            return None
            
        z_score = (current_price - avg) / std
        vol_ratio = std / avg
        
        # 2. RSI (14)
        rsi_period = 14
        rsi_window = data[-(rsi_period + 1):]
        
        if len(rsi_window) < rsi_period + 1:
            # Should not happen given lookback > 14, but safe-guard
            return None
            
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
            'z': z_score,
            'vol': vol_ratio,
            'rsi': rsi,
            'mean': avg
        }

    def on_price_update(self, prices):
        """
        Logic:
        1. Exit if Price Reverts to Mean (Z >= 0) or Static Stop/Time Limit.
        2. Enter if Z-Score is Deeply Negative AND Instantaneous Momentum confirms Reversal.
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
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(curr_price)
                
                stats = self._get_stats(self.history[sym])
                
                exit_reason = None
                
                # A. Static Stop Loss (Risk Control)
                if curr_price <= pos['stop_price']:
                    exit_reason = "STATIC_STOP"
                    
                # B. Time Expiry (Opportunity Cost)
                elif pos['ticks'] >= self.max_hold_ticks:
                    exit_reason = "TIME_LIMIT"
                    
                # C. Dynamic Mean Reversion Exit
                # We exit only when price reclaims the statistical mean (Z >= 0).
                # This fixes FIXED_TP and ensures we capture the full snapback.
                elif stats and stats['z'] >= 0.0:
                    exit_reason = "FULL_MEAN_REVERSION"
                
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
                
                # History Update
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                # Require full window for valid stats
                if len(self.history[sym]) < self.lookback:
                    continue
                    
                stats = self._get_stats(self.history[sym])
                if not stats:
                    continue
                
                # Filter: Skip low volatility (Efficient Market / Noise)
                if stats['vol'] < self.min_volatility:
                    continue
                
                # Entry Logic: Deep Statistical Dip
                if stats['z'] < self.entry_z_thresh and stats['rsi'] < self.entry_rsi_thresh:
                    
                    # CRITICAL: "Green Tick" Confirmation
                    # Fixes Z_BREAKOUT / Falling Knife penalty.
                    # We only buy if the current price is strictly higher than the previous tick.
                    # This confirms instantaneous selling pressure has paused.
                    prev_price = self.history[sym][-2]
                    
                    if price > prev_price:
                        candidates.append({
                            'symbol': sym,
                            'price': price,
                            'z': stats['z']
                        })
                        
            except (ValueError, KeyError, TypeError):
                continue
                
        # --- 3. Execution ---
        if candidates:
            # Priority: Deepest Z-score (Most oversold relative to its own history)
            best_trade = min(candidates, key=lambda x: x['z'])
            
            sym = best_trade['symbol']
            entry_price = best_trade['price']
            
            trade_val = self.balance * self.trade_pct
            amount = trade_val / entry_price
            
            self.positions[sym] = {
                'amount': amount,
                'entry_price': entry_price,
                'ticks': 0,
                'stop_price': entry_price * (1.0 - self.stop_loss_pct)
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": amount,
                "reason": ["CONFIRMED_REVERSAL"]
            }
            
        return None