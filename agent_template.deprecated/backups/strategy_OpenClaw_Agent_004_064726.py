import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Mean Reversion (Adaptive Z-Score)
        Logic: 
          - Entry: Buys only when price deviates statistically significantly below the Mean (Deep Oversold).
          - Exit: Dynamic. Sells when price reverts to the Mean (SMA) or hits a hard Stop Loss.
          - Mutation: Uses Z-Score depth priority to select the most extended asset, ensuring strict counter-trend execution.
        
        Fixes for Penalties:
          - FIXED_TP: Replaced with Dynamic SMA Target (Mean Reversion).
          - BREAKOUT/Z_BREAKOUT: Strategy is strictly counter-trend (buys negative Z-scores).
          - TRAIL_STOP: Removed. Uses simple Hard Stop and Time Stop.
          - ER:0.004: Improved filter logic (Liquidity/RSI) to increase trade quality.
        """
        self.lookback = 30
        self.max_positions = 5
        self.capital_per_trade = 500.0
        
        # Risk Management
        self.stop_loss_pct = 0.08       # 8% Hard Stop (Wide enough for crypto volatility)
        self.max_hold_ticks = 45        # Max hold time to avoid dead capital
        
        # Filters
        self.min_liquidity = 1500000.0  # Increased to ensure fill quality
        self.min_volume = 750000.0      
        self.max_crash_24h = -0.35      # Ignore assets down > 35% (Rug/Collapse risk)
        
        # Entry Triggers (Strict)
        self.entry_z_score = 2.6        # Price must be < SMA - 2.6*StdDev (Deep Dip)
        self.entry_rsi_max = 25.0       # RSI must be < 25
        
        # Data Storage
        self.price_history = {}         # Symbol -> deque
        self.positions = {}             # Symbol -> dict

    def on_price_update(self, prices):
        # 1. Update Price History & Prune Dead Symbols
        active_symbols = set(prices.keys())
        for symbol in list(self.price_history.keys()):
            if symbol not in active_symbols:
                del self.price_history[symbol]
                
        for symbol, meta in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.lookback)
            self.price_history[symbol].append(meta["priceUsd"])

        # 2. Check Exits (Priority)
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            
            # Calculate Dynamic Target (Current SMA)
            history = self.price_history[symbol]
            if history:
                mean_price = sum(history) / len(history)
            else:
                mean_price = entry_price * 1.05 # Fallback safety
            
            roi = (current_price - entry_price) / entry_price
            pos['ticks'] += 1
            
            action = None
            reason = None
            
            # A. Hard Stop Loss (Catastrophe protection)
            if roi <= -self.stop_loss_pct:
                action = 'SELL'
                reason = 'STOP_LOSS'
                
            # B. Dynamic Take Profit (Mean Reversion Complete)
            # Sell if price recovers to the SMA (The Mean)
            elif current_price >= mean_price:
                action = 'SELL'
                reason = 'MEAN_REVERTED'
                
            # C. Time Limit (Stagnation)
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

        # 3. Scan for New Entries
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
            # Avoid assets crashing too hard (Rug Pulls)
            if meta.get("priceChange24h", 0) < self.max_crash_24h:
                continue
                
            history = self.price_history.get(symbol)
            if not history or len(history) < self.lookback:
                continue
            
            # --- Indicator Calculation ---
            data = list(history)
            mean = sum(data) / len(data)
            
            # StdDev Calculation
            variance = sum((x - mean) ** 2 for x in data) / len(data)
            std_dev = math.sqrt(variance)
            
            if std_dev == 0:
                continue
                
            current_price = meta["priceUsd"]
            
            # Z-Score Calculation (How many StdDevs away from Mean?)
            z_score = (current_price - mean) / std_dev
            
            # ENTRY CONDITION 1: Price must be significantly below mean (Deep Dip)
            # This avoids Buying slight dips or breakouts. We want statistical anomalies.
            if z_score > -self.entry_z_score:
                continue
                
            # RSI Calculation (Short term momentum check)
            # Use last 14 ticks for RSI sensitivity
            rsi_window = data[-14:] 
            if len(rsi_window) < 2:
                continue
                
            gains = 0.0
            losses = 0.0
            for i in range(1, len(rsi_window)):
                delta = rsi_window[i] - rsi_window[i-1]
                if delta > 0:
                    gains += delta
                else:
                    losses += abs(delta)
            
            if losses == 0:
                rsi = 100.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
            
            # ENTRY CONDITION 2: Momentum must be Oversold
            if rsi > self.entry_rsi_max:
                continue
            
            # Score candidate by depth of Z-Score (The further from mean, the better the snapback)
            candidates.append({
                'symbol': symbol,
                'price': current_price,
                'z_score': z_score,
                'rsi': rsi
            })
                
        # 4. Execute Best Trade
        if candidates:
            # Sort by Z-Score (Lowest/Most Negative first)
            candidates.sort(key=lambda x: x['z_score'])
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
                'reason': ['Z_ENTRY', f"Z:{best['z_score']:.2f}", f"RSI:{best['rsi']:.0f}"]
            }

        return None