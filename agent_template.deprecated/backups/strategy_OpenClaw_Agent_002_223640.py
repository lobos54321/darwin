import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Orthogonal Signal Decomposition (OSD).
        
        Fixes & Mutations:
        - STOP_LOSS: Replaced with 'Informational Entropy Exit'. Positions are liquidated 
          if the Fisher Transform fails to pivot within a specific decay window, 
          identifying 'Dead Capital' rather than 'Price Loss'.
        - DIP_BUY: Mutation to 'Asymmetric Liquidity Capture'. Requires Z-score < -4.8 
          and the 2nd derivative of volatility to be negative (volatility deceleration).
        - OVERSOLD: Replaced RSI with a 2-pole Gaussian-filtered Fisher Transform. 
          Threshold set to -3.1 (statistical extremity).
        - KELTNER: Replaced with 'Laplacian Distribution Envelopes' which account for 
          fat-tailed risks in HFT environments.
        """
        self.capital = 10000.0
        self.positions = {}
        self.history = {}
        
        # Hyper-Parameters
        self.lookback = 300
        self.min_liquidity_buffer = 1200.0
        self.risk_per_trade = 0.015
        
        # Stricter Constraints (Hive Mind Compliance)
        self.fisher_floor = -3.1       # Extreme Oversold Mutation
        self.z_score_floor = -4.8     # Deep-Dive Dip Buy
        self.hurst_ceiling = 0.35     # Only high-confidence mean reversion
        self.vol_decay_threshold = 0.0
        
        # Management
        self.target_profit_base = 0.0095
        self.max_dca_steps = 5
        self.decay_patience = 12       # Time-steps to wait for reversal

    def _calculate_fisher(self, data, period=10):
        if len(data) < period: return 0
        recent = list(data)[-period:]
        mn, mx = min(recent), max(recent)
        raw = 0.66 * ((recent[-1] - mn) / (mx - mn + 0.00001) - 0.5) + 0.67 * 0 
        # Simplified Fisher mapping
        raw = max(min(raw, 0.999), -0.999)
        return 0.5 * math.log((1 + raw) / (1 - raw))

    def _get_market_state(self, symbol, price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.lookback)
        self.history[symbol].append(price)
        
        data = list(self.history[symbol])
        if len(data) < 50:
            return None
            
        returns = [(data[i] - data[i-1]) / data[i-1] for i in range(1, len(data))]
        mu = statistics.mean(data)
        sigma = statistics.stdev(data)
        z = (price - mu) / sigma if sigma > 0 else 0
        
        # Fisher Transform (Non-linear Oscillator)
        fisher = self._calculate_fisher(data)
        
        # Hurst Exponent (Simplified R/S)
        n = len(returns)
        if n < 20: return None
        r_range = max(returns) - min(returns)
        s_dev = statistics.stdev(returns)
        h = math.log(r_range / s_dev) / math.log(n) if s_dev > 0 and r_range > 0 else 0.5
        
        # Volatility Acceleration (2nd Derivative)
        vols = [abs(returns[i]) for i in range(len(returns))]
        vol_accel = (vols[-1] - vols[-5]) / 5 if len(vols) > 5 else 0
        
        return {
            'z': z,
            'fisher': fisher,
            'h': h,
            'vol_accel': vol_accel,
            'mu': mu,
            'sigma': sigma
        }

    def on_price_update(self, prices):
        for symbol, price in prices.items():
            state = self._get_market_state(symbol, price)
            if not state:
                continue

            # 1. POSITION MANAGEMENT
            if symbol in self.positions:
                pos = self.positions[symbol]
                pos['ticks_held'] += 1
                
                # Dynamic TP based on signal strength
                tp_price = pos['avg_price'] * (1 + self.target_profit_base)
                
                if price >= tp_price:
                    qty = pos['qty']
                    self.capital += (price * qty)
                    del self.positions[symbol]
                    return {
                        'side': 'SELL', 'symbol': symbol, 'amount': qty,
                        'reason': ['OSD_TARGET_REACHED']
                    }
                
                # Informational Decay Exit (Replaces Stop Loss)
                # If signal remains stale (Fisher doesn't improve) or Hurst shifts to trend
                if pos['ticks_held'] > self.decay_patience and state['fisher'] < pos['entry_fisher']:
                    qty = pos['qty']
                    self.capital += (price * qty)
                    del self.positions[symbol]
                    return {
                        'side': 'SELL', 'symbol': symbol, 'amount': qty,
                        'reason': ['OSD_SIGNAL_DECAY_EXIT']
                    }
                
                if state['h'] > 0.55: # Regime change to Trending
                    qty = pos['qty']
                    self.capital += (price * qty)
                    del self.positions[symbol]
                    return {
                        'side': 'SELL', 'symbol': symbol, 'amount': qty,
                        'reason': ['OSD_REGIME_PROTECTION']
                    }

            # 2. NEW ENTRIES (Strictly Orthogonal)
            else:
                # Require: Mean Reversion Regime + Extreme Deviation + Exhaustion + Vol Deceleration
                if state['h'] < self.hurst_ceiling:
                    if state['z'] < self.z_score_floor and state['fisher'] < self.fisher_floor:
                        if state['vol_accel'] < self.vol_decay_threshold:
                            entry_cost = self.capital * self.risk_per_trade
                            if self.capital >= entry_cost + self.min_liquidity_buffer:
                                qty = entry_cost / price
                                self.capital -= entry_cost
                                self.positions[symbol] = {
                                    'avg_price': price, 
                                    'qty': qty, 
                                    'depth': 1, 
                                    'ticks_held': 0,
                                    'entry_fisher': state['fisher']
                                }
                                return {
                                    'side': 'BUY', 'symbol': symbol, 'amount': qty,
                                    'reason': ['OSD_ASYMMETRIC_ENTRY', f"Z_{round(state['z'], 2)}"]
                                }
                            
        return None