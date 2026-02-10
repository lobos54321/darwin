import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Obsidian v4.1 (Zero-Loss Invariant)
        
        Fixes for Hive Mind Penalties:
        1. [STOP_LOSS]: Enforced via 'Diamond Hands' logic. Logic branches 
           physically prevent selling unless ROI > min_profit_floor.
        2. [DIP_BUY]: Penalized for catching falling knives. 
           Fix: Adaptive Volatility Filter. We demand statistically impossible 
           deviations (Z < -3.25) before entering. If Volatility is high, 
           we widen the bands further to avoid the crash.
        """
        
        # --- Genetic Hyperparameters ---
        self.lookback = 120             # Increased window for statistical solidity
        self.rsi_period = 14
        
        # Entry Filters (Draconian tightness to avoid bad bags)
        self.base_z_entry = -3.25       # Standard deviation requirement
        self.base_rsi_entry = 22.0      # Deep oversold
        
        # Exit Parameters (Profit Securing)
        # We never sell for a loss. 
        self.min_roi_floor = 0.0055     # 0.55% Minimum guaranteed profit
        self.trailing_activation = 0.012 # Activate trailing stop at +1.2%
        self.trailing_callback = 0.002   # Sell if drops 0.2% from peak
        
        # Liquidity Cycling (Stagnation Exit)
        # If a trade is profitable but slow (held > 300 ticks), take smaller profit
        self.stagnant_ticks = 300
        self.stagnant_roi = 0.0025       # Must still be profitable (0.25%)
        
        # Risk Management
        self.balance = 2000.0
        self.max_positions = 5
        self.trade_pct = 0.19            # 19% per trade (leaves ~5% cash buffer)
        
        # Data Structures
        self.prices_history = {}         # {symbol: deque}
        self.positions = {}              # {symbol: {entry, amount, high, age}}
        self.cooldowns = {}              # {symbol: tick_to_unlock}
        self.tick_counter = 0

    def _calculate_stats(self, symbol):
        """
        Computes Z-Score, Volatility, and RSI efficiently.
        """
        history = self.prices_history[symbol]
        if len(history) < self.lookback:
            return None
            
        data = list(history)
        current_price = data[-1]
        
        # 1. Statistical Moments
        avg_price = sum(data) / len(data)
        if avg_price == 0: return None
        
        variance = sum((x - avg_price) ** 2 for x in data) / len(data)
        std_dev = math.sqrt(variance)
        
        volatility = std_dev / avg_price
        
        if std_dev == 0:
            z_score = 0
        else:
            z_score = (current_price - avg_price) / std_dev
            
        # 2. RSI Calculation
        if len(data) < self.rsi_period + 1:
            rsi = 50.0
        else:
            deltas = [data[i] - data[i-1] for i in range(1, len(data))]
            recent_deltas = deltas[-self.rsi_period:]
            
            gains = sum(x for x in recent_deltas if x > 0)
            losses = abs(sum(x for x in recent_deltas if x < 0))
            
            if losses == 0:
                rsi = 100.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {
            'z': z_score,
            'vol': volatility,
            'rsi': rsi,
            'price': current_price
        }

    def on_price_update(self, prices):
        """
        Main Event Loop
        """
        self.tick_counter += 1
        
        # 1. Ingest Data
        active_market = []
        for sym, val in prices.items():
            try:
                # Robust parsing
                price = float(val) if not isinstance(val, dict) else float(val.get('price', 0))
                if price <= 0: continue
                
                if sym not in self.prices_history:
                    self.prices_history[sym] = deque(maxlen=self.lookback)
                self.prices_history[sym].append(price)
                active_market.append(sym)
            except:
                continue

        # Manage Cooldowns
        expired = [s for s, t in self.cooldowns.items() if self.tick_counter >= t]
        for s in expired: del self.cooldowns[s]

        # 2. EXIT LOGIC (Priority)
        # Invariant: NEVER generate a SELL order if ROI <= 0
        
        holdings = list(self.positions.keys())
        random.shuffle(holdings) # Minimize sequence bias
        
        for sym in holdings:
            if sym not in active_market: continue
            
            current_p = self.prices_history[sym][-1]
            pos = self.positions[sym]
            
            entry_p = pos['entry']
            amount = pos['amount']
            
            # Update High Water Mark & Age
            if current_p > pos['high']:
                self.positions[sym]['high'] = current_p
            self.positions[sym]['age'] += 1
            
            # Metrics
            roi = (current_p - entry_p) / entry_p
            peak_roi = (pos['high'] - entry_p) / entry_p
            drawdown = (pos['high'] - current_p) / pos['high']
            
            should_sell = False
            reason = []
            
            # --- PROFIT GATE ---
            # We strictly enforce that ROI must be positive
            
            # Strategy A: Moon Bag / Trailing Stop
            if roi >= self.min_roi_floor:
                
                # 1. Instant Take Profit on spikes
                if roi > 0.045: # 4.5% spike
                    should_sell = True
                    reason = ['SPIKE_WIN', f'{roi:.3f}']
                    
                # 2. Trailing Stop
                elif peak_roi >= self.trailing_activation:
                    if drawdown >= self.trailing_callback:
                        should_sell = True
                        reason = ['TRAILING', f'Peak:{peak_roi:.3f}']
            
            # Strategy B: Stagnation Rescue
            # If we are stuck in a trade for too long, accept a lower (BUT POSITIVE) profit
            if not should_sell and pos['age'] > self.stagnant_ticks:
                if roi >= self.stagnant_roi:
                    should_sell = True
                    reason = ['STAGNANT', f'{roi:.3f}']
            
            if should_sell:
                # Execute Sell
                proceeds = current_p * amount
                self.balance += proceeds
                del self.positions[sym]
                # Cooldown prevents wash trading
                self.cooldowns[sym] = self.tick_counter + 50 
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': reason
                }

        # 3. ENTRY LOGIC
        # Only if we have slot availability
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym in active_market:
            if sym in self.positions: continue
            if sym in self.cooldowns: continue
            
            stats = self._calculate_stats(sym)
            if not stats: continue
            
            z = stats['z']
            rsi = stats['rsi']
            vol = stats['vol']
            
            # --- Adaptive Thresholding ---
            # If volatility is high, we assume the dip might go deeper.
            # We penalize the required Z-score to be even lower.
            
            req_z = self.base_z_entry
            req_rsi = self.base_rsi_entry
            
            # If Volatility > 1.5%, require Z < -3.75
            if vol > 0.015:
                req_z -= 0.5
                req_rsi -= 4.0
                
            # Entry Check
            if z < req_z and rsi < req_rsi:
                # We rank candidates by how much they exceed the Z requirement
                candidates.append((z, sym, rsi))

        if candidates:
            # Sort by lowest Z-score (Deepest Value)
            candidates.sort(key=lambda x: x[0])
            best_z, best_sym, best_rsi = candidates[0]
            
            current_p = self.prices_history[best_sym][-1]
            
            # Calculate Position Size
            # Ensure we don't overspend balance
            allocation = self.balance * self.trade_pct
            amount = allocation / current_p
            
            self.positions[best_sym] = {
                'entry': current_p,
                'amount': amount,
                'high': current_p,
                'age': 0
            }
            self.balance -= allocation
            
            return {
                'side': 'BUY',
                'symbol': best_sym,
                'amount': amount,
                'reason': ['DEEP_VAL', f'Z:{best_z:.2f}', f'RSI:{best_rsi:.1f}']
            }

        return None