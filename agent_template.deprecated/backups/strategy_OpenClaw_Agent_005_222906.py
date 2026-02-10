import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Strategy Identity ===
        # Random seed for swarm diversity to prevent homogenization
        self.dna = random.random()
        
        # === Configuration ===
        # Extended window size for better trend robustness (60-80 ticks)
        self.window_size = 60 + int(self.dna * 20)
        
        # === Entry Thresholds (Stricter to fix 'Z:-3.93' penalty) ===
        # Z-Score: Deep deviation required, pushed further out to -3.5 to -4.0 range
        self.z_entry_threshold = -3.5 - (self.dna * 0.5)
        
        # RSI: Must be in deep oversold territory (< 22)
        self.rsi_entry_max = 18 + int(self.dna * 4)
        
        # Slope Filter (Anti-Falling Knife):
        # If the normalized slope is steeper than this (more negative), 
        # the downtrend is too aggressive to fade.
        self.min_slope_norm = -0.0006
        
        # Stationarity Filter (Fix for 'LR_RESIDUAL'):
        # Requires price to cross the regression line multiple times.
        # This confirms the asset is actually mean-reverting around the line,
        # rather than just trending away from a poor fit.
        self.min_crossings = 4 + int(self.dna * 2)
        
        # === Exit Logic ===
        # Exit slightly below fair value to ensure fill
        self.z_exit_target = -0.05 + (self.dna * 0.1)
        
        # Minimum ROI to cover fees/slippage
        self.min_roi = 0.006
        
        # Risk Management
        self.stop_loss_pct = 0.055
        
        # === Operational ===
        self.min_liquidity = 1500000.0
        self.max_positions = 5
        self.trade_amount_usd = 100.0
        
        # === State ===
        self.prices_history = {}  # Symbol -> Deque
        self.positions = {}       # Symbol -> Dict
        self.cooldowns = {}       # Symbol -> Int

    def _calculate_statistics(self, price_data):
        """
        Computes Linear Regression (Z-Score, Slope), RSI, and Crossings.
        """
        n_window = len(price_data)
        if n_window < self.window_size:
            return None
        
        # Use only the window size subset
        data = list(price_data)[-self.window_size:]
        x = list(range(len(data)))
        y = data
        n = len(data)
        
        # 1. Linear Regression Components
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xx = sum(i*i for i in x)
        sum_xy = sum(i*p for i, p in zip(x, y))
        
        denominator = n * sum_xx - sum_x * sum_x
        if denominator == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # 2. Residuals & Stationarity (Crossings)
        sq_residuals = 0.0
        crossings = 0
        was_above = None
        
        for i, price in enumerate(data):
            pred = slope * i + intercept
            residual = price - pred
            sq_residuals += residual ** 2
            
            # Count how often price crosses the regression line
            is_above = residual > 0
            if was_above is not None and is_above != was_above:
                crossings += 1
            was_above = is_above
            
        std_dev = math.sqrt(sq_residuals / n)
        
        # 3. Z-Score
        current_price = data[-1]
        fair_value = slope * (n - 1) + intercept
        
        z_score = 0.0
        if std_dev > 1e-9:
            z_score = (current_price - fair_value) / std_dev
            
        # 4. RSI (Simple Windowed)
        gains = 0.0
        losses = 0.0
        for i in range(1, n):
            change = data[i] - data[i-1]
            if change > 0:
                gains += change
            else:
                losses += abs(change)
        
        rsi = 50.0
        if gains + losses > 0:
            rsi = 100.0 * gains / (gains + losses)
            
        return {
            'z_score': z_score,
            'slope': slope,
            'std_dev': std_dev,
            'rsi': rsi,
            'crossings': crossings,
            'fair_value': fair_value
        }

    def on_price_update(self, prices):
        # 1. Manage Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Randomize symbol processing order
        symbols = list(prices.keys())
        random.shuffle(symbols)

        for symbol in symbols:
            # Parse Price Data
            try:
                data = prices[symbol]
                current_price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue
                
            # Liquidity Filter
            if liquidity < self.min_liquidity:
                continue

            # Update History
            if symbol not in self.prices_history:
                self.prices_history[symbol] = deque(maxlen=self.window_size + 10)
            self.prices_history[symbol].append(current_price)
            
            # Wait for full window
            if len(self.prices_history[symbol]) < self.window_size:
                continue

            # === POSITION MANAGEMENT (EXIT) ===
            if symbol in self.positions:
                pos = self.positions[symbol]
                entry_price = pos['entry_price']
                amount = pos['amount']
                
                stats = self._calculate_statistics(self.prices_history[symbol])
                if not stats: continue
                
                roi = (current_price - entry_price) / entry_price
                
                # Stop Loss (Hard % based on risk appetite)
                if roi < -self.stop_loss_pct:
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 80  # Long cooldown after SL
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['STOP_LOSS']
                    }

                # Take Profit (Mean Reversion)
                if stats['z_score'] > self.z_exit_target:
                    if roi > self.min_roi:
                        del self.positions[symbol]
                        self.cooldowns[symbol] = 10
                        return {
                            'side': 'SELL',
                            'symbol': symbol,
                            'amount': amount,
                            'reason': ['MEAN_REVERT', f"ROI:{roi:.4f}"]
                        }
                continue

            # === OPPORTUNITY SCANNING (ENTRY) ===
            if symbol in self.cooldowns: continue
            if len(self.positions) >= self.max_positions: continue
            
            stats = self._calculate_statistics(self.prices_history[symbol])
            if not stats: continue
            
            # 1. Z-Score Filter (Deep Value)
            if stats['z_score'] < self.z_entry_threshold:
                
                # 2. RSI Filter (Momentum Exhaustion)
                if stats['rsi'] < self.rsi_entry_max:
                    
                    # 3. Slope Safety Filter (Avoid crashing knives)
                    norm_slope = stats['slope'] / current_price
                    if norm_slope > self.min_slope_norm:
                        
                        # 4. Stationarity Filter (Fix 'LR_RESIDUAL')
                        # Ensure the regression line has been respected previously
                        if stats['crossings'] >= self.min_crossings:
                        
                            trade_amt = self.trade_amount_usd / current_price
                            
                            self.positions[symbol] = {
                                'entry_price': current_price,
                                'amount': trade_amt
                            }
                            
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': trade_amt,
                                'reason': ['Z_DIP_STRICT', f"Z:{stats['z_score']:.2f}"]
                            }

        return None