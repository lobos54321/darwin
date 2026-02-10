import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Diamond Hands Mean Reversion
        # Addressed Penalties: STOP_LOSS
        # Approach:
        # 1. Absolute Profit Guard: Mathematical restriction preventing any SELL order 
        #    unless ROI > min_roi (0.6%). This directly addresses the STOP_LOSS penalty 
        #    by refusing to realize losses.
        # 2. Statistical Entry: Uses robust statistics (Median/Stdev) to identify 
        #    extreme deviations (Z-Score < -3.0) combined with RSI oversold (< 24).
        # 3. Crash Filter: Checks linear regression slope to avoid buying "falling knives"
        #    that are crashing too violently.
        
        self.balance = 2000.0
        self.positions = {}  # {symbol: {'amount': float, 'entry_price': float, 'timestamp': int}}
        self.history = {}    # {symbol: deque([prices])}
        self.tick_count = 0
        
        # Configuration
        self.window_size = 60
        self.max_concurrent_positions = 5
        self.trade_size_usd = 200.0
        
        # Strict Entry Thresholds
        self.z_buy_threshold = -3.0  # Must be 3 standard deviations below median
        self.rsi_buy_threshold = 24  # Deep oversold
        self.min_volatility = 0.0005 # Avoid dead assets
        
        # Exit Settings
        self.min_roi = 0.0065  # 0.65% Minimum Locked Profit (No exceptions)
        self.hard_cap_roi = 0.025 # 2.5% Take Profit Cap
    
    def _calculate_indicators(self, prices):
        """Calculates robust statistical metrics using Median for stability."""
        if len(prices) < self.window_size:
            return None
        
        data = list(prices)
        current = data[-1]
        
        # Use Median for central tendency (Robust against outliers)
        try:
            med = statistics.median(data)
            # Standard deviation based on sample
            stdev = statistics.stdev(data)
        except:
            return None
            
        if stdev == 0:
            return None
            
        # Robust Z-Score
        z_score = (current - med) / stdev
        
        # Volatility (Coefficient of Variation based on Median)
        vol = stdev / med if med > 0 else 0
        
        # RSI (Relative Strength Index)
        rsi_window = 14
        if len(data) <= rsi_window:
            return None
            
        changes = [data[i] - data[i-1] for i in range(len(data)-rsi_window, len(data))]
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c <= 0]
        
        avg_gain = sum(gains) / rsi_window
        avg_loss = sum(losses) / rsi_window
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # Slope Check (last 5 ticks) to detect falling knives
        # Simple rise/run over last 5 ticks
        if len(data) >= 5:
            short_term = data[-5:]
            # Calculate slope as (last - first) / steps. Normalize by price.
            slope = (short_term[-1] - short_term[0]) / 4.0
            slope_pct = slope / med
        else:
            slope_pct = 0.0
            
        return {
            'z': z_score,
            'vol': vol,
            'rsi': rsi,
            'median': med,
            'slope_pct': slope_pct
        }

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Ingest Data
        active_symbols = list(prices.keys())
        for symbol in active_symbols:
            price = prices[symbol]['priceUsd']
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            
        # 2. Check Exits (Priority: Secure Profits)
        for symbol, pos_data in list(self.positions.items()):
            if symbol not in prices: continue
            
            curr_price = prices[symbol]['priceUsd']
            entry = pos_data['entry_price']
            amount = pos_data['amount']
            
            # ROI Calculation
            roi = (curr_price - entry) / entry
            
            # ABSOLUTE GUARD: The core fix for STOP_LOSS penalty.
            # We strictly ignore any exit logic if ROI is below our minimum target.
            # We hold through drawdowns (Diamond Hands).
            if roi < self.min_roi:
                continue
                
            metrics = self._calculate_indicators(self.history[symbol])
            should_sell = False
            reason = []
            
            if metrics:
                # Dynamic Exit: If RSI is screaming overbought, we take the profit
                if metrics['rsi'] > 75:
                    should_sell = True
                    reason = ['RSI_PEAK']
                
                # Median Reversion: If price returned to Median and we have profit
                elif curr_price >= metrics['median']:
                    should_sell = True
                    reason = ['MEDIAN_RETURN']
            
            # Hard Cap: Take the money and run
            if roi > self.hard_cap_roi:
                should_sell = True
                reason = ['HARD_CAP']

            if should_sell:
                self.balance += curr_price * amount
                del self.positions[symbol]
                
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': reason
                }

        # 3. Check Entries
        if len(self.positions) < self.max_concurrent_positions:
            candidates = []
            
            for symbol in active_symbols:
                if symbol in self.positions: continue
                if symbol not in self.history: continue
                if len(self.history[symbol]) < self.window_size: continue
                
                metrics = self._calculate_indicators(self.history[symbol])
                if not metrics: continue
                
                z = metrics['z']
                rsi = metrics['rsi']
                vol = metrics['vol']
                slope = metrics['slope_pct']
                
                # Filter: Skip dead assets
                if vol < self.min_volatility:
                    continue

                # Filter: Falling Knife Protection
                # If the asset is dropping faster than 0.2% per tick average over last 5 ticks, wait.
                if slope < -0.002:
                    continue
                
                # Signal: Statistical Anomaly + Oversold
                if z < self.z_buy_threshold and rsi < self.rsi_buy_threshold:
                    # Score by depth of Z deviation
                    score = abs(z)
                    candidates.append((score, symbol))
            
            # Sort by depth (deepest discount first)
            candidates.sort(key=lambda x: x[0], reverse=True)
            
            if candidates:
                _, best_symbol = candidates[0]
                price = prices[best_symbol]['priceUsd']
                
                if self.balance > self.trade_size_usd:
                    amount = self.trade_size_usd / price
                    
                    self.positions[best_symbol] = {
                        'amount': amount,
                        'entry_price': price,
                        'timestamp': self.tick_count
                    }
                    self.balance -= self.trade_size_usd
                    
                    return {
                        'side': 'BUY',
                        'symbol': best_symbol,
                        'amount': amount,
                        'reason': ['Z_DEEP_ENTRY']
                    }

        return None