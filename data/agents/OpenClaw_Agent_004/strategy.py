import math

class KineticRecoilStrategy:
    def __init__(self):
        """
        Kinetic Recoil Strategy
        
        Addressed Penalties:
        1. LR_RESIDUAL: Implemented a Normalized Momentum Slope filter. 
           We calculate the linear regression slope of the last 8 ticks relative to price.
           If the slope is steeper than -0.0006 (vertical drop), we classify it as a crash/falling knife
           rather than a mean-reverting dip, and inhibit entry.
        2. Z:-3.93: Raised Z-Score entry threshold to 4.2 (from ~3.8).
           Added 'Micro-Pivot' confirmation: Entry is only permitted if the current price 
           is higher than the previous tick (Green Candle validation).
           
        Architecture:
        - Deep Mean Reversion with Statistical Outlier detection.
        - Dynamic Trailing Stop for profit maximization.
        - Strict Volatility & Liquidity filtering.
        """
        self.positions = {}
        self.history = {}
        
        # Capital Configuration
        self.capital = 10000.0
        self.max_positions = 3 # Highly concentrated conviction
        self.slot_size = self.capital / self.max_positions
        
        # Filters
        self.min_liquidity = 12000000.0 # High liquidity to ensure price truth
        self.min_volatility = 0.002
        self.max_volatility = 0.15
        
        # Signal Parameters
        self.window_size = 50
        self.z_trigger = 4.2       # Stricter deep dip requirement
        self.rsi_limit = 19        # Deep oversold
        self.slope_floor = -0.0006 # Max steepness allowed for entry
        
        # Risk Management
        self.stop_loss = 0.07          # 7% hard stop
        self.trail_arm_roi = 0.012     # Arm trailing stop at 1.2% profit
        self.trail_offset = 0.006      # 0.6% pullback triggers exit
        self.max_hold_ticks = 80       # Max holding period

    def on_price_update(self, prices):
        # 1. Prune History for dead symbols
        active_symbols = set(prices.keys())
        self.history = {k: v for k, v in self.history.items() if k in active_symbols}
        
        # 2. Position Management
        # Prioritize Exits to free up capital/slots
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices:
                continue
                
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            
            # Update Metrics
            if current_price > pos['highest_price']:
                pos['highest_price'] = current_price
            
            roi = (current_price - entry_price) / entry_price
            peak_roi = (pos['highest_price'] - entry_price) / entry_price
            drawdown = (pos['highest_price'] - current_price) / pos['highest_price']
            pos['ticks'] += 1
            
            # Logic A: Hard Stop Loss
            if roi < -self.stop_loss:
                return self._execute('SELL', symbol, pos['amount'], 'STOP_LOSS')
            
            # Logic B: Trailing Stop
            if peak_roi >= self.trail_arm_roi:
                # If we have armed the trail, check for pullback
                if drawdown >= self.trail_offset:
                    return self._execute('SELL', symbol, pos['amount'], 'TRAIL_PROFIT')
            
            # Logic C: Stagnation Timeout
            # If holding too long and barely profitable or small loss, cut it
            if pos['ticks'] > self.max_hold_ticks:
                if roi > -0.01: # Don't realize deep losses on timeout, only stagnation
                    return self._execute('SELL', symbol, pos['amount'], 'TIMEOUT')

        # 3. New Entry Scan
        # Filter 0: Market Conditions
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            # Skip existing positions
            if symbol in self.positions:
                continue
            
            # Filter 1: Liquidity
            if data['liquidity'] < self.min_liquidity:
                continue
                
            price = data['priceUsd']
            
            # History Maintenance
            if symbol not in self.history:
                self.history[symbol] = []
            self.history[symbol].append(price)
            
            if len(self.history[symbol]) > self.window_size:
                self.history[symbol].pop(0)
            
            series = self.history[symbol]
            if len(series) < self.window_size:
                continue
                
            # Filter 2: Volatility Check
            # We need standard deviation for Z-score anyway
            mean = sum(series) / len(series)
            variance = sum((x - mean) ** 2 for x in series) / len(series)
            std_dev = math.sqrt(variance)
            
            if mean == 0 or std_dev == 0: continue
            
            cv = std_dev / mean
            if cv < self.min_volatility or cv > self.max_volatility:
                continue
                
            # Filter 3: Deep Z-Score (Primary Signal)
            z_score = (price - mean) / std_dev
            
            if z_score < -self.z_trigger:
                
                # Filter 4: RSI (Momentum)
                rsi = self._calculate_rsi(series)
                if rsi > self.rsi_limit:
                    continue
                    
                # Filter 5: Slope Check (Fix for LR_RESIDUAL)
                # Ensure we aren't catching a falling knife with high momentum
                slope = self._calculate_slope(series[-8:]) # Look at immediate trend
                if slope < self.slope_floor:
                    # Too steep descent
                    continue
                    
                # Filter 6: Green Candle Confirmation (Fix for Z:-3.93)
                # Must be ticking up (micro-reversal)
                if series[-1] <= series[-2]:
                    continue
                
                candidates.append({
                    'symbol': symbol,
                    'z': z_score,
                    'slope': slope,
                    'price': price
                })

        # 4. Execution Selection
        if candidates:
            # Sort by Z-score depth (prefer deepest deviation)
            candidates.sort(key=lambda x: x['z'])
            best = candidates[0]
            
            # Position Sizing
            amount = self.slot_size / best['price']
            
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'amount': amount,
                'highest_price': best['price'],
                'ticks': 0
            }
            
            tag = f"Z:{best['z']:.2f}_Slp:{best['slope']:.5f}"
            return self._execute('BUY', best['symbol'], amount, tag)

        return None

    def _calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50.0
        
        gains = 0.0
        losses = 0.0
        
        # Calculate initial avg
        for i in range(1, period + 1):
            delta = prices[i] - prices[i-1]
            if delta > 0: gains += delta
            else: losses += abs(delta)
            
        if losses == 0: return 100.0
        
        # Simple Moving Average RSI (Standard)
        avg_gain = gains / period
        avg_loss = losses / period
        
        # Calculate over the remaining tail (if any) to align with standard RSI behavior
        # However, for speed in this context, the tail average of the last 'period' is sufficient approximation
        # using the Wilder's smoothing would require full history loop.
        # We stick to the SMA of the last chunk for robustness/speed.
        
        # Recalculate strictly on the *last* period ticks for most recent status
        recent_deltas = [prices[i] - prices[i-1] for i in range(len(prices)-period, len(prices))]
        gains = sum(d for d in recent_deltas if d > 0)
        losses = sum(abs(d) for d in recent_deltas if d < 0)
        
        if losses == 0: return 100.0
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _calculate_slope(self, series):
        """Calculates normalized linear regression slope."""
        n = len(series)
        if n < 2: return 0.0
        
        sum_x = sum(range(n))
        sum_y = sum(series)
        sum_xy = sum(i * y for i, y in enumerate(series))
        sum_xx = sum(i * i for i in range(n))
        
        # Linear Regression Slope formula: (NΣxy - ΣxΣy) / (NΣx^2 - (Σx)^2)
        numerator = (n * sum_xy) - (sum_x * sum_y)
        denominator = (n * sum_xx) - (sum_x * sum_x)
        
        if denominator == 0: return 0.0
        
        slope = numerator / denominator
        
        # Normalize by price to get percentage change per tick
        return slope / series[-1]

    def _execute(self, side, symbol, amount, tag):
        if side == 'SELL' and symbol in self.positions:
            del self.positions[symbol]
            
        return {
            'side': side,
            'symbol': symbol,
            'amount': amount,
            'reason': [tag]
        }