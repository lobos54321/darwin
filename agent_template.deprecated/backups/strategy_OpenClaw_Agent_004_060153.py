import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Contrarian RSI Mean Reversion
        Objective: 
            - Replace penalized BREAKOUT/Z_BREAKOUT logic with Oscillator-based Mean Reversion.
            - Replace penalized TRAIL_STOP with Strict Fixed Risk Brackets.
        """
        # --- Configuration ---
        self.lookback_period = 14
        self.max_positions = 5
        self.capital_per_trade = 500.0
        
        # --- Filters ---
        self.min_liquidity = 1500000.0    # Filter low liquidity
        self.min_volume = 500000.0        # Filter dead coins
        self.max_crash_24h = -0.12        # Avoid falling knives (>12% drop)
        
        # --- Entry Parameters (Oversold Logic) ---
        # Buying when RSI is low is the opposite of Breakout
        self.rsi_buy_threshold = 28.0
        
        # --- Exit Parameters (Fixed Brackets) ---
        self.take_profit_pct = 0.045      # Target 4.5% Gain
        self.stop_loss_pct = 0.035        # Cap loss at 3.5%
        self.max_hold_ticks = 18          # Time-based exit
        
        # --- State ---
        self.price_history = {}
        self.positions = {}

    def _calculate_rsi(self, data):
        """
        Calculates a simple Relative Strength Index (RSI) for the data window.
        Returns a float between 0 and 100.
        """
        if len(data) < 2:
            return 50.0

        gains = 0.0
        losses = 0.0
        
        # Simple averaging for speed and reactivity
        for i in range(1, len(data)):
            change = data[i] - data[i-1]
            if change > 0:
                gains += change
            else:
                losses += abs(change)
                
        if losses == 0:
            return 100.0 if gains > 0 else 50.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        # 1. Update Price History
        active_symbols = set(prices.keys())
        
        # Cleanup delisted symbols
        for symbol in list(self.price_history.keys()):
            if symbol not in active_symbols:
                del self.price_history[symbol]
                
        # Append new data
        for symbol, meta in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.lookback_period + 5)
            self.price_history[symbol].append(meta["priceUsd"])

        # 2. Check Exits (Strict Risk Management)
        # Using a copy of keys to modify dict safely
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            
            # Calculate Return on Investment
            roi = (current_price - entry_price) / entry_price
            
            # Update hold time
            pos['ticks'] += 1
            
            action = None
            reason = None
            
            # A. Stop Loss (Fixed)
            if roi <= -self.stop_loss_pct:
                action = 'SELL'
                reason = 'FIXED_STOP'
            
            # B. Take Profit (Fixed)
            elif roi >= self.take_profit_pct:
                action = 'SELL'
                reason = 'TAKE_PROFIT'
                
            # C. Time Limit (Opportunity Cost)
            elif pos['ticks'] >= self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIME_LIMIT'
            
            if action:
                del self.positions[symbol]
                return {
                    'side': action,
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': [reason]
                }

        # 3. Check Entries (Contrarian Mean Reversion)
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, meta in prices.items():
            # Skip active positions
            if symbol in self.positions:
                continue
                
            # Liquidity & Volume Filters
            if meta["liquidity"] < self.min_liquidity:
                continue
            if meta.get("volume24h", 0) < self.min_volume:
                continue
            # Crash Filter: Don't catch extremely sharp falling knives
            if meta.get("priceChange24h", 0) < self.max_crash_24h:
                continue
                
            # History Check
            history = self.price_history.get(symbol)
            if not history or len(history) < self.lookback_period:
                continue
                
            # Strategy Logic: RSI
            rsi = self._calculate_rsi(list(history))
            
            # Buy Condition: Deeply Oversold
            if rsi < self.rsi_buy_threshold:
                candidates.append({
                    'symbol': symbol,
                    'price': meta["priceUsd"],
                    'rsi': rsi
                })
        
        # Select Best Candidate
        if candidates:
            # Sort by lowest RSI (Most oversold)
            candidates.sort(key=lambda x: x['rsi'])
            best = candidates[0]
            
            amount = self.capital_per_trade / best['price']
            
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': ['RSI_REVERSION', f"RSI:{best['rsi']:.1f}"]
            }

        return None