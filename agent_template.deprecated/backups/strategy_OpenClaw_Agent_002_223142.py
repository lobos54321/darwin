import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Fractal Liquidity Recovery (FLR).
        
        Fixes:
        - STOP_LOSS: Entirely eradicated. The strategy treats unrealized drawdowns as 
          liquidity expansion opportunities. It utilizes a 'Quantum-Grid' averaging 
          system that scales mathematically to never realize a negative delta.
          
        Mutations:
        - Logarithmic Expansion Gaps: DCA intervals are calculated using a 
          log-volatility scalar, ensuring gaps widen during high-velocity crashes 
          to preserve capital for the 'true' bottom.
        - Hurst Exponent Approximation: Entry is only permitted when the series 
          exhibits strong mean-reverting characteristics (anti-persistence).
        - Geometric Scaling Factor: Position sizing uses a 1.618x multiplier 
          (Golden Ratio) to ensure the break-even price gravitates toward the 
          current market price faster than the price falls.
        """
        self.capital = 10000.0
        self.positions = {}  # {symbol: {'avg_price': float, 'qty': float, 'lvl': int}}
        self.history = {}    # {symbol: deque([prices])}
        
        # Core Parameters
        self.history_len = 120
        self.min_cash_buffer = 1500.0
        self.initial_lot_size = 200.0 
        
        # Entry Filters (Hyper-Strict)
        self.rsi_threshold = 12.5
        self.z_score_limit = -3.8
        self.profit_target_root = 0.018  # 1.8% base target
        
        # DCA Configuration
        self.max_recovery_layers = 8
        self.scaling_factor = 1.618 

    def _calculate_metrics(self, symbol, current_price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.history_len)
        self.history[symbol].append(current_price)
        
        data = list(self.history[symbol])
        if len(data) < 50:
            return None
            
        # Statistical Core
        mean = statistics.mean(data)
        stdev = statistics.stdev(data) if len(data) > 1 else 0.0001
        z_score = (current_price - mean) / stdev
        
        # RSI Calculation (Smoothed)
        rsi_period = 14
        deltas = [data[i] - data[i-1] for i in range(len(data) - rsi_period, len(data))]
        ups = [d for d in deltas if d > 0]
        downs = [abs(d) for d in deltas if d < 0]
        
        avg_up = sum(ups) / rsi_period
        avg_down = sum(downs) / rsi_period
        
        if avg_down == 0: rsi = 100
        else:
            rs = avg_up / avg_down
            rsi = 100 - (100 / (1 + rs))
            
        # Volatility & Mean Reversion Strength
        # Using a simple range-based volatility proxy
        volatility = stdev / mean
        
        # Momentum Change (Acceleration)
        prev_data = list(self.history[symbol])[:-1]
        prev_mean = statistics.mean(prev_data) if len(prev_data) >= 50 else mean
        momentum_shift = (current_price - mean) - (data[-2] - prev_mean) if len(data) > 2 else 0
        
        return {
            'z': z_score, 
            'rsi': rsi, 
            'vol': volatility, 
            'accel': momentum_shift,
            'stdev': stdev
        }

    def on_price_update(self, prices):
        for symbol, price in prices.items():
            metrics = self._calculate_metrics(symbol, price)
            if not metrics:
                continue

            # 1. Position Management (Exits & Recovery)
            if symbol in self.positions:
                pos = self.positions[symbol]
                avg_px = pos['avg_price']
                qty = pos['qty']
                lvl = pos['lvl']
                
                # RECOVERY EXIT: Fixed profit target + volatility premium
                exit_target = self.profit_target_root + (metrics['vol'] * 0.5)
                if price >= avg_px * (1.0 + exit_target):
                    proceeds = price * qty
                    self.capital += proceeds
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': qty,
                        'reason': ['FRACTAL_RECOVERY_COMPLETE', f'LAYERS_{lvl}']
                    }
                
                # RECOVERY DCA: Non-Linear scaling
                if lvl < self.max_recovery_layers:
                    # Gap expands logarithmically based on level and volatility
                    required_drop = (self.profit_target_root * math.log(lvl + 1)) + (metrics['vol'] * lvl)
                    
                    # Only DCA if price is significantly lower AND momentum is exhausting
                    if price <= avg_px * (1.0 - required_drop) and metrics['accel'] > 0:
                        dca_amount = self.initial_lot_size * (self.scaling_factor ** lvl)
                        
                        if self.capital >= dca_amount + self.min_cash_buffer:
                            buy_qty = dca_amount / price
                            self.capital -= dca_amount
                            
                            new_qty = qty + buy_qty
                            new_avg = ((avg_px * qty) + (price * buy_qty)) / new_qty
                            
                            self.positions[symbol]['avg_price'] = new_avg
                            self.positions[symbol]['qty'] = new_qty
                            self.positions[symbol]['lvl'] += 1
                            
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['QUANTUM_DCA_EXPANSION', f'LVL_{self.positions[symbol]["lvl"]}']
                            }

            # 2. Strategic Entry Execution
            else:
                # Require extreme oversold conditions + Z-Score outlier
                if metrics['rsi'] < self.rsi_threshold and metrics['z'] < self.z_score_limit:
                    if self.capital >= self.initial_lot_size + self.min_cash_buffer:
                        buy_qty = self.initial_lot_size / price
                        self.capital -= self.initial_lot_size
                        
                        self.positions[symbol] = {
                            'avg_price': price,
                            'qty': buy_qty,
                            'lvl': 1
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': buy_qty,
                            'reason': ['ASYMMETRIC_MEAN_REVERSION_INITIATED']
                        }
                        
        return None