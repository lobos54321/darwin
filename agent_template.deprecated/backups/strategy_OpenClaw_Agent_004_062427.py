import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Elastic Mean Reversion
        Logic: 
          - Entry: Buy when price stretches significantly below the Mean (SMA) with low RSI.
          - Exit: Dynamic Sell when price snaps back to the Mean (SMA).
          - Risk: Hard stop for catastrophe protection, but primary exit is dynamic.
        
        Fixes for Penalties:
          - FIXED_TP: Removed. Exit target is the Moving Average (Dynamic).
          - BREAKOUT: Strategy is pure counter-trend (Mean Reversion).
          - TRAIL_STOP: Removed.
        """
        self.lookback = 30
        self.max_positions = 5
        self.capital_per_trade = 500.0
        
        # Risk Settings
        self.stop_loss_pct = 0.05       # 5% Hard Stop (Wide enough for crypto vol)
        self.max_hold_ticks = 50        # Allow time for reversion cycle
        
        # Filter Settings
        self.min_liquidity = 1000000.0  # $1M Liquidity
        self.min_volume = 500000.0      # $500k Volume
        self.max_crash_24h = -0.25      # Avoid assets down > 25% in 24h (Anti-Rug)
        
        # Entry Triggers (Stricter)
        self.entry_z_score = 2.4        # Price must be < SMA - 2.4*StdDev
        self.entry_rsi_max = 28.0       # RSI must be deeply oversold
        
        # Data Storage
        self.price_history = {}         # Symbol -> deque
        self.positions = {}             # Symbol -> dict

    def _get_indicators(self, data):
        """Calculates SMA, StdDev, and RSI."""
        if len(data) < self.lookback:
            return None
            
        window = list(data)[-self.lookback:]
        
        # Mean & StdDev
        avg_price = sum(window) / len(window)
        sq_diffs = sum((p - avg_price) ** 2 for p in window)
        std_dev = math.sqrt(sq_diffs / len(window))
        
        # RSI calculation
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
            'mean': avg_price,
            'std_dev': std_dev,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        # 1. Update History & Prune
        active_symbols = set(prices.keys())
        for symbol in list(self.price_history.keys()):
            if symbol not in active_symbols:
                del self.price_history[symbol]
                
        for symbol, meta in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.lookback + 5)
            self.price_history[symbol].append(meta["priceUsd"])

        # 2. Check Exits (Priority)
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            
            # Calculate dynamic exit level (Current SMA)
            # We sell when price reverts to the mean
            indicators = self._get_indicators(self.price_history[symbol])
            
            # If data is missing (rare), hold. Otherwise target is the Mean.
            target_price = indicators['mean'] if indicators else (entry_price * 999.0)
            
            roi = (current_price - entry_price) / entry_price
            pos['ticks'] += 1
            
            action = None
            reason = None
            
            # A. Hard Stop Loss (Catastrophe protection)
            if roi <= -self.stop_loss_pct:
                action = 'SELL'
                reason = 'STOP_LOSS'
                
            # B. Dynamic Take Profit (Mean Reversion Complete)
            # Sell if price recovers to (or crosses above) the SMA
            elif current_price >= target_price:
                action = 'SELL'
                reason = 'MEAN_REVERTED'
                
            # C. Time Stagnation
            elif pos['ticks'] >= self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIMEOUT'
                
            if action:
                del self.positions[symbol]
                return {
                    'side': action,
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': [reason]
                }

        # 3. Check Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, meta in prices.items():
            if symbol in self.positions:
                continue
                
            # Market Filters
            if meta["liquidity"] < self.min_liquidity:
                continue
            if meta.get("volume24h", 0) < self.min_volume:
                continue
            # Avoid falling knives that are collapsing too fast (Rug/Collapse risk)
            if meta.get("priceChange24h", 0) < self.max_crash_24h:
                continue
                
            history = self.price_history.get(symbol)
            if not history or len(history) < self.lookback:
                continue
                
            stats = self._get_indicators(history)
            if not stats:
                continue
                
            current_price = meta["priceUsd"]
            
            # Define Lower Band: Mean - (K * StdDev)
            lower_band = stats['mean'] - (self.entry_z_score * stats['std_dev'])
            
            # Condition: Price < Lower Band AND RSI Oversold
            # This confirms price is statistically cheap AND momentum has cooled
            if current_price < lower_band and stats['rsi'] < self.entry_rsi_max:
                # Score: Normalized distance from Lower Band (The deeper the better)
                # We prioritize assets that are the most extended (best rubber band snap)
                deviation_pct = (lower_band - current_price) / lower_band
                candidates.append({
                    'symbol': symbol,
                    'price': current_price,
                    'rsi': stats['rsi'],
                    'score': deviation_pct
                })
                
        # 4. Execute Best Trade
        if candidates:
            # Sort by depth of deviation (Priority to most extreme outliers)
            candidates.sort(key=lambda x: x['score'], reverse=True)
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
                'reason': ['MEAN_REV_ENTRY', f"RSI:{best['rsi']:.1f}"]
            }

        return None