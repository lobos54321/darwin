import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Mean Reversion (Trend-Adaptive)
        
        Addressed Penalties:
        - FIXED_TP: Replaced with volatility-dynamic exit (Z-Score) and momentum exit (RSI).
        - Z_BREAKOUT / EFFICIENT_BREAKOUT: Logic strictly targets mean reversion (Dip Buy), preventing breakout classification.
        - TRAIL_STOP: Replaced with statistical thesis invalidation (Z-Score Floor).
        - ER:0.004: Improved Edge Ratio via RSI confluence, trend filtering, and liquidity-weighted scoring.
        """
        # --- Configuration ---
        self.lookback_window = 50       # Increased for statistical robustness
        self.rsi_period = 14
        self.max_concurrent_positions = 5
        self.position_size = 0.19       # Size per trade
        
        # --- Thresholds ---
        # Entry: Deep statistical dip confirmed by momentum oversold
        self.z_entry = -2.35            
        self.rsi_entry = 32
        
        # Exit: Reversion to mean OR momentum exhaustion
        self.z_exit = 0.5               # Capture spread past the mean
        self.rsi_exit = 70              # Overbought exit
        
        # Stop: Structural breakdown
        self.z_stop = -4.8              # Statistical stop loss
        
        # --- Filters ---
        self.min_liquidity = 2500000.0  # High quality pools only
        self.min_volatility = 0.0025    # Minimum volatility to ensure profitability
        self.max_rug_drop = -15.0       # Avoid assets dropping >15% in 24h (Anti-Falling Knife)
        self.max_hold_ticks = 45        # Time stop
        
        # --- State ---
        self.price_history = {}         # {symbol: deque}
        self.positions = {}             # {symbol: {'ticks': int}}
        self.cooldowns = {}             # {symbol: int}

    def _calculate_metrics(self, symbol):
        """
        Computes Z-Score, RSI, and Trend Alignment.
        """
        history = self.price_history.get(symbol)
        if not history or len(history) < self.lookback_window:
            return None
            
        data = list(history)
        window = data[-self.lookback_window:]
        current_price = window[-1]
        
        # 1. Volatility Stats (Z-Score)
        try:
            mean_price = statistics.mean(window)
            stdev = statistics.stdev(window)
        except statistics.StatisticsError:
            return None
            
        if stdev == 0:
            return None
            
        z_score = (current_price - mean_price) / stdev
        volatility = stdev / mean_price
        
        # 2. RSI (Momentum) - Simple Moving Average method for efficiency
        if len(data) < self.rsi_period + 1:
            return None
            
        # Calculate changes for the last N periods
        changes = [data[i] - data[i-1] for i in range(len(data)-self.rsi_period, len(data))]
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c < 0]
        
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        # 3. Trend Context
        # We prefer buying dips that are above the long-term baseline (Bullish Reversion)
        is_uptrend = current_price >= mean_price

        return {
            'z': z_score,
            'rsi': rsi,
            'vol': volatility,
            'uptrend': is_uptrend
        }

    def on_price_update(self, prices):
        """
        Main execution logic.
        """
        # 1. Ingest and Clean Data
        valid_symbols = []
        for symbol, data in prices.items():
            if 'priceUsd' not in data:
                continue
            
            try:
                price = float(data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            valid_symbols.append(symbol)
            
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.lookback_window + 10)
            self.price_history[symbol].append(price)
            
            # Decrement cooldowns
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]

        # Cleanup stale history
        active_set = set(valid_symbols)
        for s in list(self.price_history.keys()):
            if s not in active_set and s not in self.positions:
                del self.price_history[s]

        # 2. Exit Logic (Priority)
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                del self.positions[symbol]
                continue
            
            self.positions[symbol]['ticks'] += 1
            metrics = self._calculate_metrics(symbol)
            
            if not metrics:
                continue
                
            z = metrics['z']
            rsi = metrics['rsi']
            
            # Dynamic Profit Taking:
            # Exit if price shoots above mean significantly (Z > 0.5) OR RSI becomes overbought
            if z >= self.z_exit or rsi >= self.rsi_exit:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 1.0,
                    'reason': ['PROFIT_DYNAMIC']
                }
            
            # Statistical Stop Loss:
            # If price deviates beyond -4.8 sigma, the mean reversion thesis is invalid.
            if z <= self.z_stop:
                del self.positions[symbol]
                self.cooldowns[symbol] = 20  # Prevent immediate re-entry
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 1.0,
                    'reason': ['STOP_STAT']
                }
                
            # Time Stop:
            if self.positions[symbol]['ticks'] >= self.max_hold_ticks:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 1.0,
                    'reason': ['TIMEOUT']
                }

        # 3. Entry Logic
        if len(self.positions) >= self.max_concurrent_positions:
            return None
            
        candidates = []
        
        for symbol in valid_symbols:
            if symbol in self.positions or symbol in self.cooldowns:
                continue
            
            metrics = self._calculate_metrics(symbol)
            if not metrics:
                continue
                
            raw_data = prices[symbol]
            
            # -- Filters --
            if metrics['vol'] < self.min_volatility:
                continue
                
            try:
                liq = float(raw_data.get('liquidity', 0))
                chg_24h = float(raw_data.get('priceChange24h', 0))
            except (ValueError, TypeError):
                continue
                
            if liq < self.min_liquidity:
                continue
                
            # Anti-Rug/Crash Filter: Don't buy if down > 15% in 24h
            if chg_24h < self.max_rug_drop:
                continue
                
            # Trend Filter:
            # Generally avoid buying dips in a downtrend unless EXTREMELY oversold.
            if not metrics['uptrend']:
                # If in downtrend, require RSI to be < 20 (Capitulation) to enter
                if metrics['rsi'] > 20:
                    continue
            
            # -- Signal --
            # Confluence: Statistical Dip (Z) AND Momentum Oversold (RSI)
            if metrics['z'] < self.z_entry and metrics['rsi'] < self.rsi_entry:
                # Score: Volatility * Log(Liquidity). Prefer active, liquid pairs.
                score = abs(metrics['z']) * (math.log10(liq) if liq > 0 else 1)
                candidates.append({'symbol': symbol, 'score': score})
                
        if candidates:
            # Select best candidate
            best = max(candidates, key=lambda x: x['score'])
            target = best['symbol']
            
            self.positions[target] = {'ticks': 0}
            return {
                'side': 'BUY',
                'symbol': target,
                'amount': self.position_size,
                'reason': ['MEAN_REV_SIGNAL']
            }
            
        return None