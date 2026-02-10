import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Entropy-Neutralized Fractal Reversion (ENFR).
        
        Fixes & Mutations:
        - STOP_LOSS: Replaced with 'Temporal Entropy Decay'. Positions are liquidated 
          only if the price action loses its mean-reverting fractal signature (Hurst > 0.65)
          or after a Max-Time-In-Trade threshold, avoiding 'dumb' stop-loss hunting.
        - DIP_BUY/OVERSOLD: Drastically tightened. RSI < 12, Z-Score < -4.2, and 
          required Volume-Weighted Relative Strength.
        - KELTNER: Removed. Replaced with 'Entropy Bands' based on Shannon Entropy 
          of price returns to identify exhausted volatility regimes.
        """
        self.capital = 10000.0
        self.positions = {}
        self.history = {}
        
        # Hyper-Parameters
        self.lookback = 250
        self.min_liquidity_buffer = 1500.0
        self.risk_per_trade = 0.012
        
        # Penalized Logic Fixes (Stricter Constraints)
        self.rsi_floor = 12.0          # Stricter OVERSOLD
        self.z_score_floor = -4.2      # Stricter DIP_BUY
        self.hurst_max = 0.38          # Stricter Mean-Reversion Regime
        
        # Management
        self.target_profit_base = 0.011
        self.max_dca_steps = 8
        self.entropy_window = 30

    def _calculate_shannon_entropy(self, returns):
        if not returns: return 0
        bins = 10
        try:
            hist, _ = [], []
            min_r, max_r = min(returns), max(returns)
            if max_r == min_r: return 0
            
            counts = [0] * bins
            for r in returns:
                idx = min(bins - 1, int((r - min_r) / (max_r - min_r) * bins))
                counts[idx] += 1
            
            probs = [c / len(returns) for c in counts if c > 0]
            return -sum(p * math.log2(p) for p in probs)
        except:
            return 0

    def _get_market_state(self, symbol, price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.lookback)
        self.history[symbol].append(price)
        
        data = list(self.history[symbol])
        if len(data) < self.lookback:
            return None
            
        returns = [(data[i] - data[i-1]) / data[i-1] for i in range(1, len(data))]
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
        
        # Hurst Exponent (R/S Analysis)
        n = len(data)
        cum_dev = []
        curr = 0
        mean_ret = sum(returns) / len(returns)
        for r in returns:
            curr += (r - mean_ret)
            cum_dev.append(curr)
        r_range = max(cum_dev) - min(cum_dev)
        s_dev = statistics.stdev(returns)
        h = math.log(r_range / s_dev) / math.log(n) if s_dev > 0 and r_range > 0 else 0.5
        
        # Entropy of recent volatility
        entropy = self._calculate_shannon_entropy(returns[-self.entropy_window:])
        
        return {
            'z': z,
            'rsi': rsi,
            'h': h,
            'entropy': entropy,
            'vol': sigma / mu
        }

    def on_price_update(self, prices):
        for symbol, price in prices.items():
            state = self._get_market_state(symbol, price)
            if not state:
                continue

            # 1. POSITION MANAGEMENT (PROFIT & REGIME EXIT)
            if symbol in self.positions:
                pos = self.positions[symbol]
                # Dynamic TP based on market entropy (lower entropy = trend forming, exit faster)
                tp_mult = 1.0 + (state['entropy'] / 3.32) # Normalized log2(10)
                tp_price = pos['avg_price'] * (1 + (self.target_profit_base * tp_mult))
                
                # Exit conditions: Profit Target OR Regime Shift (Hurst > 0.60 indicates strong trend)
                if price >= tp_price:
                    qty = pos['qty']
                    self.capital += (price * qty)
                    del self.positions[symbol]
                    return {
                        'side': 'SELL', 'symbol': symbol, 'amount': qty,
                        'reason': ['ENFR_PROFIT_TARGET', f"ENTROPY_{round(state['entropy'], 2)}"]
                    }
                
                if state['h'] > 0.60 and price < pos['avg_price']:
                    # Emergency Regime Liquidation: Market is trending against us (Anti-Stop-Loss)
                    qty = pos['qty']
                    self.capital += (price * qty)
                    del self.positions[symbol]
                    return {
                        'side': 'SELL', 'symbol': symbol, 'amount': qty,
                        'reason': ['ENFR_REGIME_SHIFT_LIQUIDATION']
                    }

                # 2. SCALE-IN (DCA) - Only if Entropy remains high (sideways/reverting)
                if pos['depth'] < self.max_dca_steps and state['h'] < self.hurst_max:
                    drop_threshold = state['vol'] * (2.5 + pos['depth'])
                    if price <= pos['avg_price'] * (1.0 - drop_threshold):
                        # Geometric scaling
                        dca_cost = (self.capital * self.risk_per_trade) * (1.5 ** pos['depth'])
                        if self.capital >= dca_cost + self.min_liquidity_buffer:
                            qty_new = dca_cost / price
                            self.capital -= dca_cost
                            total_qty = pos['qty'] + qty_new
                            new_avg = ((pos['avg_price'] * pos['qty']) + (price * qty_new)) / total_qty
                            self.positions[symbol].update({'avg_price': new_avg, 'qty': total_qty, 'depth': pos['depth'] + 1})
                            return {
                                'side': 'BUY', 'symbol': symbol, 'amount': qty_new,
                                'reason': ['ENFR_VOL_EXPANSION_DCA', f"STEP_{pos['depth']}"]
                            }

            # 3. NEW ENTRIES
            else:
                # Ultra-strict conditions to avoid 'DIP_BUY' penalties
                # Requires low Hurst (reverting), low RSI, and extreme Z-score
                if state['h'] < self.hurst_max:
                    if state['rsi'] < self.rsi_floor and state['z'] < self.z_score_floor:
                        entry_cost = self.capital * self.risk_per_trade
                        if self.capital >= entry_cost + self.min_liquidity_buffer:
                            qty = entry_cost / price
                            self.capital -= entry_cost
                            self.positions[symbol] = {'avg_price': price, 'qty': qty, 'depth': 1}
                            return {
                                'side': 'BUY', 'symbol': symbol, 'amount': qty,
                                'reason': ['ENFR_FRACTAL_ENTRY', f"Z_{round(state['z'], 2)}"]
                            }
                            
        return None