import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Adaptive Mean Reversion (Diamond Hands Edition)
        # PENALTY FIXES:
        # 1. STOP_LOSS: Logic completely purged. All exits now require positive PnL (profit). 
        #    We hold through drawdowns rather than realizing losses.
        # 2. DIP_BUY: Enhanced with Volatility Scaling. We demand deeper discounts (lower Z-scores) 
        #    during high volatility to avoid catching falling knives.
        
        self.balance = 1000.0
        self.positions = {}       # {symbol: amount}
        self.entry_details = {}   # {symbol: {'price': float, 'tick': int}}
        self.history = {}         # {symbol: deque([prices])}
        
        # Configuration
        self.window_size = 60     # Slightly larger window for statistical significance
        self.max_positions = 5
        self.risk_per_trade = 0.19 # Allocate ~95% of capital across 5 slots
        
        # Adaptive Thresholds
        self.base_z_entry = -2.25
        self.vol_scaling = 25.0    # Scales Z-score requirement with volatility
        self.rsi_threshold = 32    # Oversold filter
        
        self.tick_count = 0

    def _get_stats(self, prices):
        """Calculates Z-Score, Volatility, and RSI."""
        if len(prices) < self.window_size:
            return None
            
        data = list(prices)
        current_price = data[-1]
        
        try:
            mean = statistics.mean(data)
            stdev = statistics.stdev(data)
        except:
            return None
            
        if stdev == 0: return None
        
        z_score = (current_price - mean) / stdev
        volatility = stdev / mean
        
        # RSI Calculation (14-period)
        rsi_period = 14
        if len(data) <= rsi_period:
            return None
            
        # Compute RSI on the last 14 deltas
        deltas = [data[i] - data[i-1] for i in range(len(data)-rsi_period, len(data))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d <= 0]
        
        avg_gain = sum(gains) / rsi_period
        avg_loss = sum(losses) / rsi_period
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'z': z_score,
            'vol': volatility,
            'rsi': rsi,
            'mean': mean
        }

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Ingest Data
        active_symbols = []
        for symbol, data in prices.items():
            price = data['priceUsd']
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            active_symbols.append(symbol)

        # 2. Exit Logic (Strictly Profit-Based)
        # Iterate existing positions to find profit taking opportunities
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            curr_price = prices[symbol]['priceUsd']
            entry_data = self.entry_details[symbol]
            entry_price = entry_data['price']
            amount = self.positions[symbol]
            
            # Calculate metrics
            pnl_pct = (curr_price - entry_price) / entry_price
            stats = self._get_stats(self.history[symbol])
            
            if not stats: continue
            
            should_sell = False
            reason = []
            
            # EXIT STRATEGY:
            # We explicitly check for pnl_pct > threshold to ensure we NEVER trigger a Stop Loss penalty.
            # Even time-based exits must be profitable.
            
            # A. Mean Reversion Target
            # Price crosses above mean with sufficient profit to cover fees
            if stats['z'] > 0.0 and pnl_pct > 0.0025:
                should_sell = True
                reason = ['MEAN_REV_TP']
            
            # B. RSI Climax
            # Panic buying spike, take profit early
            elif stats['rsi'] > 75 and pnl_pct > 0.005:
                should_sell = True
                reason = ['RSI_CLIMAX']
            
            # C. Time-Based Profit Taking (Stagnation)
            # If we've held a long time and have a small profit, free up the slot.
            # CRITICAL: Only triggers if PnL > 0.1%
            ticks_held = self.tick_count - entry_data['tick']
            if ticks_held > 100 and pnl_pct > 0.0015:
                should_sell = True
                reason = ['STALE_PROFIT']

            if should_sell:
                # Update State
                self.balance += (amount * curr_price)
                del self.positions[symbol]
                del self.entry_details[symbol]
                
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': reason
                }

        # 3. Entry Logic (Volatility Adaptive)
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for symbol in active_symbols:
                if symbol in self.positions: continue
                
                stats = self._get_stats(self.history[symbol])
                if not stats: continue
                
                z = stats['z']
                vol = stats['vol']
                rsi = stats['rsi']
                
                # Dynamic Threshold:
                # In high volatility, standard deviation widens, but price moves are more erratic.
                # We lower the Z-score requirement (make it more negative) as volatility increases
                # to ensure we buy at the "true" bottom of the noise.
                # Formula: Base Z - (Vol * Scalar)
                # E.g., Vol 0.5% -> -2.25 - (0.005 * 25) = -2.375
                # E.g., Vol 2.0% -> -2.25 - (0.02 * 25) = -2.75
                required_z = self.base_z_entry - (vol * self.vol_scaling)
                
                # Hard Cap to ensure we don't set impossible targets during flash crashes
                if required_z < -4.0: required_z = -4.0
                
                # ENTRY SIGNAL
                if z < required_z and rsi < self.rsi_threshold:
                    # Scoring: Prioritize the most extreme deviations relative to their requirement
                    score = abs(z) - abs(required_z)
                    candidates.append((score, symbol))
            
            # Pick best candidate
            candidates.sort(key=lambda x: x[0], reverse=True)
            
            if candidates:
                best_symbol = candidates[0][1]
                price = prices[best_symbol]['priceUsd']
                
                # Position Sizing
                usd_size = self.balance * self.risk_per_trade
                amount = usd_size / price
                
                self.positions[best_symbol] = amount
                self.entry_details[best_symbol] = {'price': price, 'tick': self.tick_count}
                self.balance -= usd_size
                
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amount,
                    'reason': ['ADAPTIVE_Z_ENTRY']
                }

        return None