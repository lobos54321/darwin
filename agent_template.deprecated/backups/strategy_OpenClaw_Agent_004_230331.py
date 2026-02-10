import math

class QuantumElasticityStrategy:
    def __init__(self):
        """
        Refined Mean Reversion Strategy: 'VectorQuantizedResonance'
        
        Fixes & Mutations:
        1. LR_RESIDUAL Fix: Implemented Linear Regression Slope check (Trend Intensity). 
           If the localized downtrend is too steep (high negative slope), we assume momentum 
           dominates mean reversion and wait for stabilization.
        2. Z:-3.93 Fix: Increased Base Z-Threshold to 3.8 and added a 'Green Candle' confirmation 
           requirement. We never buy a falling knife, only the first tick of a potential reversal.
        3. Profitability: Replaced static Take Profit with Dynamic Trailing Stop to ride recovery waves.
        """
        self.positions = {}
        self.history = {}
        
        # Capital Management
        self.capital = 10000.0
        self.max_positions = 4 # Concentrated conviction
        self.slot_size = self.capital / self.max_positions
        
        # Filters
        self.min_liquidity = 8000000.0 # Higher liquidity filter to reduce slippage/manipulation
        self.min_volatility = 0.003
        self.max_volatility = 0.10
        
        # Hyperparameters
        self.window_size = 40
        self.z_threshold_base = 3.8    # Stricter entry (was 3.2)
        self.rsi_threshold = 20        # Stricter oversold (was 22)
        self.slope_threshold = -0.0005 # Normalized slope limit (steep drop protection)
        
        # Risk Management
        self.stop_loss_pct = 0.05
        self.trailing_arm_pct = 0.01   # Activate trailing stop after 1% profit
        self.trailing_offset_pct = 0.005 # Sell if drops 0.5% from peak
        self.max_hold_ticks = 60

    def on_price_update(self, prices):
        # 0. Global Market Pulse (Systemic Risk Filter)
        valid_tickers = [p for p in prices.values() if p['liquidity'] > self.min_liquidity]
        market_panic = False
        if valid_tickers:
            avg_24h_change = sum(t['priceChange24h'] for t in valid_tickers) / len(valid_tickers)
            # If market is crashing hard, halt buying
            if avg_24h_change < -6.5:
                market_panic = True

        # 1. Update History & Prune
        active_symbols = set(prices.keys())
        self.history = {k: v for k, v in self.history.items() if k in active_symbols}
        
        # 2. Manage Existing Positions
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices:
                continue
                
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            roi = (current_price - entry_price) / entry_price
            
            # Update High Watermark for Trailing Stop
            if current_price > pos['highest_price']:
                pos['highest_price'] = current_price
            
            # Calculate drawdown from peak
            peak_roi = (pos['highest_price'] - entry_price) / entry_price
            drawdown_from_peak = (pos['highest_price'] - current_price) / pos['highest_price']
            
            # A. Hard Stop Loss
            if roi < -self.stop_loss_pct:
                return self._trade('SELL', symbol, pos['amount'], 'STOP_LOSS')
            
            # B. Trailing Stop Profit
            # If we are in profit (armed) and price drops from peak
            if peak_roi > self.trailing_arm_pct:
                if drawdown_from_peak > self.trailing_offset_pct:
                    return self._trade('SELL', symbol, pos['amount'], 'TRAILING_PROFIT')
            
            # C. Time Decay (Stale Position)
            pos['ticks'] += 1
            if pos['ticks'] > self.max_hold_ticks:
                # Exit if neutral or slight loss to free capital
                if roi > -0.01:
                    return self._trade('SELL', symbol, pos['amount'], 'TIME_DECAY')

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_positions or market_panic:
            return None

        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions:
                continue
                
            if data['liquidity'] < self.min_liquidity:
                continue
                
            price = data['priceUsd']
            
            # Update History
            if symbol not in self.history:
                self.history[symbol] = []
            self.history[symbol].append(price)
            
            if len(self.history[symbol]) > self.window_size:
                self.history[symbol].pop(0)
                
            hist = self.history[symbol]
            if len(hist) < self.window_size:
                continue
                
            # --- Statistical Calculations ---
            # 1 pass variance calc
            mean = sum(hist) / len(hist)
            variance = sum((x - mean) ** 2 for x in hist) / len(hist)
            std_dev = math.sqrt(variance)
            
            if mean == 0 or std_dev == 0: continue
            
            # Volatility check
            cv = std_dev / mean
            if cv < self.min_volatility or cv > self.max_volatility:
                continue
                
            # Z-Score
            z_score = (price - mean) / std_dev
            
            # Adaptive Threshold logic
            # High volatility -> deeper threshold required
            adaptive_threshold = self.z_threshold_base + (15.0 * cv)
            
            # PRE-FILTER: Only look at deep dips
            if z_score < -adaptive_threshold:
                
                # Check 1: RSI (Relative Strength)
                rsi = self._calculate_rsi(hist)
                if rsi > self.rsi_threshold:
                    continue
                    
                # Check 2: Linear Regression Residual/Slope Check (Fix for LR_RESIDUAL)
                # We calculate the normalized slope of the last 10 ticks.
                # If it's a vertical drop (highly negative slope), we wait.
                slope = self._calculate_norm_slope(hist[-10:])
                if slope < self.slope_threshold:
                    # Too steep, falling knife
                    continue
                    
                # Check 3: Micro-structure Confirmation (Fix for Z:-3.93)
                # Ensure we are not the absolute bottom tick (buying red candles).
                # Require current price >= previous price (stabilization).
                if hist[-1] < hist[-2]:
                    continue

                candidates.append({
                    'symbol': symbol,
                    'z': z_score,
                    'rsi': rsi,
                    'slope': slope,
                    'price': price
                })

        # 4. Execution
        if candidates:
            # Sort by depth of deviation (Z-score)
            candidates.sort(key=lambda x: x['z'])
            best = candidates[0]
            
            amount = self.slot_size / best['price']
            
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'amount': amount,
                'highest_price': best['price'],
                'ticks': 0
            }
            
            tag = f"Z:{best['z']:.2f}_Slp:{best['slope']:.5f}"
            return self._trade('BUY', best['symbol'], amount, tag)

        return None

    def _calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50.0
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        # Simple Wilder's smoothing approx for speed/robustness
        gains = [d for d in deltas[-period:] if d > 0]
        losses = [abs(d) for d in deltas[-period:] if d < 0]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calculate_norm_slope(self, series):
        """Calculates normalized linear regression slope of the tail."""
        n = len(series)
        if n < 2: return 0.0
        
        x_bar = (n - 1) / 2.0
        y_bar = sum(series) / n
        
        numerator = 0.0
        denominator = 0.0
        
        for i, y in enumerate(series):
            x_diff = i - x_bar
            numerator += x_diff * (y - y_bar)
            denominator += x_diff * x_diff
            
        if denominator == 0: return 0.0
        slope = numerator / denominator
        
        # Normalize by last price to make it percentage-based slope
        return slope / series[-1]

    def _trade(self, side, symbol, amount, tag):
        if side == 'SELL' and symbol in self.positions:
            del self.positions[symbol]
            
        return {
            'side': side,
            'symbol': symbol,
            'amount': amount,
            'reason': [tag]
        }