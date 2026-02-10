import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Trend-Adaptive Linear Regression Reversion
        
        Fixes for Penalties (LR_RESIDUAL, Z:-3.93):
        1. REPLACED SMA Mean with Linear Regression Trend Line.
           - The previous SMA-based Z-score failed during strong trends (residuals exploded).
           - We now calculate Z-score based on deviation from the *Trend Line* (Linear Regression).
           - This adapts to market direction, ensuring we buy deviations from the trend, not just 'low' prices.
           
        2. STRICTER ENTRY GATES:
           - Z-Trigger lowered to -3.6 (was -3.2).
           - RSI Trigger lowered to 22 (was 24).
           - Added Micro-Reversal Check: strictly require price > previous_tick. 
             We never catch a falling knife; we wait for the first uptick to confirm support.
             
        3. LIQUIDITY:
           - Increased min_liquidity to 8M to avoid slippage/whipsaws in thin markets.
        """
        self.window_size = 50
        self.min_liquidity = 8000000.0
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # Entry Thresholds (Significantly Stricter)
        self.entry_z_trigger = -3.6
        self.entry_rsi_trigger = 22
        
        # Exit Thresholds
        self.exit_z_target = 0.0      # Exit exactly when price touches the Trend Line
        self.stop_loss_pct = 0.06     # Tighten stop to 6%
        self.max_hold_ticks = 40      # Faster rotation to free up capital
        
        # State
        self.history = {} 
        self.positions = {} 
        self.tick_count = 0

    def calculate_indicators(self, symbol, current_price):
        if symbol not in self.history or len(self.history[symbol]) < self.window_size:
            return None
            
        prices_list = list(self.history[symbol])
        n = len(prices_list)
        
        # 1. Linear Regression (Trend) Analysis
        # We fit y = mx + c to the price history
        x = list(range(n))
        y = prices_list
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(i*j for i, j in zip(x, y))
        sum_xx = sum(i*i for i in x)
        
        denom = (n * sum_xx - sum_x ** 2)
        if denom == 0:
            return None
            
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate Residuals (Actual - Predicted)
        # Predicted line values
        predicted = [slope * i + intercept for i in x]
        residuals = [y[i] - predicted[i] for i in range(n)]
        
        try:
            res_stdev = statistics.stdev(residuals)
        except:
            return None
            
        if res_stdev == 0:
            return None
            
        # Z-score based on deviation from TREND, not MEAN
        current_res = residuals[-1]
        z_score = current_res / res_stdev
        
        # 2. RSI (14 period)
        rsi = 50
        period = 14
        if n > period:
            changes = [prices_list[i] - prices_list[i-1] for i in range(1, n)]
            recent_changes = changes[-period:]
            
            gains = [c for c in recent_changes if c > 0]
            losses = [-c for c in recent_changes if c < 0]
            
            if not losses:
                rsi = 100
            elif not gains:
                rsi = 0
            else:
                avg_gain = sum(gains) / period
                avg_loss = sum(losses) / period
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                
        return {
            'z': z_score,
            'rsi': rsi,
            'slope': slope
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Update History & Filter Candidates
        active_candidates = []
        
        for symbol, data in prices.items():
            # Stricter liquidity filter
            if data['liquidity'] < self.min_liquidity:
                continue
                
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(data['priceUsd'])
            
            if len(self.history[symbol]) == self.window_size:
                active_candidates.append(symbol)
                
        # 2. Manage Exits
        # Iterate over a copy of keys to allow deletion
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            
            indicators = self.calculate_indicators(symbol, current_price)
            
            # ROI Check
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            
            action = None
            reason = None
            
            # Hard Stop Loss
            if roi < -self.stop_loss_pct:
                action = 'SELL'
                reason = 'STOP_LOSS'
            
            # Timeout
            elif (self.tick_count - pos['entry_tick']) > self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIMEOUT'
            
            # Trend Reversion Exit
            elif indicators and indicators['z'] >= self.exit_z_target:
                action = 'SELL'
                reason = 'TREND_REVERTED'
                
            if action == 'SELL':
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0,
                    'reason': [reason]
                }

        # 3. Manage Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        potential_buys = []
        
        for symbol in active_candidates:
            if symbol in self.positions:
                continue
                
            current_price = prices[symbol]['priceUsd']
            stats = self.calculate_indicators(symbol, current_price)
            
            if not stats:
                continue
                
            # Entry Logic
            # Condition 1: Price is significantly below the Trend Line (Linear Regression)
            if stats['z'] < self.entry_z_trigger:
                
                # Condition 2: Deep Oversold RSI
                if stats['rsi'] < self.entry_rsi_trigger:
                    
                    # Condition 3: Micro-Reversal Check (Anti-Falling Knife)
                    # We strictly require the current price to be higher than the previous tick.
                    # This prevents buying a candle that is still actively crashing.
                    prev_price = self.history[symbol][-2]
                    if current_price > prev_price:
                        
                        potential_buys.append({
                            'symbol': symbol,
                            'z': stats['z'],
                            'price': current_price
                        })
        
        # Sort by lowest Z-score (Deepest Value relative to Trend)
        potential_buys.sort(key=lambda x: x['z'])
        
        if potential_buys:
            target = potential_buys[0]
            amount = self.trade_size_usd / target['price']
            
            self.positions[target['symbol']] = {
                'entry_price': target['price'],
                'entry_tick': self.tick_count,
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': target['symbol'],
                'amount': amount,
                'reason': ['LINREG_DIP', 'RSI_CONFIRM', 'MICRO_REVERSAL']
            }
            
        return None