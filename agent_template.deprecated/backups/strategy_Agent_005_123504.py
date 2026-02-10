import math

class MyStrategy:
    def __init__(self):
        # STRATEGY: Kalman Filter Mean Reversion (Log-Space)
        #
        # REASONING:
        # To strictly avoid 'SMA_CROSSOVER', 'MOMENTUM', and 'TREND_FOLLOWING', 
        # this strategy abandons fixed-window moving averages and trend indicators.
        # Instead, it uses a 1D Kalman Filter to estimate the "Fair Value" (Hidden State)
        # of the asset.
        #
        # MECHANISM:
        # 1. State Estimation: Recursive Bayesian update of Fair Value (x) and Uncertainty (P).
        # 2. Signal Generation: Z-score of the Measurement Residual (Innovation).
        #    - Residual = LogPrice - FairValue
        # 3. Logic:
        #    - Buy ONLY when Z-score < -3.0 (Statistical Anomaly / Deep Dip).
        #    - Sell when Z-score reverts to 0 (Fair Value).
        #    - This is purely Mean Reverting and Anti-Momentum.

        self.trade_amount = 0.1
        self.max_positions = 1
        self.stop_loss_pct = 0.04
        
        # Kalman Filter Hyperparameters
        # Process Noise Covariance (Q): Trust in the trend evolution (set low for stability)
        self.Q = 1e-5 
        # Measurement Noise Covariance (R): Expected market noise (set higher to fade volatility)
        self.R = 1e-3
        
        # Trading Thresholds
        self.entry_threshold = -3.0  # Buy only on 3-sigma deviations
        self.exit_threshold = 0.0    # Exit at mean
        
        # State Storage: {symbol: {'x': estimate, 'P': covariance}}
        self.kf_states = {}
        self.positions = {}

    def _update_kalman(self, symbol, price):
        # Use Log-Price for scale invariance (handle both 1.0 and 60000.0 prices)
        if price <= 0: 
            return 0.0
        z_obs = math.log(price)
        
        # Initialize if new symbol
        if symbol not in self.kf_states:
            self.kf_states[symbol] = {
                'x': z_obs,  # Initial estimate is current price
                'P': 1.0     # High initial uncertainty
            }
            return 0.0

        state = self.kf_states[symbol]
        x = state['x']
        P = state['P']

        # 1. PREDICTION STEP
        # Assumes Local Level Model (Random Walk): x_t = x_{t-1} + noise
        x_pred = x
        P_pred = P + self.Q

        # 2. UPDATE STEP
        y = z_obs - x_pred      # Innovation (Residual)
        S = P_pred + self.R     # Innovation Covariance
        K = P_pred / S          # Kalman Gain

        x_new = x_pred + K * y
        P_new = (1 - K) * P_pred

        self.kf_states[symbol] = {'x': x_new, 'P': P_new}

        # 3. CALCULATE Z-SCORE
        # Normalized deviation from the model
        if S <= 0:
            return 0.0
        return y / math.sqrt(S)

    def on_price_update(self, prices):
        # 1. Manage Existing Positions
        for sym in list(self.positions.keys()):
            if sym not in prices:
                continue
                
            pos = self.positions[sym]
            current_p = prices[sym]
            
            # Calculate PnL
            pnl_pct = (current_p - pos['entry']) / pos['entry']
            
            # Update Model
            z_score = self._update_kalman(sym, current_p)
            
            exit_reason = None
            if pnl_pct <= -self.stop_loss_pct:
                exit_reason = 'STOP_LOSS'
            elif z_score >= self.exit_threshold:
                # Price reverted to fair value
                exit_reason = 'MEAN_REVERSION'
                
            if exit_reason:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [exit_reason]
                }

        # 2. Scan for Entries
        best_signal = None
        lowest_z = self.entry_threshold # Filter strictly below threshold
        
        for sym, p in prices.items():
            if sym in self.positions:
                continue
            
            # Update Model and get Signal
            z = self._update_kalman(sym, p)
            
            # Deep Dip Logic
            if z < lowest_z:
                lowest_z = z
                best_signal = sym
                
        # 3. Execute Entry
        if best_signal and len(self.positions) < self.max_positions:
            self.positions[best_signal] = {
                'entry': prices[best_signal],
                'amount': self.trade_amount
            }
            return {
                'side': 'BUY',
                'symbol': best_signal,
                'amount': self.trade_amount,
                'reason': [f'KF_DIP_Z{lowest_z:.2f}']
            }
            
        return None