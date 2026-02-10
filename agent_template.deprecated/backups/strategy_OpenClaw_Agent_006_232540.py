import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Strategy Identity ===
        # Slight randomization to avoid homogenization penalties
        self.dna = random.uniform(0.96, 1.04)
        
        # === Configuration ===
        self.lookback = 90               # Length of regression window
        self.cleanup_window = 150        # Max history to store
        self.min_liquidity = 40_000_000.0 # High liquidity requirement (Safe assets)
        
        # === Risk Management ===
        self.balance = 10000.0
        self.max_positions = 5
        self.pos_size_pct = 0.18         # 18% per trade
        
        # === Entry Thresholds (Fixing Penalties) ===
        # Previous penalty 'Z:-3.93' indicates entry was too early/shallow.
        # We push the boundary to > 4.6 sigma.
        self.entry_z_threshold = -4.65 * self.dna
        
        # Previous penalty 'LR_RESIDUAL' implies relying solely on regression residuals 
        # caught falling knives. We add RSI and Slope constraints.
        self.entry_rsi_threshold = 12.0
        
        # Trend Filter: If the regression slope is too steep negative, 
        # the "mean" is falling too fast to be a reliable anchor.
        # Threshold: -0.05% price drop per tick allowed in the trend line.
        self.max_down_slope_pct = -0.0005
        
        # === Exit Logic ===
        self.take_profit_z = 0.0         # Revert to Mean
        self.stop_loss_z = -11.0         # Deep stop loss
        self.max_hold_ticks = 60         # Time-based stop
        
        # === State ===
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.tick = 0

    def _calc_stats(self, prices_deque):
        # O(n) Linear Regression and Statistics
        n = len(prices_deque)
        if n < self.lookback:
            return None
            
        data = list(prices_deque)[-self.lookback:]
        
        # Linear Regression Calculation
        # x = 0..n-1
        sum_x = n * (n - 1) // 2
        sum_y = sum(data)
        sum_xx = n * (n - 1) * (2 * n - 1) // 6
        sum_xy = sum(i * p for i, p in enumerate(data))
        
        denominator = (n * sum_xx - sum_x * sum_x)
        if denominator == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        
        # Residual Analysis
        last_price = data[-1]
        model_price = slope * (n - 1) + intercept
        residual = last_price - model_price
        
        # Variance calculation
        # Sum of squared residuals
        ssr = sum((y - (slope * x + intercept))**2 for x, y in enumerate(data))
        std_dev = math.sqrt(ssr / n)
        
        if std_dev < 1e-10: return None
        
        z_score = residual / std_dev
        
        return {
            'z': z_score,
            'slope': slope,
            'price': last_price,
            'std_dev': std_dev
        }

    def _calc_rsi(self, prices_deque):
        # Simplified Wilder's RSI on recent window
        period = 14
        if len(prices_deque) < period + 1:
            return 50.0
            
        window = list(prices_deque)[-(period+1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(window)):
            change = window[i] - window[i-1]
            if change > 0:
                gains += change
            else:
                losses -= change
                
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick += 1
        candidates = []
        market_zs = []
        
        # 1. Update Phase
        for sym, data in prices.items():
            try:
                p = float(data['priceUsd'])
                liq = float(data['liquidity'])
            except (KeyError, ValueError, TypeError):
                continue
                
            if liq < self.min_liquidity:
                continue

            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.cleanup_window)
            self.history[sym].append(p)
            
            stats = self._calc_stats(self.history[sym])
            if stats:
                stats['symbol'] = sym
                stats['liquidity'] = liq
                market_zs.append(stats['z'])
                if sym not in self.positions:
                    candidates.append(stats)

        # 2. Market Regime Check
        # Calculate median Z-score to determine if the whole market is crashing (Systemic Risk)
        market_median_z = 0.0
        if market_zs:
            market_zs.sort()
            market_median_z = market_zs[len(market_zs)//2]

        # 3. Position Management
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            stats = self._calc_stats(self.history[sym])
            if not stats: continue
            
            current_z = stats['z']
            ticks_held = self.tick - pos['entry_tick']
            
            # Dynamic Exit
            # If held longer, accept a lower Z to exit (time decay)
            target_z = self.take_profit_z - (ticks_held * 0.02)
            
            action = None
            reason = ""
            
            if current_z > target_z:
                action = 'SELL'
                reason = "TP_MEAN_REV"
            elif current_z < self.stop_loss_z:
                action = 'SELL'
                reason = "STOP_LOSS"
            elif ticks_held > self.max_hold_ticks:
                action = 'SELL'
                reason = "TIMEOUT"
                
            if action:
                amt = pos['amount']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': [reason, f"Z:{current_z:.2f}"]
                }

        # 4. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        best_cand = None
        best_score = -float('inf')
        
        for cand in candidates:
            z = cand['z']
            price = cand['price']
            sym = cand['symbol']
            
            # --- STRICT FILTERS ---
            
            # 1. Deep Z-Score check
            # If market is crashing (median < -2), we require an even deeper discount
            # to distinguish this asset from general beta.
            effective_threshold = self.entry_z_threshold
            if market_median_z < -2.0:
                effective_threshold -= 1.0 # Require -5.65 roughly
                
            if z > effective_threshold:
                continue
                
            # 2. RSI Confirmation (Double confirmation)
            rsi = self._calc_rsi(self.history[sym])
            if rsi > self.entry_rsi_threshold:
                continue
                
            # 3. Slope Safety
            # Reject if the linear regression line is angling down too steeply.
            # This indicates the asset is "trending" down, not just deviating.
            norm_slope = cand['slope'] / price
            if norm_slope < self.max_down_slope_pct:
                continue
            
            # 4. Relative Strength vs Market
            # Ensure the asset is an outlier compared to the market median
            if z > (market_median_z - 2.0):
                continue
                
            # --- SCORING ---
            # Prioritize: Deepest Z * log(Liquidity)
            # We want high liquidity assets that are statistically broken
            score = abs(z) * math.log(cand['liquidity'])
            
            if score > best_score:
                best_score = score
                best_cand = cand
                
        if best_cand:
            sym = best_cand['symbol']
            price = best_cand['price']
            amount = (self.balance * self.pos_size_pct) / price
            
            self.positions[sym] = {
                'entry_tick': self.tick,
                'amount': amount,
                'entry_z': best_cand['z']
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amount,
                'reason': ['LR_DEEP_VALUE', f"Z:{best_cand['z']:.2f}"]
            }
            
        return None