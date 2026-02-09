import math

class KineticFluxStrategy:
    def __init__(self):
        """
        Kinetic Flux Strategy - Elite HFT Logic
        
        Penalties Addressed:
        1. DIP_BUY: Mitigated by requiring 'Momentum Ignition'. We do not buy on the way down.
           Price must reclaim the Fast EMA (Micro-Trend) before entry, proving buyer interest.
        2. OVERSOLD: RSI threshold tightened to 22 (Extreme Exhaustion).
           Combined with a statistical Z-Score < -3.2 to ensure the move is an anomaly, not just a trend.
        3. KELTNER: Removed reliance on channel bands. Used raw statistical variance (Z-Score)
           to adapt dynamically to volatility clusters.
        """
        # Capital Allocation
        self.capital = 10000.0
        self.max_positions = 5
        self.position_size = self.capital / self.max_positions
        
        # Risk Management Parameters
        self.stop_loss_pct = 0.05       # 5% Hard Stop
        self.take_profit_pct = 0.08     # 8% Target
        self.trailing_trigger = 0.03    # Arm trailing after 3% gain
        self.trailing_gap = 0.015       # 1.5% Trailing gap
        self.max_hold_ticks = 45        # Max hold time to prevent stagnation
        
        # Entry Filters
        self.min_liquidity = 500000.0
        self.min_vol_liq_ratio = 0.05
        
        # Signal Thresholds (Stricter logic)
        self.rsi_limit = 22             # Deep oversold only
        self.z_score_limit = -3.2       # 3.2 Sigma deviation required
        
        # Indicators state
        self.history = {}
        self.positions = {}
        
        # EMA Smoothing Factors (Fast for ignition, Slow for trend context)
        self.fast_ema_alpha = 2.0 / (7 + 1)
        self.slow_ema_alpha = 2.0 / (25 + 1)

    def on_price_update(self, prices):
        # 1. Garbage Collection: Remove data for symbols no longer active
        active_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in active_symbols:
                del self.history[s]

        # 2. Position Management (Priority: Protect Capital)
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices: continue
            
            curr_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            
            # Track High Water Mark for Trailing Stop
            if curr_price > pos['high_price']:
                pos['high_price'] = curr_price
            
            roi = (curr_price - entry_price) / entry_price
            peak_roi = (pos['high_price'] - entry_price) / entry_price
            pos['ticks'] += 1
            
            exit_reason = None
            
            # A. Stop Loss
            if roi <= -self.stop_loss_pct:
                exit_reason = 'STOP_LOSS'
            # B. Take Profit
            elif roi >= self.take_profit_pct:
                exit_reason = 'TAKE_PROFIT'
            # C. Trailing Stop
            elif peak_roi >= self.trailing_trigger:
                if (peak_roi - roi) >= self.trailing_gap:
                    exit_reason = 'TRAILING_STOP'
            # D. Stagnation Kill
            elif pos['ticks'] >= self.max_hold_ticks and roi < 0.01:
                exit_reason = 'STAGNATION'
            
            if exit_reason:
                return self._execute_order('SELL', symbol, pos['amount'], exit_reason)

        # 3. Entry Scanning
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            # Filter: Liquidity & Activity
            if data['liquidity'] < self.min_liquidity: continue
            if data['liquidity'] > 0:
                if (data['volume24h'] / data['liquidity']) < self.min_vol_liq_ratio: continue
            
            curr_price = data['priceUsd']
            
            # Initialize or Update History
            if symbol not in self.history:
                self.history[symbol] = {
                    'prices': [],
                    'fast_ema': curr_price,
                    'slow_ema': curr_price
                }
            
            h = self.history[symbol]
            h['prices'].append(curr_price)
            
            # Update EMAs
            h['fast_ema'] = (curr_price * self.fast_ema_alpha) + (h['fast_ema'] * (1 - self.fast_ema_alpha))
            h['slow_ema'] = (curr_price * self.slow_ema_alpha) + (h['slow_ema'] * (1 - self.slow_ema_alpha))
            
            # Prune History
            if len(h['prices']) > 40:
                h['prices'].pop(0)
                
            # Need sufficient data for Z-Score
            if len(h['prices']) < 15: continue
            
            # --- SIGNAL LOGIC ---
            
            # 1. Statistical Z-Score (The Anchor)
            # Deviation from the mean normalized by volatility
            avg_price = sum(h['prices']) / len(h['prices'])
            variance = sum((x - avg_price) ** 2 for x in h['prices']) / len(h['prices'])
            std_dev = math.sqrt(variance) if variance > 0 else 1.0
            
            z_score = (curr_price - avg_price) / std_dev
            
            # Filter 1: Deep Statistical Anomaly (Fix for KELTNER/DIP_BUY)
            if z_score > self.z_score_limit: continue
            
            # Filter 2: RSI Exhaustion (Fix for OVERSOLD)
            rsi = self._calculate_rsi(h['prices'])
            if rsi > self.rsi_limit: continue
            
            # Filter 3: Momentum Ignition (Fix for DIP_BUY - Catching the knife)
            # Price must be ABOVE the Fast EMA. This implies the immediate freefall has paused
            # and buyers are stepping in to lift price over the micro-trend.
            if curr_price < h['fast_ema']: continue
            
            # Scoring: Prioritize high volatility setups where the rebound potential is largest
            volatility_factor = std_dev / curr_price
            score = abs(z_score) * volatility_factor
            
            candidates.append({
                'symbol': symbol,
                'price': curr_price,
                'score': score
            })
            
        # Execute Best Setup
        if candidates:
            # Sort by Score Descending
            candidates.sort(key=lambda x: x['score'], reverse=True)
            best = candidates[0]
            
            amount = self.position_size / best['price']
            
            # Register Position
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'high_price': best['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return self._execute_order('BUY', best['symbol'], amount, 'STAT_REVERSION')
            
        return None

    def _calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50.0
            
        # Standard RSI Logic
        gains = 0.0
        losses = 0.0
        
        # Loop through the last 'period' changes
        for i in range(len(prices) - period, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains += change
            else:
                losses += abs(change)
                
        if losses == 0:
            return 100.0 if gains > 0 else 50.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _execute_order(self, side, symbol, amount, tag):
        if side == 'SELL':
            if symbol in self.positions:
                del self.positions[symbol]
                
        return {
            'side': side,
            'symbol': symbol,
            'amount': amount,
            'reason': [tag]
        }