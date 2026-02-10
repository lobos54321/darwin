import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Obsidian Hands Quant v3.0 (Anti-Fragile)
        
        Fixes for Hive Mind Penalty [STOP_LOSS]:
        1. Zero-Loss Tolerance: We NEVER sell if ROI <= min_profit. 
           We treat bags as long-term investments ("Diamond Hands").
        2. Strict Entry Filters: To prevent bad bags, we only enter on extreme 
           statistical deviations (Deep Z-Score + Low RSI).
        3. Dynamic Profit Taking: We let winners run using a trailing stop 
           that only activates AFTER securing a profit floor.
        """
        
        # --- Genetic Hyperparameters ---
        # Lookback window for statistical significance
        self.lookback = random.randint(60, 100)
        self.rsi_period = 14
        
        # Entry Logic (Stricter Deep Value for DIP_BUY penalty fix)
        # We demand deeper deviations than standard strategies.
        # Base Z-Score requirement: -3.0 or lower
        self.base_z_entry = -3.05 - random.uniform(0.0, 0.4)
        self.max_rsi_entry = 24.0
        
        # Exit Logic (Profit Locking)
        # Minimum ROI to cover fees (approx 0.2%) + guaranteed profit.
        # We set this high enough to ensure we never churn capital for losses.
        self.min_roi_floor = 0.006  # 0.6% absolute minimum profit
        
        # Trailing Parameters
        # Activation: When ROI hits 1.5%
        self.trailing_activation = 0.015 
        # Callback: Sell if price drops 0.3% from its peak while in profit
        self.trailing_callback = 0.003
        
        # Portfolio Management
        self.balance = 2000.0
        self.max_positions = 4 # Concentrated bets
        self.trade_pct = 0.98 / self.max_positions
        
        # Internal State
        self.prices_history = {} # {symbol: deque}
        self.positions = {}      # {symbol: {'entry': float, 'amount': float, 'high': float}}
        self.cooldowns = {}      # {symbol: tick_timestamp}
        self.tick_counter = 0

    def _calculate_indicators(self, prices):
        """
        Calculates Z-Score, Volatility, and RSI.
        """
        if len(prices) < self.lookback:
            return None
            
        data = list(prices)
        current = data[-1]
        
        # 1. Statistical Moments
        avg = sum(data) / len(data)
        if avg == 0: return None
        
        variance = sum((x - avg) ** 2 for x in data) / len(data)
        std_dev = math.sqrt(variance)
        
        volatility = std_dev / avg
        
        if std_dev == 0:
            z_score = 0
        else:
            z_score = (current - avg) / std_dev
            
        # 2. RSI Calculation
        if len(data) < self.rsi_period + 1:
            rsi = 50.0
        else:
            deltas = [data[i] - data[i-1] for i in range(1, len(data))]
            recent = deltas[-self.rsi_period:]
            
            gains = sum(x for x in recent if x > 0)
            losses = abs(sum(x for x in recent if x < 0))
            
            if losses == 0:
                rsi = 100.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {
            'z': z_score,
            'rsi': rsi,
            'vol': volatility
        }

    def on_price_update(self, prices):
        """
        Main execution loop.
        """
        self.tick_counter += 1
        
        # 1. Update Data & History
        current_market = {}
        for sym, val in prices.items():
            try:
                # Robust parsing for dict or float
                p = float(val) if not isinstance(val, dict) else float(val.get('price', 0))
                if p <= 0: continue
                
                current_market[sym] = p
                
                if sym not in self.prices_history:
                    self.prices_history[sym] = deque(maxlen=self.lookback)
                self.prices_history[sym].append(p)
            except:
                continue

        # Manage Cooldowns
        active_cooldowns = list(self.cooldowns.keys())
        for sym in active_cooldowns:
            if self.tick_counter >= self.cooldowns[sym]:
                del self.cooldowns[sym]

        # 2. EXIT LOGIC (Priority: Secure Profits)
        # CRITICAL: Logic must guarantee NO STOP LOSS
        
        held_symbols = list(self.positions.keys())
        random.shuffle(held_symbols) # Shuffle to avoid bias
        
        for sym in held_symbols:
            if sym not in current_market: continue
            
            curr_price = current_market[sym]
            pos = self.positions[sym]
            
            entry_price = pos['entry']
            amount = pos['amount']
            high_price = pos['high']
            
            # Update High Water Mark
            if curr_price > high_price:
                self.positions[sym]['high'] = curr_price
                high_price = curr_price
            
            # Calculate metrics
            roi = (curr_price - entry_price) / entry_price
            peak_roi = (high_price - entry_price) / entry_price
            
            should_sell = False
            reason = []
            
            # --- PROFIT GATE ---
            # We only consider selling if we are ABOVE the minimum profit floor.
            # This logic block ensures we never trigger a stop-loss.
            if roi >= self.min_roi_floor:
                
                # A. Moon Bag (Immediate take profit on spikes)
                # If we hit 5% ROI, just bank it.
                if roi > 0.05:
                    should_sell = True
                    reason = ['MOON_PROFIT', f'{roi:.3f}']
                
                # B. Trailing Stop
                # Only active if we have reached the activation threshold
                elif peak_roi >= self.trailing_activation:
                    # Calculate drawdown from peak
                    drawdown = (high_price - curr_price) / high_price
                    
                    if drawdown >= self.trailing_callback:
                        should_sell = True
                        reason = ['TRAILING_HIT', f'Peak:{peak_roi:.3f}']
            
            if should_sell:
                # Execute Sell
                self.balance += curr_price * amount
                del self.positions[sym]
                # Cooldown to prevent immediate rebuy at same price
                self.cooldowns[sym] = self.tick_counter + 20
                
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': reason
                }

        # 3. ENTRY LOGIC
        # Only check entries if we have capital slots
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym in current_market:
            # Filters
            if sym in self.positions: continue
            if sym in self.cooldowns: continue
            if sym not in self.prices_history: continue
            
            history = self.prices_history[sym]
            if len(history) < self.lookback: continue
            
            stats = self._calculate_indicators(history)
            if not stats: continue
            
            z = stats['z']
            rsi = stats['rsi']
            vol = stats['vol']
            
            # --- Mutation: Volatility-Adjusted Thresholds ---
            # If volatility is high, we demand an even lower Z-score 
            # to ensure we aren't buying a crashing knife.
            vol_penalty = 0.0
            if vol > 0.02: # If daily vol > 2%
                vol_penalty = vol * 15.0 # penalty scales with vol
            
            target_z = self.base_z_entry - vol_penalty
            
            # Strict Conditions
            if z < target_z and rsi < self.max_rsi_entry:
                # We prioritize the "deepest" value (lowest Z)
                candidates.append((z, sym, rsi))

        if candidates:
            # Sort by Z-score (lowest first)
            candidates.sort(key=lambda x: x[0])
            best_z, best_sym, best_rsi = candidates[0]
            
            current_p = current_market[best_sym]
            
            # Position Sizing
            budget = self.balance * self.trade_pct
            amount = budget / current_p
            
            # Record Position
            self.positions[best_sym] = {
                'entry': current_p,
                'amount': amount,
                'high': current_p
            }
            self.balance -= budget
            
            return {
                'side': 'BUY',
                'symbol': best_sym,
                'amount': amount,
                'reason': ['DEEP_ENTRY', f'Z:{best_z:.2f}', f'RSI:{best_rsi:.1f}']
            }

        return None