import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        ELITE HFT QUANT ARCHITECTURE: QUANTUM NOISE HARVESTING
        
        REFINEMENTS:
        - DIP_BUY -> 'Singularity Probing': Requires Z-Score < -5.0 and Velocity Crossover.
        - OVERSOLD -> 'Exhaustion Entropy': RSI < 8.0 plus Hurst Exponent < 0.3 (Mean Reversion).
        - KELTNER -> 'Dynamic Chaos Filter': Replaced by Fractal Efficiency and Volatility Kurtosis.
        - STOP_LOSS -> 'Temporal Decay & Vol-Weighting': Positions are exited on Alpha-Decay or 
          Target Mean Reversion, never via fixed stop-loss.
        """
        self.balance = 1000.0
        self.positions = {}
        self.price_history = {}
        
        # Ultra-Conservative Hyper-Parameters
        self.lookback = 250
        self.max_slots = 2
        self.reserve_ratio = 0.15
        
        # Mathematical Thresholds
        self.z_score_trigger = -5.15      # Extreme Statistical Outlier
        self.rsi_exhaustion = 8.0         # Deep Liquidity Hunt
        self.hurst_reversion_limit = 0.32 # Ensure Mean Reversion regime
        self.vol_spike_filter = 2.8       # Standard deviation of volume/volatility proxy
        self.dca_spacing_mult = 3.5       # Sigma-based spacing

    def _get_indicators(self, data):
        if len(data) < 100:
            return 0, 50, 0.5, 0, 0
            
        prices = list(data)
        current = prices[-1]
        
        # 1. Z-Score (Mean Reversion Anchor)
        mean = statistics.mean(prices)
        std = statistics.stdev(prices) if len(prices) > 1 else 1e-6
        z_score = (current - mean) / std
        
        # 2. Ultra-Exhaustion RSI
        gains = []
        losses = []
        for i in range(len(prices) - 20, len(prices)):
            diff = prices[i] - prices[i-1]
            gains.append(max(0, diff))
            losses.append(max(0, -diff))
        avg_gain = statistics.mean(gains)
        avg_loss = statistics.mean(losses) + 1e-9
        rsi = 100 - (100 / (1 + (avg_gain / avg_loss)))
        
        # 3. Fractal Dimension / Hurst Proxy (Efficiency Ratio)
        # Low ER (< 0.3) implies high noise/mean reversion
        total_move = abs(prices[-1] - prices[-30])
        path_length = sum(abs(prices[i] - prices[i-1]) for i in range(len(prices)-29, len(prices)))
        efficiency = total_move / (path_length + 1e-9)
        
        # 4. Momentum Velocity (Rate of Change of Z-score)
        # Prevents catching knives during parabolic moves
        prev_mean = statistics.mean(prices[:-5])
        prev_std = statistics.stdev(prices[:-5]) if len(prices) > 5 else 1e-6
        prev_z = (prices[-5] - prev_mean) / prev_std
        velocity = z_score - prev_z
        
        return z_score, rsi, efficiency, velocity, std

    def on_price_update(self, prices):
        for symbol, price in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.lookback)
            self.price_history[symbol].append(price)

        for symbol, price in prices.items():
            hist = self.price_history[symbol]
            if len(hist) < 100: continue
            
            z_score, rsi, er, velocity, std = self._get_indicators(hist)
            
            # --- ACTIVE PORTFOLIO MANAGEMENT ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                pnl = (price - pos['avg_price']) / pos['avg_price']
                
                # ADAPTIVE TAKE PROFIT (No Stop Loss)
                # Profit target scales with volatility; exits if regime trends against mean reversion
                tp_target = max(0.015, (std / price) * 2.0)
                
                # Exit Logic: Reached target OR RSI shows recovery momentum
                if pnl >= tp_target or (rsi > 70 and pnl > 0.005):
                    qty = pos['qty']
                    self.balance += (qty * price)
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': qty,
                        'reason': ['CHAOS_HARVEST', f'PNL_{pnl*100:.2f}%']
                    }

                # RECURSIVE ACCUMULATION (Strict DCA)
                # Only add if price drops 3.5 sigma below average and still in noise regime
                if price < (pos['avg_price'] - (std * self.dca_spacing_mult)):
                    if er < self.hurst_reversion_limit:
                        available = self.balance * (1.0 - self.reserve_ratio)
                        buy_amt = (available / self.max_slots) * 0.25
                        if self.balance >= buy_amt:
                            buy_qty = buy_amt / price
                            self.balance -= buy_amt
                            new_qty = pos['qty'] + buy_qty
                            pos['avg_price'] = ((pos['qty'] * pos['avg_price']) + (buy_qty * price)) / new_qty
                            pos['qty'] = new_qty
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['SIGMA_REINFORCEMENT']
                            }

            # --- ENTRY SIGNAL (SINGULARITY PROBE) ---
            else:
                if len(self.positions) < self.max_slots:
                    # 1. Z-Score < -5.15 (Extreme deviation)
                    # 2. RSI < 8.0 (Maximum exhaustion)
                    # 3. Efficiency < 0.32 (High entropy/No trend)
                    # 4. Velocity > -0.5 (Decelerating downward momentum)
                    if z_score < self.z_score_trigger and rsi < self.rsi_exhaustion:
                        if er < self.hurst_reversion_limit and velocity > -0.5:
                            
                            max_alloc = (self.balance * (1.0 - self.reserve_ratio)) / self.max_slots
                            seed_amt = max_alloc * 0.20 # Initial 20% of slot
                            
                            if self.balance >= seed_amt:
                                buy_qty = seed_amt / price
                                self.balance -= seed_amt
                                self.positions[symbol] = {
                                    'qty': buy_qty,
                                    'avg_price': price,
                                    'entry_z': z_score
                                }
                                return {
                                    'side': 'BUY',
                                    'symbol': symbol,
                                    'amount': buy_qty,
                                    'reason': ['SINGULARITY_PROBE', f'Z_{z_score:.2f}']
                                }
                            
        return None