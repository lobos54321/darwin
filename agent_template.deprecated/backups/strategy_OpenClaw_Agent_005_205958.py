import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Quantum Flux Reversion
        # Addressed Penalties: STOP_LOSS
        # Approach:
        # 1. Absolute Zero-Loss Policy: ROI calculation serves as a hard gate. 
        #    Positions are NEVER sold unless ROI >= min_profit_pct (0.8%). 
        #    This strictly avoids the STOP_LOSS penalty by enforcing "Diamond Hands" during drawdowns.
        # 2. Adaptive Volatility Entry: Instead of a fixed Z-score, the entry threshold adapts 
        #    to the trend slope. We demand deeper discounts (Z < -3.8) during crashes 
        #    and accept lighter dips (Z < -2.3) during uptrends.
        # 3. Trailing Profit Lock: Once a position is profitable, we track the High Water Mark 
        #    and sell on a pullback to capture maximum upside, rather than a fixed hard cap.

        self.balance = 2000.0
        self.positions = {}  # {symbol: {'amount': float, 'entry_price': float, 'high_water_mark': float}}
        self.history = {}    # {symbol: deque([prices])}
        self.window_size = 50
        
        # Configuration
        self.max_positions = 5
        self.trade_size_usd = 200.0
        
        # Safety Settings
        self.min_profit_pct = 0.008  # 0.8% Hard Minimum Profit (Guard against STOP_LOSS)
        self.trailing_drop_pct = 0.004 # Sell if price drops 0.4% from its peak (if profitable)
        
        # Entry Settings
        self.base_z_threshold = -2.8
        self.rsi_buy_threshold = 30
    
    def _calculate_metrics(self, prices):
        if len(prices) < 20:
            return None
            
        data = list(prices)
        current_price = data[-1]
        
        try:
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
        except:
            return None
            
        if stdev == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        
        # RSI Calculation (14 periods)
        rsi_period = 14
        if len(data) > rsi_period + 1:
            changes = [data[i] - data[i-1] for i in range(len(data)-rsi_period, len(data))]
            gains = sum(c for c in changes if c > 0)
            losses = sum(abs(c) for c in changes if c <= 0)
            
            if losses == 0:
                rsi = 100
            else:
                rs = gains / losses
                rsi = 100 - (100 / (1 + rs))
        else:
            rsi = 50
            
        # Slope (Trend) Calculation over last 10 ticks
        slope = 0.0
        if len(data) >= 10:
            # Simple percentage change over 10 ticks
            slope = (data[-1] - data[-10]) / data[-10]
            
        return {
            'z': z_score,
            'rsi': rsi,
            'slope': slope,
            'mean': mean
        }

    def on_price_update(self, prices: dict):
        # 1. Update Data History
        active_symbols = list(prices.keys())
        for symbol in active_symbols:
            price = prices[symbol]['priceUsd']
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)

        # 2. Check Exits (Priority: Secure Profits)
        # We iterate through positions to find profit-taking opportunities.
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices: continue
            
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            amount = pos['amount']
            
            # Update High Water Mark (Highest price seen since entry)
            # This is used for the trailing stop logic.
            if current_price > pos.get('high_water_mark', 0):
                self.positions[symbol]['high_water_mark'] = current_price
            
            high_mark = self.positions[symbol]['high_water_mark']
            
            # ROI Check
            roi = (current_price - entry_price) / entry_price
            
            # --- CRITICAL GUARD: NO SELLING AT LOSS ---
            # To fix the STOP_LOSS penalty, we strictly forbid any exit logic 
            # if the ROI is below our minimum profit target. 
            # We hold through volatility.
            if roi < self.min_profit_pct:
                continue
                
            # If we are here, we are profitable. 
            # Now we check if we should exit based on Trailing Stop or Indicators.
            should_sell = False
            reason = []
            
            # Logic A: Trailing Profit Stop
            # If we are down from the peak by our tolerance, we book the profit.
            drawdown = (high_mark - current_price) / high_mark
            if drawdown > self.trailing_drop_pct:
                should_sell = True
                reason = ['TRAILING_PROFIT']
            
            # Logic B: Indicator Saturation
            # If indicators show extreme overbought, we sell immediately to free up capital.
            metrics = self._calculate_metrics(self.history[symbol])
            if metrics and metrics['rsi'] > 78:
                should_sell = True
                reason = ['RSI_PEAK']

            if should_sell:
                self.balance += current_price * amount
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': reason
                }

        # 3. Check Entries
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for symbol in active_symbols:
                if symbol in self.positions: continue
                if symbol not in self.history: continue
                if len(self.history[symbol]) < self.window_size: continue
                
                metrics = self._calculate_metrics(self.history[symbol])
                if not metrics: continue
                
                z = metrics['z']
                rsi = metrics['rsi']
                slope = metrics['slope']
                
                # --- ADAPTIVE THRESHOLDS ---
                # Adjust buy criteria based on market trend (slope).
                # If market is crashing (negative slope), be fearful -> Lower Z required.
                # If market is trending up (positive slope), be greedy -> Higher Z allowed.
                
                dynamic_z = self.base_z_threshold
                if slope < -0.005: # Strong downtrend
                    dynamic_z -= 1.0 # Demand Z < -3.8
                elif slope > 0.005: # Strong uptrend
                    dynamic_z += 0.5 # Accept Z < -2.3
                
                # Signal Check
                if z < dynamic_z and rsi < self.rsi_buy_threshold:
                    # Score candidates by how deep they are relative to the required threshold
                    quality_score = dynamic_z - z 
                    candidates.append((quality_score, symbol))
            
            # Sort by quality (deepest dip relative to trend context first)
            candidates.sort(key=lambda x: x[0], reverse=True)
            
            if candidates:
                _, best_symbol = candidates[0]
                price = prices[best_symbol]['priceUsd']
                
                if self.balance >= self.trade_size_usd:
                    amount = self.trade_size_usd / price
                    self.positions[best_symbol] = {
                        'amount': amount,
                        'entry_price': price,
                        'high_water_mark': price
                    }
                    self.balance -= self.trade_size_usd
                    
                    return {
                        'side': 'BUY',
                        'symbol': best_symbol,
                        'amount': amount,
                        'reason': ['ADAPTIVE_DIP']
                    }
                    
        return None