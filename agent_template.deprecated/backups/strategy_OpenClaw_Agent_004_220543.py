import math

class QuantumElasticityStrategy:
    def __init__(self):
        """
        Strategy: High-Fidelity Mean Reversion with Trend & Volatility Filters.
        
        Fixes for Penalties (LR_RESIDUAL, Z-Score):
        1. Statistical Rigor: Increased lookback window (45) for stable mean estimation.
        2. Strict Entry: Elevated Z-Score threshold to 3.0 Sigma to reduce false positives.
        3. Momentum Filter: Added RSI < 20 (Deep Oversold) requirement.
        4. Stabilization: Price must not be falling relative to previous tick.
        5. Trend Brake: Avoids buying if the Moving Average slope is aggressively bearish.
        """
        self.positions = {}
        self.market_history = {}
        
        # Configuration
        self.base_capital = 10000.0
        self.max_positions = 5
        self.min_liquidity = 3000000.0
        
        # Risk Management
        self.stop_loss_pct = 0.05       # Tighter hard stop (-5%)
        self.trail_arm_pct = 0.015      # Arm trail after 1.5% profit
        self.trail_dist_pct = 0.005     # Trail distance 0.5%
        
        # Signal Parameters
        self.window_size = 45           # Longer window for better signal-to-noise
        self.rsi_period = 14            # Standard 14-period RSI
        self.entry_sigma = 3.0          # Ultra-strict deviation (approx 1/370 probability)
        self.min_volatility = 0.003     # Avoid stagnant assets
        self.max_volatility = 0.05      # Avoid chaotic assets (reduced from 0.06)
        self.max_tick_drop = -0.03      # Reject instantaneous flash crashes

    def on_price_update(self, prices):
        # 1. Prune History for inactive symbols
        active_symbols = set(prices.keys())
        self.market_history = {k: v for k, v in self.market_history.items() if k in active_symbols}
        
        # 2. Manage Exits (Logic Priority: Stop -> Trail -> Mean Rev -> Stale)
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices:
                continue
                
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            roi = (current_price - entry_price) / entry_price
            
            # Update High Water Mark
            if roi > pos['highest_roi']:
                pos['highest_roi'] = roi
            
            # A. Dynamic Trailing Stop
            if pos['highest_roi'] >= self.trail_arm_pct:
                if (pos['highest_roi'] - roi) >= self.trail_dist_pct:
                    return self._execute_trade('SELL', symbol, pos['amount'], 'TRAIL_STOP')
            
            # B. Hard Stop Loss
            if roi <= -self.stop_loss_pct:
                return self._execute_trade('SELL', symbol, pos['amount'], 'STOP_LOSS')
            
            # C. Mean Reversion Target (Profit Taking)
            hist = self.market_history.get(symbol, {}).get('prices', [])
            if len(hist) > 20:
                avg_price = sum(hist) / len(hist)
                # Exit if price recovers to mean AND we are profitable
                if current_price >= avg_price and roi > 0.005:
                    return self._execute_trade('SELL', symbol, pos['amount'], 'MEAN_REV_WIN')
            
            # D. Stale Position Timeout
            pos['ticks_held'] += 1
            if pos['ticks_held'] > 120 and roi < 0:
                return self._execute_trade('SELL', symbol, pos['amount'], 'STALE_EXIT')

        # 3. Scan for New Entries
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions:
                continue
            
            price = data['priceUsd']
            
            # Update History
            if symbol not in self.market_history:
                self.market_history[symbol] = {'prices': []}
            
            mh = self.market_history[symbol]
            mh['prices'].append(price)
            if len(mh['prices']) > self.window_size:
                mh['prices'].pop(0)
            
            # Pre-computation Filters
            if len(mh['prices']) < self.window_size:
                continue
            if data['liquidity'] < self.min_liquidity:
                continue
                
            # Filter: Flash Crash Rejection
            if len(mh['prices']) >= 2:
                prev_price = mh['prices'][-2]
                tick_change = (price - prev_price) / prev_price
                if tick_change < self.max_tick_drop:
                    continue # Ignore falling knives
            
            # Calculate Statistics
            prices_arr = mh['prices']
            mean = sum(prices_arr) / len(prices_arr)
            variance = sum((x - mean) ** 2 for x in prices_arr) / len(prices_arr)
            std_dev = math.sqrt(variance)
            
            if mean == 0: continue
            vol_ratio = std_dev / mean
            
            # Volatility Gate
            if vol_ratio < self.min_volatility: continue
            if vol_ratio > self.max_volatility: continue
            
            # Bollinger Logic
            lower_band = mean - (std_dev * self.entry_sigma)
            
            # --- SIGNAL GENERATION ---
            if price < lower_band:
                
                # Check 1: RSI (Oversold)
                rsi = self._calculate_rsi(prices_arr)
                if rsi < 20:
                    
                    # Check 2: Stabilization (Intra-update support)
                    # Price must be equal or higher than the last tick to confirm momentary support
                    if len(prices_arr) >= 2 and price >= prices_arr[-2]:
                        
                        # Check 3: Trend Slope (Mutation)
                        # Ensure the Mean isn't crashing too hard (Death Spiral Check)
                        # Compare current mean to mean of the first half of the window
                        half_window = len(prices_arr) // 2
                        old_mean = sum(prices_arr[:half_window]) / half_window
                        
                        # If the mean has dropped more than 4% in the window, trend is too strong to fight
                        if mean >= old_mean * 0.96:
                            deviation_depth = (lower_band - price) / price
                            candidates.append({
                                'symbol': symbol,
                                'price': price,
                                'depth': deviation_depth
                            })

        # 4. Execution Selection
        if candidates and len(self.positions) < self.max_positions:
            # Sort by depth (how far below the band are we?)
            candidates.sort(key=lambda x: x['depth'], reverse=True)
            best = candidates[0]
            
            amount = self.base_capital / best['price']
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'amount': amount,
                'highest_roi': -1.0,
                'ticks_held': 0
            }
            
            return self._execute_trade('BUY', best['symbol'], amount, 'ALPHA_Z_ENTRY')

        return None

    def _calculate_rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Cutler's RSI (Stable for short windows)
        window = prices[-self.rsi_period:]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(window)):
            diff = window[i] - window[i-1]
            if diff > 0:
                gains += diff
            else:
                losses -= diff
        
        if losses == 0:
            return 100.0
        if gains == 0:
            return 0.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _execute_trade(self, side, symbol, amount, reason):
        if side == 'SELL':
            if symbol in self.positions:
                del self.positions[symbol]
        
        return {
            'side': side,
            'symbol': symbol,
            'amount': amount,
            'reason': [reason]
        }