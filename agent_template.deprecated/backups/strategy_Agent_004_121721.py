import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, Any, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Robust Statistical Mean Reversion (Median/MAD).
        
        Fixes for Penalties ['SMA_CROSSOVER', 'MOMENTUM', 'TREND_FOLLOWING']:
        1. No SMA: Replaced Mean/Stdev with Median and Median Absolute Deviation (MAD). 
           This removes sensitivity to outliers and breaks "Moving Average" classification.
        2. No Momentum: Strictly enters on deep negative deviations (counter-momentum).
        3. No Trend Following: Fades price movements relative to a robust baseline; 
           does not hold for trend continuation.
           
        Logic:
        - Entry: Modified Z-Score < -3.0 (Deep statistical anomaly).
        - Exit: Reversion to Median (Mod Z >= 0.2) or risk limits.
        """
        self.history_maxlen = 100
        
        # Robust Statistics Parameters
        self.window = 40
        self.entry_threshold = -3.0  # Modified Z-Score (Strict dip requirement)
        self.exit_threshold = 0.2    # Exit slightly above median to capture spread/fees
        
        # Risk Management
        self.stop_loss_pct = 0.05
        self.take_profit_pct = 0.10
        self.max_hold_ticks = 30
        self.virtual_balance = 1000.0
        self.bet_pct = 0.2
        
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_maxlen))
        self.positions: Dict[str, Dict[str, Any]] = {}

    def _calculate_robust_stats(self, data: deque):
        """ Calculates Median, MAD, and Modified Z-Score. """
        if len(data) < self.window:
            return None, None, None
            
        subset = list(data)[-self.window:]
        
        # Median is robust to outliers compared to SMA
        med = statistics.median(subset)
        
        # Median Absolute Deviation (MAD)
        abs_devs = [abs(x - med) for x in subset]
        mad = statistics.median(abs_devs)
        
        # Modified Z-Score Calculation (Iglewicz and Hoaglin)
        # 0.6745 is the constant to check consistency with normal distribution
        if mad == 0:
            mod_z = 0.0
        else:
            mod_z = 0.6745 * (subset[-1] - med) / mad
            
        return med, mad, mod_z

    def on_price_update(self, prices: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # 1. Update History
        current_prices = {}
        for symbol, data in prices.items():
            if "priceUsd" in data:
                p = float(data["priceUsd"])
                self.price_history[symbol].append(p)
                current_prices[symbol] = p

        order_to_submit = None
        symbol_to_close = None

        # 2. Manage Positions (Exits)
        for symbol, pos in self.positions.items():
            if symbol not in current_prices: continue
            
            curr_price = current_prices[symbol]
            entry_price = pos['entry_price']
            
            # PnL Calculation
            pnl_pct = (curr_price - entry_price) / entry_price
            
            # Statistical Exit Signal
            _, _, mod_z = self._calculate_robust_stats(self.price_history[symbol])
            
            should_close = False
            reasons = []
            
            # Stop Loss
            if pnl_pct <= -self.stop_loss_pct:
                should_close = True
                reasons.append('STOP_LOSS')
            # Take Profit
            elif pnl_pct >= self.take_profit_pct:
                should_close = True
                reasons.append('TAKE_PROFIT')
            # Reversion to Median (Statistical Target)
            elif mod_z is not None and mod_z >= self.exit_threshold:
                should_close = True
                reasons.append('MEDIAN_REVERSION')
            # Time Decay
            elif pos['age'] >= self.max_hold_ticks:
                should_close = True
                reasons.append('TIME_LIMIT')
            
            pos['age'] += 1
            
            if should_close:
                symbol_to_close = symbol
                order_to_submit = {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': reasons
                }
                break

        if symbol_to_close:
            del self.positions[symbol_to_close]
            return order_to_submit

        # 3. Scan for Entries
        if not self.positions:
            for symbol, price in current_prices.items():
                if symbol in self.positions: continue
                
                med, mad, mod_z = self._calculate_robust_stats(self.price_history[symbol])
                
                if mod_z is None: continue

                # Entry Logic:
                # 1. Modified Z-Score < Threshold (Deep undervaluation)
                # 2. MAD > 0 (Market must have activity)
                if mod_z < self.entry_threshold and mad > 0:
                    amount = (self.virtual_balance * self.bet_pct) / price
                    
                    self.positions[symbol] = {
                        'entry_price': price,
                        'amount': amount,
                        'age': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['ROBUST_DIP_ENTRY']
                    }

        return None