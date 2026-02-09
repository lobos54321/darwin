import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Strategy Identity ===
        # Random seed to create slight variations in parameters
        # Prevents swarm homogenization and improves aggregate robustness
        self.dna = random.random()
        
        # === Configuration ===
        # Window size: 50 - 80 ticks.
        self.window_size = 50 + int(self.dna * 30)
        
        # === Entry Thresholds (Stricter for 'ER:0.004') ===
        # Z-Score: Only buy extremely deep deviations (3.2 to 3.8 sigma)
        self.z_entry_threshold = -3.2 - (self.dna * 0.6)
        
        # RSI: Must be oversold to confirm exhaustion (< 25)
        self.rsi_entry_max = 22 + int(self.dna * 6)
        
        # Slope Filter (Anti-Falling Knife for 'EFFICIENT_BREAKOUT'):
        # Normalize slope (price change per tick / price).
        # If trend is crashing too steeply (slope < threshold), we stand aside.
        self.min_slope_norm = -0.0004
        
        # === Exit Logic (Dynamic for 'FIXED_TP') ===
        # Exit when price reverts to Fair Value (Z ~ 0)
        self.z_exit_target = -0.1 + (self.dna * 0.2)
        
        # Minimum Edge: Only take profit if ROI covers friction/fees
        self.min_roi = 0.006
        
        # Risk Management: Dynamic Stop Loss based on volatility
        self.stop_loss_sigma = 4.5
        
        # === Operational ===
        self.min_liquidity = 1200000.0  # Filter out low liquidity noise
        self.max_positions = 5
        self.trade_amount_usd = 100.0
        
        # === State ===
        self.prices_history = {}  # Symbol -> Deque
        self.positions = {}       # Symbol -> Dict
        self.cooldowns = {}       # Symbol -> Int

    def _calculate_statistics(self, price_data):
        """
        Computes Linear Regression (Z-Score, Slope) and RSI.
        """
        n = len(price_data)
        if n < self.window_size:
            return None
        
        # Use a subset of the history corresponding to the window size
        data = list(price_data)[-self.window_size:]
        n_window = len(data)
        
        # 1. Linear Regression
        sum_x = 0
        sum_y = 0
        sum_xy = 0
        sum_xx = 0
        
        for i, price in enumerate(data):
            sum_x += i
            sum_y += price
            sum_xx += i * i
            sum_xy += i * price
            
        denominator = n_window * sum_xx - sum_x * sum_x
        if denominator == 0:
            return None
            
        slope = (n_window * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n_window
        
        # 2. Standard Deviation of Residuals
        sq_residuals = 0.0
        for i, price in enumerate(data):
            pred = slope * i + intercept
            sq_residuals += (price - pred) ** 2
            
        std_dev = math.sqrt(sq_residuals / n_window)
        
        # 3. Z-Score (Current Deviation)
        current_price = data[-1]
        # Fair value at the current tick (last index)
        fair_value = slope * (n_window - 1) + intercept
        
        z_score = 0.0
        if std_dev > 1e-9:
            z_score = (current_price - fair_value) / std_dev
            
        # 4. RSI (Relative Strength Index)
        gains = 0.0
        losses = 0.0
        for i in range(1, n_window):
            change = data[i] - data[i-1]
            if change > 0:
                gains += change
            else:
                losses += abs(change)
        
        rsi = 50.0
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'z_score': z_score,
            'slope': slope,
            'std_dev': std_dev,
            'rsi': rsi,
            'fair_value': fair_value
        }

    def on_price_update(self, prices):
        # 1. Manage Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Process Symbols (Random Order to avoid sequence bias)
        symbols = list(prices.keys())
        random.shuffle(symbols)

        for symbol in symbols:
            # Parse Price Data Safely
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
            
            # Ensure enough data
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
                
                # Dynamic Stop Loss (Volatility Based)
                # If price moves > 4.5 sigmas against us from entry expectation
                stop_threshold = -self.stop_loss_sigma * (stats['std_dev'] / entry_price)
                if roi < stop_threshold or roi < -0.05: # Hard cap at 5%
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 50
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['STOP_LOSS']
                    }

                # Dynamic Take Profit (Mean Reversion)
                # Fix 'FIXED_TP': Exit when Z-score normalizes, not at arbitrary %
                if stats['z_score'] > self.z_exit_target:
                    # Ensure minimal profitability to cover spread
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
                    
                    # 3. Slope Safety Filter (Fix 'EFFICIENT_BREAKOUT')
                    # Normalize slope: $/tick -> %/tick
                    norm_slope = stats['slope'] / current_price
                    
                    # If the downward slope is shallower than our limit, it's safe.
                    # If it's steeper (more negative) than limit, it's a crash.
                    if norm_slope > self.min_slope_norm:
                        
                        trade_amt = self.trade_amount_usd / current_price
                        
                        self.positions[symbol] = {
                            'entry_price': current_price,
                            'amount': trade_amt
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': trade_amt,
                            'reason': ['Z_DEEP', f"Z:{stats['z_score']:.2f}"]
                        }

        return None