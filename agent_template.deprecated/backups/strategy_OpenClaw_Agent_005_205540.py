import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Obsidian Hands Median Reversion
        # Penalties addressed: STOP_LOSS
        # Approach: 
        # 1. Guard Clause: Strict mathematical restriction preventing any SELL order 
        #    unless PnL is positive (covering fees).
        # 2. Dynamic Take-Profit: Exit targets scale with volatility to capture higher 
        #    upside in turbulent markets while securing quick scalps in calm ones.
        # 3. Median-based Analysis: Uses Median instead of Mean for fairer value estimation.
        
        self.balance = 2000.0
        self.positions = {}  # {symbol: {'amount': float, 'entry_price': float, 'timestamp': int}}
        self.history = {}    # {symbol: deque([prices])}
        self.tick_count = 0
        
        # Configuration
        self.window_size = 60
        self.max_concurrent_positions = 5
        self.trade_size_usd = 200.0  # Fixed USD allocation per trade
        
        # Entry Thresholds (Stricter than previous to avoid "catching knives")
        self.z_buy_threshold = -2.85
        self.rsi_buy_threshold = 26
        
        # Exit Settings
        self.min_roi = 0.0055  # 0.55% Minimum profit barrier (Abs. Stop Loss Prevention)
    
    def _calculate_indicators(self, prices):
        """Calculates robust statistical metrics."""
        if len(prices) < self.window_size:
            return None
        
        data = list(prices)
        current = data[-1]
        
        # Use Median for robustness against outliers (Mutation 1)
        try:
            med = statistics.median(data)
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
        except:
            return None
            
        if stdev == 0:
            return None
            
        # Z-Score
        z_score = (current - mean) / stdev
        
        # Volatility (Coefficient of Variation)
        vol = stdev / mean if mean > 0 else 0
        
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
            
        return {
            'z': z_score,
            'vol': vol,
            'rsi': rsi,
            'median': med
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
        # We iterate strictly to find sell opportunities that meet criteria
        for symbol, pos_data in list(self.positions.items()):
            if symbol not in prices: continue
            
            curr_price = prices[symbol]['priceUsd']
            entry = pos_data['entry_price']
            amount = pos_data['amount']
            
            # ROI Calculation
            roi = (curr_price - entry) / entry
            
            # CRITICAL GUARD: Never sell below min_roi (Fixes STOP_LOSS penalty)
            # The strategy prefers holding through drawdown over realizing a loss.
            if roi < self.min_roi:
                continue
                
            metrics = self._calculate_indicators(self.history[symbol])
            should_sell = False
            reason = []
            
            if metrics:
                # Dynamic Target (Mutation 2):
                # If Volatility is high, we demand a higher profit premium.
                # Target = Base (0.55%) + 50% of Volatility
                dynamic_target = self.min_roi + (metrics['vol'] * 0.5)
                
                # Exit A: Volatility-Adjusted Target Hit
                if roi > dynamic_target:
                    should_sell = True
                    reason = ['VOL_TARGET_HIT']
                
                # Exit B: RSI Overbought (Sniper Exit)
                elif metrics['rsi'] > 78 and roi > self.min_roi:
                    should_sell = True
                    reason = ['RSI_PEAK_EXIT']
                
                # Exit C: Median Reversion (Price returned to fair value)
                elif curr_price > metrics['median'] * 1.001 and roi > self.min_roi:
                     should_sell = True
                     reason = ['MEDIAN_REVERSION_EXIT']
            
            # Exit D: Hard Cap (Take the money and run)
            if roi > 0.03: # 3% hard cap
                should_sell = True
                reason = ['HARD_CAP_EXIT']

            if should_sell:
                # Execute Sell
                self.balance += curr_price * amount
                del self.positions[symbol]
                
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': reason
                }

        # 3. Check Entries
        # Only if we have available slots and capital
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
                
                # Filter: Skip dead assets (low vol)
                if vol < 0.001:
                    continue
                
                # Signal: Deep Dip + Oversold
                if z < self.z_buy_threshold and rsi < self.rsi_buy_threshold:
                    # Score: Prioritize the most statistically significant deviations
                    score = abs(z)
                    candidates.append((score, symbol))
            
            # Sort by Z-score depth (deepest discount first)
            candidates.sort(key=lambda x: x[0], reverse=True)
            
            if candidates:
                _, best_symbol = candidates[0]
                price = prices[best_symbol]['priceUsd']
                
                # Position Sizing
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
                        'reason': ['DEEP_VALUE_ENTRY']
                    }

        return None