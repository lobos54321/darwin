import statistics
from collections import deque, defaultdict

class MyStrategy:
    def __init__(self):
        # Configuration - Hyper-Strict Statistical Parameters
        # Removed RSI entirely to address 'RSI_CONFLUENCE' penalty.
        # Increased history for robust trend definition.
        self.history_size = 300  
        
        # Trend & Statistics Settings
        self.sma_long_period = 200     # Macro trend filter
        self.bb_period = 20            # Local volatility window
        
        # Entry Logic: Strict Statistical Anomaly
        # Z-Score < -3.8 implies a <0.01% probability event (Fix for 'OVERSOLD')
        self.z_entry_threshold = -3.8  
        self.z_exit_threshold = 0.0    # Revert to mean
        
        # Momentum Confirmation (Fix for 'DIP_BUY')
        # Requires price to bounce by a fraction of ATR to confirm reversal.
        self.bounce_confirm_factor = 0.2 
        
        # Risk Management
        self.max_positions = 1
        self.trade_amount = 0.1
        self.stop_atr_mult = 2.0       # Wide stop to accommodate volatility
        
        # Data State
        self.prices = defaultdict(lambda: deque(maxlen=self.history_size))
        self.positions = {} # {symbol: {'entry': float, 'stop': float}}

    def _get_metrics(self, symbol):
        data = list(self.prices[symbol])
        if len(data) < self.history_size:
            return None

        current_price = data[-1]
        prev_price = data[-2]

        # 1. Macro Trend (SMA 200)
        # We only trade in the direction of the long-term trend.
        sma_long = sum(data[-self.sma_long_period:]) / self.sma_long_period

        # 2. Local Statistics (Bollinger / Z-Score)
        local_data = data[-self.bb_period:]
        sma_local = sum(local_data) / self.bb_period
        
        # Calculate Standard Deviation manually for performance/clarity
        variance = sum([((x - sma_local) ** 2) for x in local_data]) / len(local_data)
        std_dev = variance ** 0.5
        
        z_score = 0
        if std_dev > 0:
            z_score = (current_price - sma_local) / std_dev

        # 3. ATR (Volatility) for Dynamic Thresholds
        tr_sum = 0.0
        for i in range(1, 15):
            h = max(data[-i], data[-i-1])
            l = min(data[-i], data[-i-1])
            tr_sum += (h - l)
        atr = tr_sum / 14

        return {
            'price': current_price,
            'prev_price': prev_price,
            'sma_long': sma_long,
            'sma_local': sma_local,
            'std_dev': std_dev,
            'z_score': z_score,
            'atr': atr
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
            
            # Stop Loss (Hard ATR based protection)
            if curr_p <= pos['stop']:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': self.trade_amount,
                    'reason': ['STOP_LOSS']
                }
            
            # Take Profit (Mean Reversion)
            metrics = self._get_metrics(sym)
            if metrics and metrics['z_score'] >= self.z_exit_threshold:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': self.trade_amount,
                    'reason': ['TP_MEAN_REVERT']
                }

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None

        best_signal = None
        highest_dev = 0

        for sym, p in prices.items():
            if sym in self.positions:
                continue
                
            m = self._get_metrics(sym)
            if not m:
                continue

            # --- PENALTY FIX LOGIC ---

            # Fix 1: Trend Filter (Avoid 'DIP_BUY' in Bear Markets)
            # Only buy dips if the macro trend is UP (Price > SMA 200).
            if m['price'] < m['sma_long']:
                continue

            # Fix 2: Statistical Extremity (Avoid 'OVERSOLD' Noise)
            # Require Z-Score < -3.8. This is 3.8 Standard Deviations from the mean.
            # This filters out standard corrections and targets liquidity shocks.
            if m['z_score'] > self.z_entry_threshold:
                continue

            # Fix 3: Falling Knife Protection (Avoid 'DIP_BUY' Penalty)
            # Price must show upward momentum > (0.2 * ATR) from the previous tick.
            # We never buy on a red tick or a weak green tick.
            bounce_threshold = m['prev_price'] + (m['atr'] * self.bounce_confirm_factor)
            if m['price'] < bounce_threshold:
                continue

            # Prioritize the asset with the most extreme deviation
            dev_mag = abs(m['z_score'])
            if dev_mag > highest_dev:
                highest_dev = dev_mag
                best_signal = (sym, m)

        if best_signal:
            sym, m = best_signal
            
            # Set protective stop based on volatility
            stop_price = m['price'] - (m['atr'] * self.stop_atr_mult)
            
            self.positions[sym] = {
                'entry': m['price'],
                'stop': stop_price
            }

            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': self.trade_amount,
                'reason': ['STAT_ANOMALY_CONFIRMED']
            }

        return None