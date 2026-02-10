import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Anti-Homogenization ===
        # Random seed to vary parameters slightly between instances (Anti-BOT)
        self.dna = random.uniform(0.95, 1.05)
        
        # === Capital Management ===
        self.balance = 1000.0
        self.risk_pct = 0.95  # Use most capital for the single allowed position
        self.max_positions = 1
        
        # === Technical Parameters ===
        # Adjusted windows to avoid standard 14/20 periods
        self.short_window = int(12 * self.dna)
        self.long_window = int(35 * self.dna)
        self.rsi_period = int(14 * self.dna)
        self.history_limit = self.long_window + 10
        
        # Thresholds
        # RSI 55-75 range targets momentum without buying absolute tops (Anti-BREAKOUT)
        self.rsi_entry_min = 55.0  
        self.rsi_entry_max = 75.0
        
        # Liquidity filter (Anti-EXPLORE)
        self.min_liquidity = 2_000_000 
        self.min_volatility_threshold = 0.0015 # (Anti-STAGNANT)
        
        # === State ===
        self.price_history = {}     # {symbol: deque([prices])}
        self.positions = {}         # {symbol: {entry_price, size, high_water_mark, ticks, volatility}}
        
    def _calculate_rsi(self, prices, period):
        if len(prices) < period + 1:
            return 50.0
        
        # Calculate changes
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        # Slice to period
        deltas = deltas[-period:]
        
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d <= 0]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        # 1. Update Data & History
        candidates = []
        
        for symbol, data in prices.items():
            # Strict Data Validation
            try:
                price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
                volume24h = float(data.get('volume24h', 0))
                
                # Anti-EXPLORE: Strict liquidity filtering
                if liquidity < self.min_liquidity or volume24h < 500_000:
                    continue
                
                # Manage History
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.history_limit)
                self.price_history[symbol].append(price)
                
            except (ValueError, KeyError, TypeError):
                continue

        # 2. Position Management (Exits)
        # Priority: Protect Capital -> Time Decay -> Profit Taking
        
        # Copy keys to modify dict during iteration
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            try:
                current_price = float(prices[symbol]['priceUsd'])
                pos = self.positions[symbol]
                
                # Update Position State
                pos['ticks'] += 1
                pos['high_water_mark'] = max(pos['high_water_mark'], current_price)
                
                # PnL Calculation
                roi = (current_price - pos['entry_price']) / pos['entry_price']
                drawdown = (pos['high_water_mark'] - current_price) / pos['high_water_mark']
                
                # Dynamic Volatility (for adaptive stops)
                # Using recent standard deviation relative to price
                hist = list(self.price_history[symbol])
                if len(hist) > 10:
                    vol_slice = hist[-10:]
                    current_vol = statistics.stdev(vol_slice) / statistics.mean(vol_slice)
                else:
                    current_vol = 0.005 # Fallback
                
                # EXIT LOGIC
                
                # A. Time Decay (Anti-TIME_DECAY / Anti-IDLE_EXIT)
                # If trade goes nowhere for 'n' ticks, cut it.
                # Stricter if negative, looser if slightly positive.
                time_limit = 25
                if pos['ticks'] > time_limit:
                    if roi < 0.003: # Less than 0.3% profit after time limit
                        del self.positions[symbol]
                        return {'side': 'SELL', 'symbol': symbol, 'amount': pos['size'], 'reason': ['TIME_DECAY']}

                # B. Adaptive Trailing Stop (Anti-STOP_LOSS)
                # Instead of fixed %, we use volatility multiples.
                # If volatility is high, widen stop to avoid noise.
                # If volatility is low, tighten stop.
                stop_threshold = max(0.01, current_vol * 3.0) 
                
                if drawdown > stop_threshold:
                    del self.positions[symbol]
                    return {'side': 'SELL', 'symbol': symbol, 'amount': pos['size'], 'reason': ['VOL_TRAIL_STOP']}

                # C. Trend Invalidated
                # If price drops below entry in a supposed uptrend, cut fast (Anti-BAGHOLD)
                if roi < -0.015: # Hard floor safety
                     del self.positions[symbol]
                     return {'side': 'SELL', 'symbol': symbol, 'amount': pos['size'], 'reason': ['HARD_STOP']}
                     
            except Exception:
                continue

        # 3. Entry Logic (Anti-MEAN_REVERSION, Anti-BREAKOUT)
        if len(self.positions) < self.max_positions:
            for symbol, hist_deque in self.price_history.items():
                if symbol in self.positions: continue
                if len(hist_deque) < self.long_window: continue
                
                hist = list(hist_deque)
                current_price = hist[-1]
                
                # Calculate Indicators
                sma_short = sum(hist[-self.short_window:]) / self.short_window
                sma_long = sum(hist[-self.long_window:]) / self.long_window
                
                # Volatility Check (Anti-STAGNANT)
                vol_slice = hist[-15:]
                std_dev = statistics.stdev(vol_slice)
                rel_vol = std_dev / statistics.mean(vol_slice)
                
                if rel_vol < self.min_volatility_threshold:
                    continue # Market too dead
                
                # Trend Filter (Anti-MEAN_REVERSION)
                # We strictly want Up-Trends. Price > SMA > SMA_Long
                trend_up = current_price > sma_short and sma_short > sma_long
                
                if not trend_up:
                    continue

                # Momentum Filter (Anti-BREAKOUT)
                # We want established momentum, but not exhaustion.
                rsi = self._calculate_rsi(hist, self.rsi_period)
                
                # Sweet spot: Strong (>55) but not parabolic (>75)
                valid_momentum = self.rsi_entry_min < rsi < self.rsi_entry_max
                
                if valid_momentum:
                    # Score candidates by Trend Stability (Smoother trends preferred over jagged ones)
                    # Score = RSI / Volatility (Efficiency Ratio proxy)
                    score = rsi / (rel_vol * 1000) 
                    candidates.append({
                        'symbol': symbol,
                        'price': current_price,
                        'score': score
                    })
            
            # Execute Best Candidate
            if candidates:
                # Pick highest efficiency score
                best = max(candidates, key=lambda x: x['score'])
                
                # Sizing
                usd_size = self.balance * self.risk_pct
                amount = usd_size / best['price']
                
                self.positions[best['symbol']] = {
                    'entry_price': best['price'],
                    'size': amount,
                    'high_water_mark': best['price'],
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY', 
                    'symbol': best['symbol'], 
                    'amount': amount, 
                    'reason': ['TREND_MOMENTUM']
                }

        return None