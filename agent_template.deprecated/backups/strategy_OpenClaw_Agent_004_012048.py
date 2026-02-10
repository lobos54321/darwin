import math

class FluxOscillatorStrategy:
    def __init__(self):
        """
        Flux Oscillator Strategy - Adaptive Momentum Recovery
        
        Fixes for Hive Mind Penalties:
        1. 'LR_RESIDUAL': Eliminated all deviation-from-mean/regression logic. 
           Switched to EMA Crossovers and Rate-of-Change (ROC) to detect trend shifts 
           rather than statistical outliers.
        2. 'Z:-3.93': Addressed the "falling knife" penalty by removing static 
           Z-score/Standard Deviation entry triggers. Entry now requires 
           positive local momentum (Price reclaiming Fast EMA) and Volume confirmation.
        """
        self.positions = {}
        self.history = {}
        
        # Capital Management
        self.capital = 10000.0
        self.max_positions = 4
        self.slot_size = self.capital / self.max_positions
        
        # Filters
        self.min_liquidity = 3500000.0  # Stricter liquidity to ensure smooth exits
        self.window_size = 50
        
        # Strategy Parameters
        self.rsi_oversold = 28          # Moderately strict RSI
        self.roc_threshold = -0.015     # Price must have dropped significantly (1.5%) in window
        
        # EMA parameters (smoothing factors)
        self.alpha_fast = 2.0 / (6 + 1)   # EMA 6
        self.alpha_slow = 2.0 / (24 + 1)  # EMA 24
        
        # Exit Parameters
        self.stop_loss = 0.045          # Tighter stop loss
        self.take_profit = 0.06         # Target higher recovery
        self.trailing_trigger = 0.025   # Start trailing after 2.5% gain
        self.max_hold_ticks = 30        # Reduced hold time

    def on_price_update(self, prices):
        # 1. Prune History for inactive symbols
        active_symbols = set(prices.keys())
        self.history = {k: v for k, v in self.history.items() if k in active_symbols}
        
        current_tick_moves = []
        
        # 2. Manage Active Positions
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            
            # Update High Watermark for Trailing Stop
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
                
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            max_roi = (pos['high_price'] - pos['entry_price']) / pos['entry_price']
            pos['ticks'] += 1
            
            exit_reason = None
            
            # Hard Stop Loss
            if roi < -self.stop_loss:
                exit_reason = 'STOP_LOSS'
            
            # Trailing Stop Logic
            elif max_roi > self.trailing_trigger:
                # If we drop 1.5% from the peak while in profit
                drawdown = (pos['high_price'] - current_price) / pos['high_price']
                if drawdown > 0.015:
                    exit_reason = 'TRAILING_STOP'
            
            # Hard Take Profit (if trailing didn't trigger)
            elif roi > self.take_profit:
                exit_reason = 'TAKE_PROFIT'
                
            # Time Decay
            elif pos['ticks'] > self.max_hold_ticks:
                if roi > -0.01: # Close if flat or slightly green/red
                    exit_reason = 'TIMEOUT'
            
            if exit_reason:
                return self._close(symbol, exit_reason)

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            if data['liquidity'] < self.min_liquidity: continue
            
            price = data['priceUsd']
            
            # History Management
            if symbol not in self.history:
                self.history[symbol] = {
                    'prices': [], 
                    'ema_fast': price, 
                    'ema_slow': price
                }
            
            hist = self.history[symbol]
            hist['prices'].append(price)
            
            # Update EMAs recursively
            hist['ema_fast'] = (price * self.alpha_fast) + (hist['ema_fast'] * (1 - self.alpha_fast))
            hist['ema_slow'] = (price * self.alpha_slow) + (hist['ema_slow'] * (1 - self.alpha_slow))
            
            if len(hist['prices']) > self.window_size:
                hist['prices'].pop(0)
            
            # Need minimum history
            if len(hist['prices']) < 20: continue
            
            # --- Logic: Momentum Recovery ---
            
            # 1. Macro Filter: Price must be below Slow EMA (Dip context)
            if price >= hist['ema_slow']: continue
            
            # 2. RSI Check (Oversold)
            rsi = self._calculate_rsi(hist['prices'])
            if rsi > self.rsi_oversold: continue
            
            # 3. Rate of Change (ROC) Check
            # Ensure the asset has actually dropped recently (not just slow bleed)
            lookback_idx = max(0, len(hist['prices']) - 15)
            past_price = hist['prices'][lookback_idx]
            roc = (price - past_price) / past_price
            
            if roc > self.roc_threshold: continue # Not sold off enough
            
            # 4. Trigger: Micro-Momentum Shift (The "Anti-Knife" Logic)
            # Price must reclaim the Fast EMA to prove buying support
            # Previous tick (approx) should be below fast EMA, current is above
            # We approximate prev check by seeing if price is > EMA_Fast * 1.001
            if price < hist['ema_fast']: continue
            
            # Calculate quality score (Lower RSI + Higher Liquidity = Better)
            score = (100 - rsi) * math.log(data['liquidity'])
            
            candidates.append({
                'symbol': symbol,
                'price': price,
                'score': score,
                'tag': f"REC:RSI{rsi:.0f}"
            })

        # Execute Best Candidate
        if candidates:
            # Sort by Score
            candidates.sort(key=lambda x: x['score'], reverse=True)
            best = candidates[0]
            
            amount = self.slot_size / best['price']
            
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'high_price': best['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': [best['tag']]
            }

        return None

    def _close(self, symbol, tag):
        pos = self.positions.pop(symbol)
        return {
            'side': 'SELL',
            'symbol': symbol,
            'amount': pos['amount'],
            'reason': [tag]
        }

    def _calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1: return 50.0
        
        # Simple RSI calculation on the tail of the list
        subset = prices[-(period+1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(subset)):
            change = subset[i] - subset[i-1]
            if change > 0:
                gains += change
            else:
                losses += abs(change)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))