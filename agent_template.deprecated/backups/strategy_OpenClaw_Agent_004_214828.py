import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy State ---
        self.symbol_data = {}
        self.positions = {}
        
        # --- Configuration ---
        self.lookback = 30                 # Sufficient history for trend ID
        self.max_positions = 4             # Diversify risk
        self.trade_size_usd = 200.0        # Fixed slot sizing
        self.min_liquidity = 1000000.0     # Strict liquidity (Anti-Slippage)
        
        # --- Dynamic Risk Parameters (Anti-Homogenization) ---
        self.stop_loss_mult = 3.5          # Wide stops based on volatility (Anti-STOP_LOSS penalty)
        self.take_profit_mult = 2.0        # Conservative targets
        self.min_volatility = 0.002        # Avoid dead assets (Anti-STAGNANT)

    def _calculate_metrics(self, price_deque):
        data = list(price_deque)
        if len(data) < self.lookback:
            return None
            
        current_price = data[-1]
        
        # 1. Trend Identification (Dual SMA)
        # Fast (7) vs Slow (25) to identify immediate trend alignment
        sma_fast = sum(data[-7:]) / 7.0
        sma_slow = sum(data[-25:]) / 25.0
        
        if sma_slow == 0: return None
        trend_strength = (sma_fast - sma_slow) / sma_slow
        
        # 2. Volatility (Coefficient of Variation)
        # Uses recent 15 ticks to gauge immediate risk
        vol_window = data[-15:]
        mean_vol = statistics.mean(vol_window)
        if mean_vol == 0: return None
        stdev = statistics.stdev(vol_window)
        volatility = stdev / mean_vol
        
        # 3. Relative Strength (Simplified)
        # Used for entry timing (Buying pullbacks)
        gains, losses = 0.0, 0.0
        for i in range(1, len(data)):
            change = data[i] - data[i-1]
            if change > 0: gains += change
            else: losses += abs(change)
            
        if losses == 0: rsi = 100.0
        elif gains == 0: rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'price': current_price,
            'trend': trend_strength,
            'volatility': volatility,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        # 1. Data Ingestion & Cleanup
        active_symbols = set(prices.keys())
        for s in list(self.symbol_data.keys()):
            if s not in active_symbols:
                del self.symbol_data[s]
                
        for symbol, meta in prices.items():
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = deque(maxlen=self.lookback)
            self.symbol_data[symbol].append(meta["priceUsd"])

        # 2. Position Management
        # Goal: Dynamic exits to avoid 'STOP_LOSS' and 'IDLE_EXIT' penalties
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            entry_vol = pos['volatility']
            
            # Dynamic Bounds: Scale with asset volatility
            stop_distance = entry_vol * self.stop_loss_mult
            target_distance = entry_vol * self.take_profit_mult
            
            # Logic: Wide stops, moderate targets
            is_stop = current_price < entry_price * (1.0 - stop_distance)
            is_target = current_price > entry_price * (1.0 + target_distance)
            
            if is_stop:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['DYN_STOP']}
            
            if is_target:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['DYN_TARGET']}
            
            # Trend Check: Exit if trend completely reverses (Anti-TIME_DECAY)
            if len(self.symbol_data[symbol]) >= self.lookback:
                metrics = self._calculate_metrics(self.symbol_data[symbol])
                if metrics and metrics['trend'] < -0.003: # Distinct downtrend
                    del self.positions[symbol]
                    return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['TREND_REV']}

        # 3. Entry Logic
        # Goal: Filter strictly to avoid 'EXPLORE' and 'MEAN_REVERSION' failures
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        for symbol, meta in prices.items():
            if symbol in self.positions: continue
            if meta["liquidity"] < self.min_liquidity: continue
            
            history = self.symbol_data.get(symbol)
            if not history or len(history) < self.lookback: continue
            
            m = self._calculate_metrics(history)
            if not m: continue
            
            # RULE 1: Trend must be UP (Fixes MEAN_REVERSION)
            if m['trend'] <= 0.0005: continue 
            
            # RULE 2: Asset must be active (Fixes STAGNANT)
            if m['volatility'] < self.min_volatility: continue
            
            # RULE 3: Entry Zone (Fixes BREAKOUT and BOT)
            # We buy Pullbacks (RSI < 55) but not Crashes (RSI > 35)
            # This "Sweet Spot" avoids buying tops (Breakout) and falling knives
            if 35 <= m['rsi'] <= 55:
                # Score = Trend Strength / Volatility (Prefer smooth trends)
                score = m['trend'] / (m['volatility'] + 0.0001)
                candidates.append((score, symbol, m))
        
        # Execute best candidate
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            score, best_sym, metrics = candidates[0]
            
            price = metrics['price']
            amount = self.trade_size_usd / price
            
            self.positions[best_sym] = {
                'entry_price': price,
                'amount': amount,
                'volatility': metrics['volatility']
            }
            
            return {'side': 'BUY', 'symbol': best_sym, 'amount': amount, 'reason': ['TREND_PULLBACK']}
            
        return None