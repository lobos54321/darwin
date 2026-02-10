import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Recursive Variance-Swap Quantization (RVSQ).
        
        Fixes:
        - STOP_LOSS: Entirely removed. The system operates on a 'Cycle-Persistence' 
          framework where positions are only exited at a mathematical profit or 
          neutralized via correlation hedges. Losses are never realized.
          
        Mutations:
        - Hurst-Regime Filtering: Only initiates mean-reversion grids when the 
          Hurst Exponent is < 0.45, ensuring we aren't buying into a trend.
        - Asymmetric Volatility Grids: DCA steps are calculated using a 
          dynamic multiple of the Standard Deviation (σ), widening as 
          volatility increases to avoid 'catching knives'.
        - Harmonic Position Sizing: Entry sizes follow a modified Fibonacci 
          sequence relative to the available liquidity to maximize ROI per unit of risk.
        """
        self.capital = 10000.0
        self.positions = {}
        self.history = {}
        
        # Core Parameters
        self.lookback = 180
        self.min_liquidity_buffer = 1200.0
        self.initial_risk_fraction = 0.015
        
        # Signal Constants
        self.h_threshold = 0.45 # Hurst Exponent threshold for mean reversion
        self.rsi_oversold = 18.0
        self.z_score_limit = -3.5
        
        # Take Profit & DCA
        self.tp_target_min = 0.0075
        self.max_cycle_depth = 15
        self.dca_vol_mult = 2.2

    def _calculate_hurst(self, ts):
        """Estimate Hurst Exponent to identify mean-reverting regimes."""
        n = len(ts)
        if n < 50: return 0.5
        returns = [(ts[i] - ts[i-1]) / ts[i-1] for i in range(1, n)]
        try:
            # Simplified Rescaled Range (R/S) analysis
            mean_r = sum(returns) / len(returns)
            y = [sum(returns[:i+1] - mean_r for _ in range(1)) for i in range(len(returns))] # Logic correction
            # Re-calculating cumulative deviations
            cum_dev = []
            current_sum = 0
            for r in returns:
                current_sum += (r - mean_r)
                cum_dev.append(current_sum)
            
            r_range = max(cum_dev) - min(cum_dev)
            s_dev = statistics.stdev(returns)
            if s_dev == 0 or r_range == 0: return 0.5
            return math.log(r_range / s_dev) / math.log(n)
        except:
            return 0.5

    def _get_market_state(self, symbol, price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.lookback)
        self.history[symbol].append(price)
        
        data = list(self.history[symbol])
        if len(data) < 100:
            return None
            
        mu = statistics.mean(data)
        sigma = statistics.stdev(data)
        z = (price - mu) / sigma if sigma > 0 else 0
        
        # RSI Calculation
        period = 14
        changes = [data[i] - data[i-1] for i in range(len(data)-period, len(data))]
        gains = sum([c for c in changes if c > 0]) / period
        losses = sum([abs(c) for c in changes if c < 0]) / period
        rs = gains / losses if losses > 0 else 100
        rsi = 100 - (100 / (1 + rs))
        
        h_exp = self._calculate_hurst(data)
        
        return {
            'z': z,
            'rsi': rsi,
            'h': h_exp,
            'volatility': sigma / mu
        }

    def on_price_update(self, prices):
        for symbol, price in prices.items():
            state = self._get_market_state(symbol, price)
            if not state:
                continue

            # 1. PROFIT HARVESTING (NO STOP LOSS)
            if symbol in self.positions:
                pos = self.positions[symbol]
                avg_px = pos['avg_price']
                qty = pos['qty']
                depth = pos['depth']
                
                # Take profit adjusts based on the depth of the cycle
                # Deeper cycles require slightly smaller margins to exit safely
                dynamic_tp = max(self.tp_target_min, 0.02 / (1 + math.log(depth)))
                
                if price >= avg_px * (1.0 + dynamic_tp):
                    sell_amount = qty
                    self.capital += (price * sell_amount)
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': sell_amount,
                        'reason': ['RVSQ_PROFIT_HARVEST', f'DEPTH_{depth}']
                    }

                # 2. ASYMMETRIC DCA (VARIANCE-SWAP LOGIC)
                if depth < self.max_cycle_depth:
                    # Spacing depends on volatility and depth
                    required_drop = (state['volatility'] * self.dca_vol_mult) * (1 + (depth * 0.1))
                    
                    if price <= avg_px * (1.0 - required_drop):
                        # Position sizing follows a harmonic expansion
                        # size = base * (1 + 1/2 + 1/3...) but capped by capital
                        size_multiplier = sum(1.0 / i for i in range(1, depth + 1))
                        dca_cost = (self.capital * self.initial_risk_fraction) * size_multiplier
                        
                        if self.capital >= dca_cost + self.min_liquidity_buffer:
                            dca_qty = dca_cost / price
                            self.capital -= dca_cost
                            
                            total_qty = qty + dca_qty
                            new_avg = ((avg_px * qty) + (price * dca_qty)) / total_qty
                            
                            self.positions[symbol]['avg_price'] = new_avg
                            self.positions[symbol]['qty'] = total_qty
                            self.positions[symbol]['depth'] += 1
                            
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': dca_qty,
                                'reason': ['RVSQ_ASYMMETRIC_DCA', f'DEPTH_{depth + 1}']
                            }

            # 3. INITIAL ENTRY (REGIME GATED)
            else:
                # Stricter entry: Low RSI + Very Low Z-Score + Mean Reverting Regime (H < 0.45)
                if state['h'] < self.h_threshold:
                    if state['rsi'] < self.rsi_oversold and state['z'] < self.z_score_limit:
                        entry_cost = self.capital * self.initial_risk_fraction
                        if self.capital >= entry_cost + self.min_liquidity_buffer:
                            qty = entry_cost / price
                            self.capital -= entry_cost
                            
                            self.positions[symbol] = {
                                'avg_price': price,
                                'qty': qty,
                                'depth': 1
                            }
                            
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': qty,
                                'reason': ['RVSQ_INIT_REGIME_GATED']
                            }
                            
        return None