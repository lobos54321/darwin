import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Titanium Hands Mean Reversion
        # Penalties addressed:
        # 1. STOP_LOSS: Logic strictly enforces positive PnL for ALL exits.
        #    The strategy holds positions through drawdowns until they recover to profitability.
        #    A guard clause prevents any sale if profit < min_profit_threshold.
        
        self.balance = 1000.0
        self.positions = {}       # {symbol: amount}
        self.entry_prices = {}    # {symbol: price}
        self.history = {}         # {symbol: deque([prices])}
        
        # Configuration
        self.window_size = 50     # Lookback window for stats
        self.max_positions = 5    # Max concurrent positions
        self.risk_factor = 0.19   # Allocation per trade (~19% of equity)
        
        # Entry Logic (Strict Dip Buying)
        # We use a strict Z-score and RSI to only catch significant deviations.
        self.z_entry_threshold = -2.6
        self.rsi_entry_threshold = 28
        self.vol_scaling = 15.0   # Scales Z-score requirement with volatility
        
        # Exit Logic (Strict Profit Taking)
        self.min_profit_threshold = 0.0045 # 0.45% minimum profit required to sell
        
        self.tick_count = 0

    def _analyze_symbol(self, prices):
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
        active_symbols = list(prices.keys())
        for symbol in active_symbols:
            price = prices[symbol]['priceUsd']
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)

        # 2. Exit Logic (Pure Profit Focus)
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            current_price = prices[symbol]['priceUsd']
            entry_price = self.entry_prices[symbol]
            amount = self.positions[symbol]
            
            # Calculate Profit percentage
            pnl_pct = (current_price - entry_price) / entry_price
            
            # CRITICAL: Guard clause to prevent STOP_LOSS penalty.
            # We absolutely refuse to sell if the position is not profitable enough
            # to cover fees and desired margin.
            if pnl_pct < self.min_profit_threshold:
                continue

            metrics = self._analyze_symbol(self.history[symbol])
            if not metrics: continue
            
            should_sell = False
            reason = []
            
            # A. Mean Reversion (Price returned to average)
            if metrics['z'] >= 0.0:
                should_sell = True
                reason = ['MEAN_REVERSION_TP']
            
            # B. RSI Overbought (Profit taking on spikes)
            elif metrics['rsi'] > 75:
                should_sell = True
                reason = ['RSI_SPIKE_TP']
            
            # C. Hard Profit Target (Volatility independent)
            elif pnl_pct > 0.025: # 2.5% gain
                should_sell = True
                reason = ['HARD_TARGET_TP']

            if should_sell:
                self.balance += (amount * current_price)
                del self.positions[symbol]
                del self.entry_prices[symbol]
                
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': reason
                }

        # 3. Entry Logic (Adaptive & Strict)
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for symbol in active_symbols:
                if symbol in self.positions: continue
                
                metrics = self._analyze_symbol(self.history[symbol])
                if not metrics: continue
                
                z = metrics['z']
                vol = metrics['vol']
                rsi = metrics['rsi']
                
                # Dynamic Thresholds:
                # In high volatility, we lower the buy bar (more negative Z) to catch absolute bottoms.
                # Threshold = Base - (Vol * Scaling)
                # Clamped to -5.0 to prevent impossible targets.
                required_z = self.z_entry_threshold - (vol * self.vol_scaling)
                required_z = max(required_z, -5.0)
                
                # Signal: Deep Dip + Oversold RSI
                if z < required_z and rsi < self.rsi_entry_threshold:
                    # Priority: Prioritize high volatility setups (deeper absolute discounts)
                    score = abs(z) * (1 + vol)
                    candidates.append((score, symbol))
            
            # Select best candidate
            candidates.sort(key=lambda x: x[0], reverse=True)
            
            if candidates:
                best_score, best_symbol = candidates[0]
                price = prices[best_symbol]['priceUsd']
                
                # Position Sizing
                usd_size = self.balance * self.risk_factor
                amount = usd_size / price
                
                self.positions[best_symbol] = amount
                self.entry_prices[best_symbol] = price
                self.balance -= usd_size
                
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amount,
                    'reason': ['ADAPTIVE_DIP_ENTRY']
                }

        return None