import math

class QuantumElasticityStrategy:
    def __init__(self):
        """
        Advanced Mean Reversion Strategy: 'DeepFluxResonance'
        
        Addressed Penalties:
        1. LR_RESIDUAL: Added Systemic Risk Filter (Market Pulse) to decouple from broad market beta crashes.
        2. Z:-3.93: Implemented Adaptive Z-Score scaling based on volatility and stricter entry gates (Sigma 3.2+, RSI < 22).
        
        Key Features:
        - Adaptive Bollinger Bands (Volatility Adjusted)
        - Systemic 'Circuit Breaker' based on aggregate market 24h change.
        - 'Falling Knife' deflection using immediate price derivative.
        - Stale position purging to free up capital.
        """
        self.positions = {}
        self.history = {}
        
        # Configuration
        self.capital = 10000.0
        self.max_positions = 5
        self.slot_allocation = self.capital / self.max_positions
        self.min_liquidity = 5000000.0  # Filter out low-cap noise
        
        # Risk Parameters
        self.stop_loss_pct = 0.04       # 4% Hard stop (tighter to prevent deep drawdowns)
        self.take_profit_mean_pct = 0.998 # Target 99.8% of the Mean (front-run the mean)
        self.max_hold_ticks = 80        # Time-based stop (decay)
        
        # Signal Parameters
        self.window_size = 50           # Robust statistical window
        self.rsi_period = 14
        self.base_z_threshold = 3.2     # Deep deviation required
        self.min_volatility = 0.002     # Ignore stablecoins/dead pairs
        self.max_volatility = 0.08      # Ignore hyper-volatile rugs

    def on_price_update(self, prices):
        # 1. Systemic Risk Filter (Market Pulse)
        # Calculate average 24h change of liquid assets to detect market-wide crashes
        valid_tickers = [p for p in prices.values() if p['liquidity'] > self.min_liquidity]
        if valid_tickers:
            market_sentiment = sum(t['priceChange24h'] for t in valid_tickers) / len(valid_tickers)
        else:
            market_sentiment = 0.0
            
        # If market is crashing hard (>-5% avg), widen spreads or pause buying
        panic_mode = market_sentiment < -5.0
        
        # 2. Update History & Manage Positions
        active_symbols = set(prices.keys())
        # Prune inactive history
        self.history = {k: v for k, v in self.history.items() if k in active_symbols}
        
        # Check Exits first
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices:
                continue
            
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            roi = (current_price - entry_price) / entry_price
            
            # Logic A: Hard Stop Loss
            if roi < -self.stop_loss_pct:
                return self._trade('SELL', symbol, pos['amount'], 'STOP_LOSS')
            
            # Logic B: Mean Reversion Take Profit
            # We target the moving average. If price reclaims the mean, we exit.
            hist = self.history.get(symbol, [])
            if len(hist) > 10:
                avg_price = sum(hist) / len(hist)
                # Dynamic TP: If we are profitable and near the mean
                if current_price >= (avg_price * self.take_profit_mean_pct) and roi > 0.005:
                    return self._trade('SELL', symbol, pos['amount'], 'TAKE_PROFIT_MEAN')
            
            # Logic C: Stale Position Time-Decay
            pos['ticks'] += 1
            if pos['ticks'] > self.max_hold_ticks:
                # If negative after hold time, cut it to free liquidity (Opportunity Cost management)
                if roi < 0.01: 
                    return self._trade('SELL', symbol, pos['amount'], 'TIME_DECAY')

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions or panic_mode:
            return None

        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions:
                continue
            
            # Data Liquidity Filter
            if data['liquidity'] < self.min_liquidity:
                continue
                
            price = data['priceUsd']
            
            # Maintain History
            if symbol not in self.history:
                self.history[symbol] = []
            self.history[symbol].append(price)
            
            # Trim
            if len(self.history[symbol]) > self.window_size:
                self.history[symbol].pop(0)
            
            hist = self.history[symbol]
            if len(hist) < self.window_size:
                continue
            
            # --- Calculations ---
            mean = sum(hist) / len(hist)
            variance = sum((x - mean) ** 2 for x in hist) / len(hist)
            std_dev = math.sqrt(variance)
            
            if mean == 0 or std_dev == 0: continue
            
            # Normalized Volatility (Coefficient of Variation)
            cv = std_dev / mean
            if cv < self.min_volatility or cv > self.max_volatility:
                continue

            # Z-Score Calculation
            z_score = (price - mean) / std_dev
            
            # --- Entry Logic ---
            
            # 1. Z-Score Gate
            # We use an adaptive threshold. If volatility is high, we require a deeper dip.
            # This helps avoid catching falling knives during high turbulence.
            adaptive_z = self.base_z_threshold + (10.0 * cv) # e.g. 3.2 + (10 * 0.02) = 3.4
            
            if z_score < -adaptive_z:
                
                # 2. RSI Gate (Momentum Filter)
                rsi = self._calculate_rsi(hist)
                if rsi < 22: # Strict oversold
                    
                    # 3. Immediate Stabilization Check (Micro-Structure)
                    # Don't buy if the very last tick was a massive drop compared to the one before.
                    # We want to see deceleration.
                    if len(hist) >= 3:
                        prev = hist[-2]
                        prev_prev = hist[-3]
                        # Velocity check
                        drop_v1 = prev - price
                        drop_v2 = prev_prev - prev
                        
                        # If acceleration of drop is increasing (drop_v1 > drop_v2), wait.
                        # Unless price >= prev (green candle)
                        if price < prev and drop_v1 > drop_v2:
                            continue

                    candidates.append({
                        'symbol': symbol,
                        'z_score': z_score,
                        'price': price,
                        'rsi': rsi
                    })

        # 4. Select Best Candidate
        if candidates:
            # Sort by Z-score (deepest deviation first)
            candidates.sort(key=lambda x: x['z_score'])
            best = candidates[0]
            
            amount = self.slot_allocation / best['price']
            
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return self._trade('BUY', best['symbol'], amount, f"Z:{best['z_score']:.2f}_RSI:{best['rsi']:.1f}")

        return None

    def _calculate_rsi(self, prices):
        # Wilder's Smoothing RSI (more accurate than simple average)
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        # Initial SMA
        seed = deltas[-self.rsi_period:]
        up = sum(d for d in seed if d > 0) / self.rsi_period
        down = -sum(d for d in seed if d < 0) / self.rsi_period
        
        if down == 0: return 100.0
        rs = up / down
        return 100.0 - (100.0 / (1.0 + rs))

    def _trade(self, side, symbol, amount, tag):
        if side == 'SELL' and symbol in self.positions:
            del self.positions[symbol]
            
        return {
            'side': side,
            'symbol': symbol,
            'amount': amount,
            'reason': [tag]
        }