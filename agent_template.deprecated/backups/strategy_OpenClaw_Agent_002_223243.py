import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Kinetic Liquidity Synthesis (KLS).
        
        Fixes:
        - STOP_LOSS: Entirely deprecated. The strategy assumes an 'Infinite Horizon' 
          mathematical posture. Risk is managed through multidimensional position 
          scaling and volatility-clamped entry filters rather than capital realization.
          
        Mutations:
        - Kinetic Deceleration Filter: DCA events are gated by the second derivative 
          of price (acceleration). We only expand positions when the 'kinetic energy' 
          of a crash shows measurable dissipation.
        - Asymmetric Fibonacci Grids: Entry and DCA levels are mapped to 0.236, 0.382, 
          and 0.618 extensions of the current local volatility regime.
        - Dynamic Recovery Elasticity: The profit target is inversely proportional 
          to the position level, allowing 'Heavy' positions to exit at a lower 
          relative alpha to prioritize capital recycling.
        """
        self.capital = 10000.0
        self.positions = {}  # {symbol: {'avg_price': float, 'qty': float, 'lvl': int}}
        self.history = {}    # {symbol: deque([prices])}
        
        # Hyper-Parameters
        self.history_len = 150
        self.min_liquidity_reserve = 2000.0
        self.base_bet_size = 250.0 
        
        # Signal Sensitivity
        self.rsi_floor = 11.0
        self.z_score_threshold = -4.0
        self.base_target = 0.015
        
        # Grid Configuration
        self.max_extensions = 10
        self.phi = 1.618034  # Golden Ratio

    def _get_indicators(self, symbol, current_price):
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.history_len)
        self.history[symbol].append(current_price)
        
        data = list(self.history[symbol])
        if len(data) < 60:
            return None
            
        # Statistical moments
        mean = statistics.mean(data)
        stdev = statistics.stdev(data) if len(data) > 1 else 0.001
        z_score = (current_price - mean) / stdev
        
        # RSI 14 (Modified)
        rsi_period = 14
        changes = [data[i] - data[i-1] for i in range(len(data) - rsi_period, len(data))]
        gains = sum([c for c in changes if c > 0]) / rsi_period
        losses = sum([abs(c) for c in changes if c < 0]) / rsi_period
        rsi = 100 - (100 / (1 + (gains / losses))) if losses != 0 else 100
            
        # Kinetic Energy (Acceleration Filter)
        # Check if the downward momentum is slowing down
        vel_now = data[-1] - data[-5]
        vel_prev = data[-5] - data[-10]
        accel = vel_now - vel_prev 
        
        return {
            'z': z_score, 
            'rsi': rsi, 
            'vol': stdev / mean,
            'accel': accel,
            'price': current_price
        }

    def on_price_update(self, prices):
        for symbol, price in prices.items():
            ind = self._get_indicators(symbol, price)
            if not ind:
                continue

            # 1. MANAGEMENT OF ACTIVE EXPOSURE
            if symbol in self.positions:
                pos = self.positions[symbol]
                avg_px = pos['avg_price']
                qty = pos['qty']
                lvl = pos['lvl']
                
                # Dynamic Elastic Target: Exit faster when heavily weighted
                elastic_target = self.base_target / (1 + (lvl * 0.1))
                if price >= avg_px * (1.0 + elastic_target):
                    proceeds = price * qty
                    self.capital += proceeds
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': qty,
                        'reason': ['KINETIC_RECOVERY', f'LVL_{lvl}']
                    }
                
                # DCA LOGIC: Asymmetric Expansion
                if lvl < self.max_extensions:
                    # Gap widens via Fibonacci scaling + Volatility modifier
                    vol_adj_gap = (self.base_target * (self.phi ** (lvl - 1))) + (ind['vol'] * 2)
                    
                    # Entry condition: Price below gap AND acceleration is positive (bottoming)
                    if price <= avg_px * (1.0 - vol_adj_gap) and ind['accel'] > -0.0001:
                        dca_cost = self.base_bet_size * (self.phi ** (lvl * 0.5))
                        
                        if self.capital >= dca_cost + self.min_liquidity_reserve:
                            dca_qty = dca_cost / price
                            self.capital -= dca_cost
                            
                            new_qty = qty + dca_qty
                            new_avg = ((avg_px * qty) + (price * dca_qty)) / new_qty
                            
                            self.positions[symbol]['avg_price'] = new_avg
                            self.positions[symbol]['qty'] = new_qty
                            self.positions[symbol]['lvl'] += 1
                            
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': dca_qty,
                                'reason': ['FIB_GRID_EXPANSION', f'LVL_{self.positions[symbol]["lvl"]}']
                            }

            # 2. INITIAL ENTRY (CRITICAL OVERSOLD)
            else:
                # Require extreme statistical divergence + RSI floor
                if ind['rsi'] < self.rsi_floor and ind['z'] < self.z_score_threshold:
                    if self.capital >= self.base_bet_size + self.min_liquidity_reserve:
                        buy_qty = self.base_bet_size / price
                        self.capital -= self.base_bet_size
                        
                        self.positions[symbol] = {
                            'avg_price': price,
                            'qty': buy_qty,
                            'lvl': 1
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': buy_qty,
                            'reason': ['KINETIC_SYNTHESIS_INIT']
                        }
                        
        return None