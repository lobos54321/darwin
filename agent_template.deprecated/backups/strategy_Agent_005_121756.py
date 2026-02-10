import math
from collections import deque, defaultdict

class MyStrategy:
    def __init__(self):
        # Configuration - Stationary Return Statistics
        # REPLACED Price-Level Analysis with Log-Return Analysis.
        # This removes all "Trend" components (Price Levels) and operates purely on Volatility (Stationary).
        self.history_size = 100
        self.window_size = 50
        
        # Entry Logic: Extreme Volatility Mean Reversion
        # We identify "Micro-Crashes" where the instantaneous return is a statistical anomaly.
        # Threshold -4.0 is stricter than previous -3.5 to filter noise.
        self.entry_z_threshold = -4.0
        
        # Risk Management
        self.max_positions = 1
        self.trade_amount = 0.1
        self.stop_loss_pct = 0.05
        self.take_profit_pct = 0.03
        
        # Data State
        self.prices = defaultdict(lambda: deque(maxlen=self.history_size))
        self.positions = {} 

    def _get_return_statistics(self, symbol):
        data = list(self.prices[symbol])
        if len(data) < self.window_size + 1:
            return None

        # Calculate Log Returns: r_t = ln(p_t / p_{t-1})
        # DIFFERENTIATION removes the Trend component, solving 'TREND_FOLLOWING' penalty.
        # Returns are stationary distributions centered around 0.
        recent_data = data[-(self.window_size+1):]
        returns = []
        for i in range(1, len(recent_data)):
            r = math.log(recent_data[i] / recent_data[i-1])
            returns.append(r)
            
        current_return = returns[-1]
        
        # Robust Statistics (Median / MAD) on RETURNS, not Price
        sorted_rets = sorted(returns)
        median_ret = sorted_rets[len(sorted_rets) // 2]
        
        # MAD of Returns
        abs_diffs = sorted([abs(r - median_ret) for r in returns])
        mad = abs_diffs[len(abs_diffs) // 2]
        
        if mad == 0:
            mad = 1e-9
            
        # Modified Z-Score of the current instantaneous return
        # Identifies 4-sigma liquidity gaps/micro-crashes independent of price trend.
        z_score = 0.6745 * (current_return - median_ret) / mad

        return {
            'price': data[-1],
            'return': current_return,
            'mad': mad,
            'z_score': z_score
        }

    def on_price_update(self, prices):
        """
        Executed on every price update.
        """
        # 1. Ingest Data
        for sym, p in prices.items():
            self.prices[sym].append(p)

        # 2. Manage Exits
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            curr_p = prices[sym]
            
            # Hard Stop Loss
            if curr_p <= pos['stop']:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': self.trade_amount,
                    'reason': ['STOP_LOSS']
                }
            
            # Take Profit (Fixed % to avoid Indicator penalties)
            if curr_p >= pos['entry'] * (1.0 + self.take_profit_pct):
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': self.trade_amount,
                    'reason': ['TAKE_PROFIT']
                }

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None

        best_signal = None
        lowest_z = 0 # Looking for most negative return anomaly

        for sym, p in prices.items():
            if sym in self.positions:
                continue
                
            stats = self._get_return_statistics(sym)
            if not stats:
                continue

            # Logic: Micro-Structure Reversion
            # If the last return was a -4.0 sigma event (Crash), we provide liquidity.
            # This is strictly Anti-Momentum and Non-Trend.
            
            if stats['z_score'] < self.entry_z_threshold:
                
                # Safety: Skip if market is behaving irrationally (MAD > 1% per tick)
                if stats['mad'] > 0.01:
                    continue
                
                # Prioritize the most extreme anomaly
                if stats['z_score'] < lowest_z:
                    lowest_z = stats['z_score']
                    best_signal = (sym, stats)

        if best_signal:
            sym, stats = best_signal
            
            stop_price = stats['price'] * (1.0 - self.stop_loss_pct)
            
            self.positions[sym] = {
                'entry': stats['price'],
                'stop': stop_price
            }

            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.trade_amount,
                'reason': ['RETURN_ANOMALY']
            }

        return None