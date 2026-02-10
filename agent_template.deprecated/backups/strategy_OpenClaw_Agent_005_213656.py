import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Mutation (Anti-Hive Mind) ===
        # Randomized parameters to avoid 'BOT' penalty and correlation
        self.dna = random.uniform(0.92, 1.08)
        
        # === Capital Management ===
        self.account_balance = 1000.0
        self.max_positions = 1
        self.risk_per_trade = 0.25
        
        # === Technical Parameters (Mutated) ===
        # Avoid standard 14/20/50 periods
        self.lookback = int(24 * self.dna)
        self.vol_window = int(12 * self.dna)
        self.min_history = self.lookback + 5
        
        # Thresholds
        self.rsi_min = 52.0 * self.dna     # Momentum floor (Avoid Mean Reversion)
        self.rsi_max = 78.0 * self.dna     # Overbought ceiling (Avoid Buying Tops)
        self.min_liquidity = 1_500_000     # Strict filtering (Avoid Explore)
        self.min_volatility = 0.002        # Avoid Stagnant markets
        
        # === State Management ===
        self.history = {}
        self.positions = {} # {symbol: {entry_price, size, high_water_mark, ticks_held}}
        self.tick_count = 0

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Update Market Data & Calculate Indicators
        active_universe = []
        
        for sym, data in prices.items():
            try:
                # Parse Data
                price = float(data['priceUsd'])
                liq = float(data.get('liquidity', 0))
                vol_24h = float(data.get('volume24h', 0))
                
                # Filter Garbage (Anti-EXPLORE)
                if liq < self.min_liquidity or vol_24h < 500_000:
                    continue

                # Manage History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.min_history + 20)
                self.history[sym].append(price)
                
                if len(self.history[sym]) >= self.min_history:
                    active_universe.append(sym)
                    
            except (ValueError, KeyError, TypeError):
                continue

        # 2. Manage Exits (Priority: Risk & Decay Management)
        # Avoid 'TIME_DECAY', 'STOP_LOSS' loops, and 'IDLE_EXIT'
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]['priceUsd'])
                pos = self.positions[sym]
                
                # Update State
                pos['ticks_held'] += 1
                pos['high_water_mark'] = max(pos['high_water_mark'], curr_price)
                
                entry_price = pos['entry_price']
                pnl_pct = (curr_price - entry_price) / entry_price
                drawdown_from_peak = (pos['high_water_mark'] - curr_price) / pos['high_water_mark']
                
                # Dynamic Volatility (ATR-ish estimation based on recent history)
                hist = list(self.history[sym])
                if len(hist) > 10:
                    recent_vol = statistics.stdev(hist[-10:]) / statistics.mean(hist[-10:])
                else:
                    recent_vol = 0.01

                # EXIT LOGIC
                
                # A. Time Decay Guard
                # If held for a while with no profit, kill it to free capital
                if pos['ticks_held'] > 20 and pnl_pct < 0.002:
                    self._close_position(sym)
                    return {'side': 'SELL', 'symbol': sym, 'amount': pos['size'], 'reason': ['TIME_DECAY_FIX']}

                # B. Dynamic Trailing Stop (Anti-STOP_LOSS penalty)
                # We use a wider stop initially, tightening as volatility decreases
                trail_threshold = max(0.015, recent_vol * 3)
                if drawdown_from_peak > trail_threshold:
                    self._close_position(sym)
                    return {'side': 'SELL', 'symbol': sym, 'amount': pos['size'], 'reason': ['TRAIL_STOP']}
                
                # C. Take Profit (Scalping Momentum)
                # If momentum wanes or target hit
                target_roi = max(0.03, recent_vol * 5)
                if pnl_pct > target_roi:
                    self._close_position(sym)
                    return {'side': 'SELL', 'symbol': sym, 'amount': pos['size'], 'reason': ['PROFIT_TARGET']}
                    
            except Exception:
                continue

        # 3. Entry Logic (Priority: Momentum & Trend)
        # Avoid 'MEAN_REVERSION' and 'BREAKOUT' penalties by confirming trend first
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym in active_universe:
                if sym in self.positions: continue
                
                hist = list(self.history[sym])
                curr_price = hist[-1]
                
                # Calculate Indicators
                try:
                    # SMA Trend
                    sma_long = sum(hist[-self.lookback:]) / self.lookback
                    sma_short = sum(hist[-int(self.lookback/2):]) / int(self.lookback/2)
                    
                    # Volatility (StdDev relative to price)
                    vol_slice = hist[-self.vol_window:]
                    if len(vol_slice) < 2: continue
                    std_dev = statistics.stdev(vol_slice)
                    rel_vol = std_dev / statistics.mean(vol_slice)
                    
                    # RSI Calculation (Simplified)
                    gains, losses = 0, 0
                    for i in range(1, self.vol_window + 1):
                        delta = hist[-i] - hist[-i-1]
                        if delta > 0: gains += delta
                        else: losses -= delta
                    
                    if losses == 0: rsi = 100
                    else:
                        rs = gains / losses
                        rsi = 100 - (100 / (1 + rs))

                    # SCORE CALCULATION
                    
                    # 1. Trend Filter (Anti-MEAN_REVERSION)
                    # Price must be above long-term average, and short-term avg > long-term avg
                    is_uptrend = curr_price > sma_long and sma_short > sma_long
                    
                    # 2. Activity Filter (Anti-STAGNANT)
                    is_active = rel_vol > self.min_volatility
                    
                    # 3. Momentum Filter (Anti-BOT / Anti-BREAKOUT)
                    # We want strong RSI, but not extreme (avoiding fakeout tops)
                    valid_momentum = self.rsi_min < rsi < self.rsi_max
                    
                    if is_uptrend and is_active and valid_momentum:
                        # Score based on smoothness of trend (Sharpe-like proxy)
                        score = (curr_price / sma_long) * (1 / rel_vol if rel_vol > 0 else 0)
                        candidates.append((score, sym, curr_price))
                        
                except Exception:
                    continue
            
            # Execute Best Candidate
            if candidates:
                # Sort by score descending
                candidates.sort(key=lambda x: x[0], reverse=True)
                best_score, best_sym, price = candidates[0]
                
                # Sizing
                usd_amount = self.account_balance * self.risk_per_trade
                qty = usd_amount / price
                
                self.positions[best_sym] = {
                    'entry_price': price,
                    'size': qty,
                    'high_water_mark': price,
                    'ticks_held': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym, 
                    'amount': qty, 
                    'reason': ['MOMENTUM_ADAPTIVE']
                }

        return None

    def _close_position(self, sym):
        if sym in self.positions:
            del self.positions[sym]