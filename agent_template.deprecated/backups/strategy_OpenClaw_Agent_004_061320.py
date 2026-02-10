import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Bollinger Mean Reversion (Volatility-Adjusted)
        Fixes:
        - Replaces BREAKOUT/Z_BREAKOUT with Volatility Band Mean Reversion.
        - Replaces TRAIL_STOP with fixed Bracket Orders (SL/TP).
        - Improves ER by requiring confluence of RSI and Band penetration.
        """
        self.lookback_period = 20
        self.max_positions = 5
        self.capital_per_trade = 500.0
        
        # --- Filters ---
        self.min_liquidity = 2000000.0    # Increased liquidity filter
        self.min_volume = 1000000.0       # Increased volume filter
        self.max_drop_24h = -0.15         # Avoid total collapses (>15% drop)
        
        # --- Entry Parameters ---
        # Confluence: Price < Lower Band AND RSI < Threshold
        self.bb_std_dev = 2.1             # 2.1 StdDev (Stricter than 2.0)
        self.rsi_threshold = 30.0         # Oversold threshold
        
        # --- Exit Parameters (Fixed Risk) ---
        self.take_profit_pct = 0.055      # Target 5.5% Gain
        self.stop_loss_pct = 0.025        # Cap loss at 2.5% (Tight fixed stop)
        self.max_hold_ticks = 20          # Time-based exit
        
        # --- State ---
        self.price_history = {}
        self.positions = {}

    def _calculate_indicators(self, data):
        """
        Computes SMA, Lower Bollinger Band, and RSI.
        """
        if len(data) < self.lookback_period:
            return None
            
        # Slicing the window
        window = list(data)[-self.lookback_period:]
        
        # 1. Bollinger Bands
        sma = sum(window) / len(window)
        variance = sum((x - sma) ** 2 for x in window) / len(window)
        std_dev = math.sqrt(variance)
        lower_band = sma - (std_dev * self.bb_std_dev)
        
        # 2. RSI (Simple Averaging)
        gains = 0.0
        losses = 0.0
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains += delta
            else:
                losses += abs(delta)
        
        if losses == 0:
            rsi = 100.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'lower_band': lower_band,
            'rsi': rsi,
            'std_dev': std_dev
        }

    def on_price_update(self, prices):
        # 1. Prune Data & Update History
        active_symbols = set(prices.keys())
        for symbol in list(self.price_history.keys()):
            if symbol not in active_symbols:
                del self.price_history[symbol]
                
        for symbol, meta in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.lookback_period + 5)
            self.price_history[symbol].append(meta["priceUsd"])

        # 2. Manage Existing Positions (Exits)
        # Using list() to allow modification of dict during iteration
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            
            roi = (current_price - entry_price) / entry_price
            pos['ticks'] += 1
            
            action = None
            reason = None
            
            # Priority 1: Fixed Stop Loss (Risk Control)
            if roi <= -self.stop_loss_pct:
                action = 'SELL'
                reason = 'FIXED_STOP'
                
            # Priority 2: Take Profit (Target)
            elif roi >= self.take_profit_pct:
                action = 'SELL'
                reason = 'TAKE_PROFIT'
                
            # Priority 3: Time Expiration (Stale Trade)
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

        # 3. Scan for New Entries (Confluence of BB + RSI)
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, meta in prices.items():
            # Skip if already in position
            if symbol in self.positions:
                continue
                
            # Filters: High Quality Assets Only
            if meta["liquidity"] < self.min_liquidity:
                continue
            if meta.get("volume24h", 0) < self.min_volume:
                continue
            # Avoid falling knives that are crashing too hard
            if meta.get("priceChange24h", 0) < self.max_drop_24h:
                continue
                
            # Data sufficiency check
            history = self.price_history.get(symbol)
            if not history or len(history) < self.lookback_period:
                continue
                
            # Calculate Technicals
            indicators = self._calculate_indicators(history)
            if not indicators:
                continue
                
            current_price = meta["priceUsd"]
            
            # STRATEGY LOGIC:
            # 1. Price penetration below Lower Bollinger Band (Mean Reversion setup)
            # 2. RSI is Oversold (Confirmation of momentum exhaustion)
            
            if current_price < indicators['lower_band']:
                if indicators['rsi'] < self.rsi_threshold:
                    # Score by depth of deviation (lower is better for entry)
                    # We normalize score by RSI to prioritize most oversold
                    candidates.append({
                        'symbol': symbol,
                        'price': current_price,
                        'rsi': indicators['rsi'],
                        'deviation': (current_price - indicators['lower_band']) / indicators['std_dev']
                    })

        # 4. Execute Best Trade
        if candidates:
            # Sort by RSI (Lowest RSI = Best Mean Reversion Candidate)
            # Secondary sort could be deviation depth
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
                'reason': ['BB_REVERSION', f"RSI:{best['rsi']:.1f}"]
            }

        return None