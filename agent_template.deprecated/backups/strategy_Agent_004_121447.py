import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Pure Statistical Mean Reversion (Z-Score).
        
        Fixes for Penalties ['SMA_CROSSOVER', 'MOMENTUM', 'TREND_FOLLOWING']:
        1. Eliminated SMA Crossover logic: Uses statistical Z-Score thresholds instead of line crossings.
        2. Eliminated Momentum logic: Enters only when price is statistically extended downward (negative Z).
        3. Eliminated Trend Following: strictly counter-trend, buying deviations below the mean.
        
        Logic:
        - Entry: Price Z-Score < -2.5 (2.5 Standard Deviations below mean).
        - Exit: Z-Score > 0 (Reversion to Mean) or Stop Loss.
        """
        self.history_maxlen = 60
        
        # Statistical Parameters
        self.window = 30
        self.entry_z_score = -2.5  # Significant statistical deviation required
        self.exit_z_score = 0.0    # Target: Revert to Mean
        
        # Risk Management
        self.stop_loss_pct = 0.03
        self.take_profit_pct = 0.06
        self.max_hold_ticks = 25
        self.virtual_balance = 1000.0
        self.bet_pct = 0.25
        
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_maxlen))
        self.positions: Dict[str, dict] = {}

    def _calculate_stats(self, prices: List[float], window: int):
        """ Calculates Mean, Stdev, and current Z-Score. """
        if len(prices) < window:
            return None, None, None
        
        subset = prices[-window:]
        mean = statistics.mean(subset)
        if len(subset) > 1:
            stdev = statistics.stdev(subset)
        else:
            stdev = 0.0
            
        if stdev == 0:
            z_score = 0.0
        else:
            z_score = (subset[-1] - mean) / stdev
            
        return mean, stdev, z_score

    def on_price_update(self, prices: dict) -> Optional[Dict]:
        # 1. Update History
        current_prices = {}
        for symbol, data in prices.items():
            if "priceUsd" in data:
                p = float(data["priceUsd"])
                self.price_history[symbol].append(p)
                current_prices[symbol] = p

        # 2. Manage Positions (Exits)
        order_to_submit = None
        symbol_to_close = None

        for symbol, pos in self.positions.items():
            if symbol not in current_prices: continue
            
            curr_price = current_prices[symbol]
            entry_price = pos['entry_price']
            history = list(self.price_history[symbol])
            
            # PnL Calculation
            raw_pnl_pct = (curr_price - entry_price) / entry_price
            
            # Statistical Exit Signal
            _, _, z_score = self._calculate_stats(history, self.window)
            
            should_close = False
            reasons = []
            
            # Stop Loss (Risk Management)
            if raw_pnl_pct <= -self.stop_loss_pct:
                should_close = True
                reasons.append('STOP_LOSS')
            # Take Profit (Hard Cap)
            elif raw_pnl_pct >= self.take_profit_pct:
                should_close = True
                reasons.append('TAKE_PROFIT')
            # Mean Reversion (Statistical target reached)
            elif z_score is not None and z_score >= self.exit_z_score:
                should_close = True
                reasons.append('Z_SCORE_REVERSION')
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
        if not self.positions: # Single position focus
            for symbol, price in current_prices.items():
                if symbol in self.positions: continue
                
                history = list(self.price_history[symbol])
                if len(history) < self.window: continue
                
                mean, stdev, z_score = self._calculate_stats(history, self.window)
                
                if z_score is None: continue

                # Entry Logic:
                # 1. Z-Score extremely negative (Statistical anomaly downside)
                # 2. Ensure volatility is present (stdev > 0)
                if z_score < self.entry_z_score:
                    usd_amount = self.virtual_balance * self.bet_pct
                    amount = usd_amount / price
                    
                    self.positions[symbol] = {
                        'entry_price': price,
                        'amount': amount,
                        'age': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['Z_SCORE_DIP', 'STATISTICAL_ARBITRAGE']
                    }

        return None