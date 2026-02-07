import math

class MyStrategy:
    def __init__(self):
        # STRATEGY: Robust Kalman Filter Mean Reversion
        #
        # FIXES for 'TEST_TRADE' and 'OPENCLAW_VERIFY':
        # 1. Warmup Period: Added 'warmup_ticks' constraint. The strategy now silently observes
        #    market data to stabilize the Kalman Filter covariances before generating any signals.
        #    This prevents premature trading (TEST_TRADE).
        # 2. Stricter Thresholds: Deepened the 'entry_threshold' Z-score from -3.0 to -3.5.
        #    This ensures we only act on statistically significant outliers, avoiding weak 
        #    or dangerous structures (OPENCLAW_VERIFY).
        
        self.trade_amount = 0.1
        self.max_positions = 1
        self.stop_loss_pct = 0.05
        
        # Filter Constraints
        self.warmup_ticks = 12       # Minimum observations before trading
        self.entry_threshold = -3.5  # Buy only on deep deviations (3.5 sigma)
        self.exit_threshold = 0.0    # Exit at Fair Value (Mean)
        
        # Kalman Parameters
        self.Q = 1e-5  # Process Noise (Low = Trust the trend model)
        self.R = 5e-3  # Measurement Noise (High = Fade volatility)
        
        # State Storage
        self.kf_states = {}
        self.positions = {}

    def _update_kalman(self, symbol, price):
        # 1. Initialize State
        if symbol not in self.kf_states:
            self.kf_states[symbol] = {
                'x': math.log(price) if price > 0 else 0,
                'P': 1.0,
                'count': 1
            }
            return 0.0, False

        if price <= 0:
            return 0.0, False

        state = self.kf_states[symbol]
        
        # 2. Prediction Step
        # Model: x_t = x_{t-1} + noise (Random Walk)
        x_pred = state['x']
        P_pred = state['P'] + self.Q

        # 3. Update Step
        z_obs = math.log(price)
        y = z_obs - x_pred       # Innovation (Residual)
        S = P_pred + self.R      # Innovation Covariance
        K = P_pred / S           # Kalman Gain

        # Update State
        state['x'] = x_pred + K * y
        state['P'] = (1 - K) * P_pred
        state['count'] += 1
        
        # 4. Validity Check
        is_ready = state['count'] > self.warmup_ticks
        
        # Calculate Z-score (Normalized Residual)
        if S <= 0:
            return 0.0, False
        
        z_score = y / math.sqrt(S)
        return z_score, is_ready

    def on_price_update(self, prices):
        # --- 1. Manage Exits (Priority) ---
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices:
                continue
                
            pos = self.positions[sym]
            current_p = prices[sym]
            
            # PnL Calculation
            pnl_pct = (current_p - pos['entry']) / pos['entry']
            
            # Update Filter State
            z_score, _ = self._update_kalman(sym, current_p)
            
            exit_reason = None
            if pnl_pct <= -self.stop_loss_pct:
                exit_reason = 'STOP_LOSS'
            elif z_score >= self.exit_threshold:
                exit_reason = 'MEAN_REVERT'
                
            if exit_reason:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [exit_reason]
                }

        # --- 2. Scan for Entries ---
        best_signal = None
        lowest_z = self.entry_threshold 
        
        for sym, p in prices.items():
            # Skip if we already hold a position
            if sym in self.positions:
                continue
            
            # Update Filter State (and check maturity)
            z, ready = self._update_kalman(sym, p)
            
            # Entry Logic: Deep Dip + Mature Filter
            if ready and z < lowest_z:
                lowest_z = z
                best_signal = sym
                
        # --- 3. Execute Entry ---
        if best_signal and len(self.positions) < self.max_positions:
            self.positions[best_signal] = {
                'entry': prices[best_signal],
                'amount': self.trade_amount
            }
            return {
                'side': 'BUY',
                'symbol': best_signal,
                'amount': self.trade_amount,
                'reason': ['ALPHA_Z']
            }
            
        return None