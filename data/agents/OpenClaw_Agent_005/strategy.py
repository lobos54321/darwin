import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Random seed to vary parameters and avoid homogenization
        self.dna = random.uniform(0.95, 1.15)
        
        # === Capital Management ===
        self.balance = 1000.0
        self.risk_per_trade = 0.95  # Aggressive allocation for best setups
        self.max_positions = 1      # Focus capital
        
        # === Indicators & Windows ===
        # Lookback optimized for momentum detection
        self.lookback_period = int(24 * self.dna) 
        self.rsi_period = 14
        
        # === Filters (Strict) ===
        self.min_liquidity = 2_000_000
        self.min_volume = 1_000_000
        
        # === Strategy Thresholds (Anti-MEAN_REVERSION) ===
        # We replace dip-buying with Z-Score Breakout logic.
        # Buying only when price is statistically significantly HIGHER than the mean.
        self.z_entry_threshold = 1.6 * self.dna  # Buy > 1.6 std devs above mean
        
        # RSI Confirmation: Must be bullish (>55) but not exhausted (<85)
        self.rsi_min = 55.0
        self.rsi_max = 85.0
        
        # State
        self.history = {}      # {symbol: deque}
        self.positions = {}    # {symbol: {data}}

    def _get_rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        gains = []
        losses = []
        
        # Calculate changes
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        # Simple Average for speed/stability in HFT window
        avg_gain = sum(gains[-self.rsi_period:]) / self.rsi_period
        avg_loss = sum(losses[-self.rsi_period:]) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _get_z_score(self, prices):
        # Measures how many standard deviations current price is from the mean
        if len(prices) < self.lookback_period:
            return 0.0
            
        window = list(prices)[-self.lookback_period:]
        if len(window) < 2: 
            return 0.0
            
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        if stdev == 0:
            return 0.0
            
        current = window[-1]
        return (current - mean) / stdev

    def on_price_update(self, prices: dict):
        # 1. Ingest Data & Update History
        active_symbols = []
        
        for symbol, data in prices.items():
            try:
                # Extract and validate
                price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
                volume = float(data.get('volume24h', 0))
                
                if liquidity < self.min_liquidity or volume < self.min_volume:
                    continue
                
                if symbol not in self.history:
                    self.history[symbol] = deque(maxlen=self.lookback_period + 5)
                
                self.history[symbol].append(price)
                active_symbols.append(symbol)
                
            except (KeyError, ValueError, TypeError):
                continue

        # 2. Manage Existing Positions
        # Check for exits before entries
        pos_keys = list(self.positions.keys())
        for symbol in pos_keys:
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = float(prices[symbol]['priceUsd'])
            
            # Update High Water Mark for Trailing Stop
            pos['high_water_mark'] = max(pos['high_water_mark'], current_price)
            
            # Calculate PnL stats
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            drawdown = (pos['high_water_mark'] - current_price) / pos['high_water_mark']
            
            # === Exit Logic ===
            # A. Trailing Stop (Protect Gains)
            # Tight trail (1.2%) for momentum trades
            if drawdown > 0.012:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['TRAIL_STOP']}
            
            # B. Hard Stop Loss (Catastrophe protection)
            if roi < -0.02:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['STOP_LOSS']}
            
            # C. Take Profit (Scalp)
            if roi > 0.05:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['TAKE_PROFIT']}

        # 3. Scan for Entries (Momentum Breakout)
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for symbol in active_symbols:
                if symbol in self.positions: continue
                
                hist = self.history[symbol]
                if len(hist) < self.lookback_period: continue
                
                # Calculate Z-Score
                z_score = self._get_z_score(hist)
                
                # === Anti-MEAN_REVERSION Logic ===
                # Strictly buy positive deviation (Breakouts)
                # Z-Score > Threshold means price is shooting up away from average
                if z_score > self.z_entry_threshold:
                    
                    # Confirm with RSI (Trend Strength)
                    # Avoid buying absolute tops (RSI > 85)
                    rsi = self._get_rsi(list(hist))
                    
                    if self.rsi_min < rsi < self.rsi_max:
                        candidates.append({
                            'symbol': symbol,
                            'price': hist[-1],
                            'score': z_score  # Higher Z-score = Stronger Breakout
                        })
            
            # Execute best candidate
            if candidates:
                best = max(candidates, key=lambda x: x['score'])
                
                usd_size = self.balance * self.risk_per_trade
                amount = usd_size / best['price']
                
                self.positions[best['symbol']] = {
                    'entry_price': best['price'],
                    'amount': amount,
                    'high_water_mark': best['price']
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best['symbol'],
                    'amount': amount,
                    'reason': ['Z_BREAKOUT']
                }
                
        return None