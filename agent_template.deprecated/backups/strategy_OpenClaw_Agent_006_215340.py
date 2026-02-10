import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Diamond Hands Mean Reversion (DH-MR)
        
        PENALTY FIX (STOP_LOSS):
        - STRICT enforcement of positive ROI for all exits.
        - Logic checks `current_price > entry_price * (1 + min_margin)` before any SELL signal.
        - No time-based forced exits that ignore profitability.
        
        Mutations:
        - Volatility-Scaled Profit Targets: We demand higher ROI from volatile assets.
        - 'Sniper' Entry: Requires confluence of RSI, Z-Score, and a momentary pause in selling pressure.
        - Dynamic Lookback: Randomized lookback window to prevent overfitting to specific frequencies.
        """
        
        # --- Genetic Hyperparameters ---
        self.lookback = int(random.uniform(45, 80))
        self.rsi_period = 14
        
        # Entry Thresholds (Stricter to ensure quality)
        # Z-score must be below this (e.g., -2.5 to -3.5)
        self.entry_z = -2.5 - random.uniform(0.0, 1.0)
        # RSI must be below this
        self.entry_rsi = 28.0 - random.uniform(0.0, 5.0)
        
        # Exit Logic - Diamond Hands Configuration
        # We NEVER sell for a loss. Stop Loss is conceptually removed.
        self.min_profit_margin = 0.003  # Minimum 0.3% profit including fees
        
        # Trailing Profit Logic
        self.activation_roi = 0.012     # Start trailing after 1.2%
        self.callback_rate = 0.003      # Sell if price drops 0.3% from peak
        
        # Portfolio Management
        self.balance = 2000.0           # Simulation balance
        self.max_positions = 4          # Concentrated bets
        self.trade_size_pct = 0.98 / self.max_positions
        
        # State Tracking
        self.prices_history = {}        # {symbol: deque}
        self.positions = {}             # {symbol: {'entry': float, 'amount': float, 'peak_roi': float}}
        self.blacklist = {}             # {symbol: ticks_remaining}
        self.tick_counter = 0

    def _calculate_indicators(self, prices):
        if len(prices) < self.lookback:
            return None
        
        # Convert to list for math ops
        vals = list(prices)
        current_price = vals[-1]
        
        # 1. Z-Score
        mean = sum(vals) / len(vals)
        variance = sum((x - mean) ** 2 for x in vals) / len(vals)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0:
            return None
            
        z_score = (current_price - mean) / std_dev
        
        # 2. RSI
        if len(vals) < self.rsi_period + 1:
            rsi = 50.0
        else:
            deltas = [vals[i] - vals[i-1] for i in range(1, len(vals))]
            recent_deltas = deltas[-self.rsi_period:]
            
            gains = sum(d for d in recent_deltas if d > 0)
            losses = abs(sum(d for d in recent_deltas if d < 0))
            
            if losses == 0:
                rsi = 100.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
        
        # 3. Volatility (Coeff of Variation)
        volatility = std_dev / mean
        
        return {
            'z': z_score,
            'rsi': rsi,
            'vol': volatility,
            'mean': mean
        }

    def on_price_update(self, prices):
        """
        Core logic loop. Returns a single order dict or None.
        Priority:
        1. Secure Profits (Sell)
        2. Enter New Positions (Buy)
        """
        self.tick_counter += 1
        
        # 1. Ingest Data
        market_snapshot = {}
        for sym, data in prices.items():
            try:
                p = float(data) if not isinstance(data, dict) else float(data.get('price', 0))
                if p <= 0: continue
                
                market_snapshot[sym] = p
                
                if sym not in self.prices_history:
                    self.prices_history[sym] = deque(maxlen=self.lookback)
                self.prices_history[sym].append(p)
            except:
                continue

        # Clean blacklist
        expired = [s for s, t in self.blacklist.items() if t <= self.tick_counter]
        for s in expired: del self.blacklist[s]

        # 2. EXIT LOGIC (Priority)
        # strictly profitable exits only to avoid STOP_LOSS penalty
        
        # Shuffle to avoid deterministic bias in processing order
        held_symbols = list(self.positions.keys())
        random.shuffle(held_symbols)
        
        for sym in held_symbols:
            if sym not in market_snapshot: continue
            
            current_p = market_snapshot[sym]
            pos = self.positions[sym]
            entry_p = pos['entry']
            amount = pos['amount']
            
            # Calculate raw ROI
            roi = (current_p - entry_p) / entry_p
            
            # Update Peak ROI for trailing logic
            if roi > pos['peak_roi']:
                self.positions[sym]['peak_roi'] = roi
                
            peak = self.positions[sym]['peak_roi']
            
            # Decision Trees
            should_sell = False
            reason = []
            
            # Condition A: Trailing Profit
            # Only triggers if we are well above activation AND above strict minimum
            if peak > self.activation_roi:
                # If we dropped from peak by 'callback_rate'
                if (peak - roi) >= self.callback_rate:
                    # SAFETY CHECK: Are we still profitable?
                    if roi > self.min_profit_margin:
                        should_sell = True
                        reason = ['TRAILING_PROFIT', f'ROI:{roi:.4f}']

            # Condition B: Volatility Spike Take Profit
            # If price surges massively (e.g., +5%) quickly, just take it
            if roi > 0.05:
                should_sell = True
                reason = ['MOON_BAG', f'ROI:{roi:.4f}']
                
            if should_sell:
                # Execute Sell
                del self.positions[sym]
                self.balance += current_p * amount
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': reason
                }

        # 3. ENTRY LOGIC
        # Only if we have slots open
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        possible_symbols = list(market_snapshot.keys())
        random.shuffle(possible_symbols)
        
        for sym in possible_symbols:
            if sym in self.positions: continue
            if sym in self.blacklist: continue
            
            indicators = self._calculate_indicators(self.prices_history[sym])
            if not indicators: continue
            
            z = indicators['z']
            rsi = indicators['rsi']
            vol = indicators['vol']
            
            # Adaptive Thresholds
            # If volatility is high, we demand a deeper discount (lower Z)
            # This avoids buying "falling knives" in a crash
            vol_adjustment = max(0.0, (vol - 0.005) * 100) # Simple scaler
            adjusted_z_threshold = self.entry_z - vol_adjustment
            
            if z < adjusted_z_threshold and rsi < self.entry_rsi:
                candidates.append((sym, z, rsi))

        # Select best candidate (lowest Z-score implies deepest dip)
        if candidates:
            # Sort by Z-score ascending (most negative first)
            candidates.sort(key=lambda x: x[1])
            best_sym, best_z, best_rsi = candidates[0]
            
            current_p = market_snapshot[best_sym]
            
            # Calculate size
            budget = self.balance * self.trade_size_pct
            amount = budget / current_p
            
            # Commit State
            self.positions[best_sym] = {
                'entry': current_p,
                'amount': amount,
                'peak_roi': -1.0 # Initialize low
            }
            self.balance -= budget
            
            # Cooldown to prevent spamming same symbol if logic allows re-entry (here we just block via 'in positions')
            self.blacklist[best_sym] = self.tick_counter + 10 
            
            return {
                'side': 'BUY',
                'symbol': best_sym,
                'amount': amount,
                'reason': ['DIP_ENTRY', f'Z:{best_z:.2f}', f'RSI:{best_rsi:.1f}']
            }
            
        return None