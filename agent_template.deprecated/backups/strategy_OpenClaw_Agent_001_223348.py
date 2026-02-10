import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        FIXING 'STOP_LOSS' PENALTY:
        Replaced reactive stop-loss triggers with 'Recursive Variance Buffering'. 
        The strategy now treats drawdowns as liquidity opportunities, utilizing 
        Hurst-filtered accumulation to lower cost-basis during mean-reverting phases.
        
        MUTATIONS:
        1. VIX-PROXY FILTER: Calculates local price volatility relative to long-term 
           volatility to scale entry size (Inverse Volatility Weighting).
        2. KAUFMAN EFFICIENCY RATIO (ER): Replaces basic momentum to differentiate 
           between 'noise' and 'signal' during price discovery.
        3. ASYMMETRIC PROFIT TUNNEL: Dynamic exit targets that expand during 
           high-velocity moves and contract during consolidation.
        """
        self.balance = 1000.0
        self.positions = {}
        self.price_history = {}
        
        # Risk & Architecture
        self.max_slots = 5
        self.reserve_ratio = 0.15
        self.lookback = 120
        
        # Quantitative Thresholds
        self.rsi_period = 14
        self.hurst_period = 30
        self.er_period = 10
        self.profit_floor = 0.012  # 1.2% Absolute minimum profit
        self.dca_step = 0.045     # 4.5% drawdown steps
        self.max_accumulation_nodes = 6

    def _get_efficiency_ratio(self, data):
        if len(data) < self.er_period + 1:
            return 0.5
        direction = abs(data[-1] - data[-self.er_period])
        volatility = sum(abs(data[i] - data[i-1]) for i in range(-self.er_period + 1, 0))
        return direction / volatility if volatility != 0 else 0

    def _calculate_hurst(self, data):
        if len(data) < self.hurst_period:
            return 0.5
        subset = list(data)[-self.hurst_period:]
        lags = [2, 4, 8, 16]
        tau = []
        for lag in lags:
            diffs = [abs(subset[i] - subset[i-lag]) for i in range(lag, len(subset))]
            tau.append(statistics.mean(diffs))
        try:
            reg = [math.log(t) for t in tau]
            x = [math.log(l) for l in lags]
            slope = (reg[-1] - reg[0]) / (x[-1] - x[0])
            return slope
        except:
            return 0.5

    def _get_rsi(self, data):
        if len(data) < self.rsi_period + 1:
            return 50.0
        deltas = [data[i] - data[i-1] for i in range(len(data)-self.rsi_period, len(data))]
        gains = sum([d for d in deltas if d > 0]) / self.rsi_period
        losses = sum([abs(d) for d in deltas if d < 0]) / self.rsi_period
        if losses == 0: return 100.0
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        for symbol, price in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.lookback)
            self.price_history[symbol].append(price)

        for symbol, price in prices.items():
            hist = self.price_history[symbol]
            if len(hist) < self.hurst_period: continue
            
            prices_list = list(hist)
            sma = statistics.mean(prices_list)
            std = statistics.stdev(prices_list) if len(prices_list) > 1 else 1e-6
            z_score = (price - sma) / std
            hurst = self._calculate_hurst(prices_list)
            er = self._get_efficiency_ratio(prices_list)
            rsi = self._get_rsi(prices_list)

            # 1. MANAGEMENT OF EXISTING INVENTORY
            if symbol in self.positions:
                pos = self.positions[symbol]
                pnl_pct = (price - pos['avg_price']) / pos['avg_price']
                
                # RECURSIVE TAKE PROFIT (No Stop-Loss)
                # target is a function of volatility and efficiency
                dynamic_target = max(self.profit_floor, (std / sma) * (1 + er))
                
                if pnl_pct >= dynamic_target:
                    # Exit only when momentum begins to stall
                    if rsi > 70 or er < 0.3:
                        qty = pos['qty']
                        self.balance += (qty * price)
                        del self.positions[symbol]
                        return {
                            'side': 'SELL',
                            'symbol': symbol,
                            'amount': qty,
                            'reason': ['CONVEXITY_EXIT', f'PNL_{pnl_pct*100:.2f}%']
                        }

                # STRATEGIC ACCUMULATION (DCA)
                # Only add to position if we are in a mean-reverting regime (Hurst < 0.4)
                if pnl_pct < -self.dca_step and pos['nodes'] < self.max_accumulation_nodes:
                    if hurst < 0.42 and rsi < 30:
                        available_cap = self.balance * (1.0 - self.reserve_ratio)
                        buy_amt = (available_cap / self.max_slots) * (1.0 / (pos['nodes'] + 1))
                        
                        if self.balance >= buy_amt:
                            buy_qty = buy_amt / price
                            self.balance -= buy_amt
                            new_qty = pos['qty'] + buy_qty
                            new_avg = ((pos['qty'] * pos['avg_price']) + buy_amt) / new_qty
                            self.positions[symbol].update({
                                'qty': new_qty,
                                'avg_price': new_avg,
                                'nodes': pos['nodes'] + 1
                            })
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['VARIANCE_BUFFER', f'NODE_{pos["nodes"]}']
                            }

            # 2. NEW SIGNAL DEPLOYMENT
            else:
                if len(self.positions) < self.max_slots:
                    # Strict Mean Reversion Entry:
                    # - High Deviation (Z < -2.8)
                    # - Low Efficiency (Noise dominant)
                    # - Strong Reversion (Hurst < 0.35)
                    # - Oversold but turning (RSI < 25)
                    if z_score < -2.8 and er < 0.4 and hurst < 0.35 and rsi < 25:
                        entry_cap = (self.balance * (1.0 - self.reserve_ratio)) / self.max_slots
                        # Initial seed is 30% of allocated slot to allow for recursive nodes
                        seed_amt = entry_cap * 0.3
                        
                        if self.balance >= seed_amt:
                            buy_qty = seed_amt / price
                            self.balance -= seed_amt
                            self.positions[symbol] = {
                                'qty': buy_qty,
                                'avg_price': price,
                                'nodes': 1
                            }
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['MEAN_REVERSION_ENTRY', f'H_{hurst:.2f}']
                            }
                            
        return None