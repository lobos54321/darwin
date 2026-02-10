import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy State ---
        self.symbol_data = {}
        self.positions = {}
        self.balance = 1000.0
        self.tick_counter = 0
        
        # --- Parameters & Mutations ---
        # Increased lookback for better statistical relevance
        self.lookback = 30
        self.max_positions = 3             # Lower concentration to select only best setups
        
        # Strict Filters to fix 'EXPLORE', 'STAGNANT'
        self.min_liquidity = 500000.0      # Significantly increased liquidity requirement
        self.min_volatility = 0.008        # Require sufficient volatility (0.8% CV)
        
        # Entry Logic (Stricter to fix 'DIP_BUY', 'MEAN_REVERSION')
        self.entry_z_score = 3.5           # Require 3.5 std dev dip (Extreme anomaly)
        self.entry_rsi = 25.0              # Deep oversold condition
        self.crash_filter_pct = -15.0      # Avoid assets crashing > 15% 24h (Anti-Falling Knife)
        
        # Exit Logic (Fixes 'TIME_DECAY', 'STOP_LOSS')
        self.max_hold_ticks = 6            # Fast rotation (Scalp focus)
        self.stagnant_ticks = 3            # Exit quickly if price stalls
        self.stop_loss_pct = 0.05          # Hard stop
        self.min_profit_pct = 0.02         # Base take profit

    def _calculate_rsi(self, prices):
        if len(prices) < 14:
            return 50.0
        
        gains = []
        losses = []
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(delta))
                
        if not gains: return 0.0
        if not losses: return 100.0
        
        avg_gain = sum(gains[-14:]) / 14
        avg_loss = sum(losses[-14:]) / 14
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # 1. Data Ingestion & Cleanup
        current_symbols = set(prices.keys())
        for s in list(self.symbol_data.keys()):
            if s not in current_symbols:
                del self.symbol_data[s]

        candidates = []
        for symbol, data in prices.items():
            # Liquidity Filter
            if data["liquidity"] < self.min_liquidity:
                continue
                
            price = data["priceUsd"]
            
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = deque(maxlen=self.lookback)
            
            self.symbol_data[symbol].append(price)
            
            if len(self.symbol_data[symbol]) == self.lookback:
                candidates.append(symbol)

        # 2. Position Management (Exits)
        # Priority: Fix TIME_DECAY and STAGNANT
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            ticks_held = self.tick_counter - pos["entry_tick"]
            amount = pos["amount"]
            entry_price = pos["entry_price"]
            
            roi = (current_price - entry_price) / entry_price
            
            exit_reason = None
            
            # Stop Loss
            if roi <= -self.stop_loss_pct:
                exit_reason = "STOP_LOSS"
            # Take Profit
            elif roi >= self.min_profit_pct:
                exit_reason = "TAKE_PROFIT"
            # Time Limit
            elif ticks_held >= self.max_hold_ticks:
                exit_reason = "TIME_LIMIT"
            # Stagnation Check (Exit if flat for 3 ticks)
            elif ticks_held >= self.stagnant_ticks and abs(roi) < 0.003:
                exit_reason = "STAGNANT"
                
            if exit_reason:
                self.balance += (amount * current_price)
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': [exit_reason]
                }

        # 3. Entry Evaluation
        if len(self.positions) >= self.max_positions:
            return None
            
        opportunities = []
        
        for symbol in candidates:
            if symbol in self.positions: continue
            
            hist = list(self.symbol_data[symbol])
            current_price = hist[-1]
            prev_price = hist[-2]
            
            # --- Mutation: Green Tick Confirmation ---
            # To avoid 'BREAKOUT' (downside) and Catching Knives.
            # Only enter if the current tick is >= previous tick (Stabilization)
            if current_price < prev_price:
                continue

            # --- Macro Filter ---
            # Avoid assets that are crashing too hard in 24h context
            if prices[symbol]['priceChange24h'] < self.crash_filter_pct:
                continue

            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            if stdev == 0 or mean == 0: continue
            
            # Volatility Filter (Avoid 'STAGNANT' traps)
            cov = stdev / mean
            if cov < self.min_volatility: continue
            
            z_score = (current_price - mean) / stdev
            
            # Signal: Extreme Z-Score + Low RSI
            if z_score < -self.entry_z_score:
                rsi = self._calculate_rsi(hist)
                if rsi < self.entry_rsi:
                    # Score opportunity by volatility (higher vol = faster bounce)
                    score = abs(z_score) * cov
                    opportunities.append((symbol, score, current_price))
        
        # Sort by signal strength
        opportunities.sort(key=lambda x: x[1], reverse=True)
        
        if opportunities:
            symbol, _, price = opportunities[0]
            
            # Position Sizing
            slots = self.max_positions - len(self.positions)
            # Use 98% of slot allocation to be safe
            balance_share = (self.balance / slots) * 0.98
            amount = balance_share / price
            
            self.positions[symbol] = {
                "entry_price": price,
                "amount": amount,
                "entry_tick": self.tick_counter
            }
            self.balance -= (amount * price)
            
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': amount,
                'reason': ['SNIPER_DIP']
            }
            
        return None