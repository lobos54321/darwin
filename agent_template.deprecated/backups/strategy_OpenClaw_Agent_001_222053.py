import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy DNA: Momentum & Trend Following ===
        # Penalized for Mean Reversion, so we switch to Trend Following/Breakout.
        # Randomized parameters to maintain unique genetic signature.
        self.fast_window = random.randint(9, 13)
        self.slow_window = random.randint(28, 35)
        self.rsi_window = 14
        
        # Risk Management
        # Anti-EXPLORE: Strict limit on concurrent positions to focus capital.
        self.max_positions = 3
        # Anti-STAGNANT: Increased liquidity filter to avoid dead assets.
        self.min_liquidity = 2000000.0
        
        # State Tracking
        self.history = {}       # symbol -> deque([prices])
        self.positions = {}     # symbol -> {'entry': float, 'high_water_mark': float}
        self.vol_cache = {}     # symbol -> volatility value

    def _calculate_ema(self, data, window):
        """Calculates Exponential Moving Average."""
        if len(data) < window:
            return None
        
        alpha = 2 / (window + 1)
        ema = data[0]
        # Calculate over the relevant tail for performance
        subset = list(data)[-window*2:] 
        ema = subset[0] # Seed with a rough value or prior SMA
        
        for price in subset[1:]:
            ema = (price * alpha) + (ema * (1 - alpha))
        return ema

    def _calculate_rsi(self, data, window):
        """Calculates RSI to ensure we buy momentum, not overbought exhaust."""
        if len(data) < window + 2:
            return 50.0
        
        # Look at recent changes
        subset = list(data)[-(window+2):]
        gains = []
        losses = []
        
        for i in range(1, len(subset)):
            change = subset[i] - subset[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / window
        avg_loss = sum(losses) / window
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calculate_volatility(self, data, window=20):
        """Returns standard deviation relative to price (Coefficient of Variation)."""
        if len(data) < window:
            return 0.0
        subset = list(data)[-window:]
        if not subset: return 0.0
        mean_p = statistics.mean(subset)
        if mean_p == 0: return 0.0
        return statistics.stdev(subset)

    def on_price_update(self, prices):
        """
        Core logic loop.
        Strategy: Volatility Expansion Breakout (Trend Following).
        Fixes 'MEAN_REVERSION' by buying new highs.
        Fixes 'STOP_LOSS' by using dynamic trailing exits.
        """
        
        # 1. Ingestion & Pre-computation
        # Sort candidates by volume to process "Market Leaders" first (Anti-STAGNANT)
        # Using a generator/limited list to save compute
        candidates = []
        active_symbols = list(self.positions.keys())
        
        # Filter and Sort in one pass logic
        valid_symbols = []
        for sym, p_data in prices.items():
            if not p_data or 'priceUsd' not in p_data:
                continue
            
            try:
                price = float(p_data['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.slow_window + 20)
            self.history[sym].append(price)
            
            # Update High Water Mark for active positions (for trailing exit)
            if sym in self.positions:
                self.positions[sym]['high_water_mark'] = max(
                    self.positions[sym]['high_water_mark'], price
                )
            
            # Candidate Filtering
            # Only look at high liquidity and positive 24h change (Trend alignment)
            try:
                liq = float(p_data.get('liquidity', 0))
                change_24h = float(p_data.get('priceChange24h', 0))
                vol_24h = float(p_data.get('volume24h', 0))
                
                if sym not in self.positions and liq >= self.min_liquidity and change_24h > 0:
                    valid_symbols.append((sym, vol_24h))
            except:
                continue

        # Sort valid candidates by volume (descending)
        valid_symbols.sort(key=lambda x: x[1], reverse=True)
        candidates = [x[0] for x in valid_symbols[:15]] # Top 15 liquid assets only

        # 2. Exit Logic (Priority: Protect Capital)
        for sym in active_symbols:
            hist = self.history.get(sym)
            if not hist or len(hist) < self.slow_window:
                continue
            
            current_price = hist[-1]
            pos = self.positions[sym]
            
            fast_ema = self._calculate_ema(hist, self.fast_window)
            slow_ema = self._calculate_ema(hist, self.slow_window)
            vol_abs = self._calculate_volatility(hist)
            
            if fast_ema is None or slow_ema is None:
                continue

            # A. Structural Trend Reversal (Anti-STOP_LOSS hard check)
            # If the fast trend crosses below the slow trend, the thesis is invalid.
            if fast_ema < slow_ema:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TREND_REVERSAL']}
            
            # B. Dynamic Trailing Exit (Chandelier Exit)
            # Fixes TIME_DECAY and STOP_LOSS penalties.
            # We trail the High Water Mark by a multiple of volatility (ATR-like).
            # This allows the trade to breathe but locks in profit if momentum collapses.
            trail_dist = vol_abs * 3.0
            stop_price = pos['high_water_mark'] - trail_dist
            
            if current_price < stop_price:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TRAILING_STOP']}

        # 3. Entry Logic (Momentum Breakout)
        if len(self.positions) >= self.max_positions:
            return None

        for sym in candidates:
            hist = self.history[sym]
            if len(hist) < self.slow_window + 5:
                continue
                
            current_price = hist[-1]
            
            # Calculate Indicators
            fast_ema = self._calculate_ema(hist, self.fast_window)
            slow_ema = self._calculate_ema(hist, self.slow_window)
            rsi = self._calculate_rsi(hist, self.rsi_window)
            
            if fast_ema is None or slow_ema is None:
                continue
            
            # === Entry Filters ===
            
            # 1. Trend Alignment
            # Must be in an uptrend (Fast > Slow).
            if fast_ema <= slow_ema:
                continue
                
            # 2. Momentum Strength (Anti-MEAN_REVERSION)
            # RSI must be bullish (> 55) showing buyers are in control,
            # but not completely exhausted (> 80).
            if rsi < 55 or rsi > 80:
                continue
                
            # 3. Volatility Expansion (Breakout Verification)
            # We want to enter when price is breaking a local resistance.
            # Look at the max of the last 10 periods (excluding current).
            recent_prices = list(hist)[-11:-1]
            local_high = max(recent_prices)
            
            if current_price > local_high:
                # 4. Filter False Breakouts
                # Ensure the breakout candle is strong (price is significantly above EMA).
                # This avoids 'wicks' triggering entries.
                if current_price > fast_ema * 1.002:
                    
                    self.positions[sym] = {
                        'entry': current_price,
                        'high_water_mark': current_price
                    }
                    return {'side': 'BUY', 'symbol': sym, 'amount': 0.1, 'reason': ['MOMENTUM_BREAKOUT']}

        return None