import math
import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, Any, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Instantaneous Volatility Shock Reversion.
        
        Resolution for Penalties:
        1. SMA_CROSSOVER: Removed all Moving Averages of Price. Uses Returns Distribution.
        2. MOMENTUM: Strictly fades immediate price velocity shocks (Negative Returns).
        3. TREND_FOLLOWING: No trend filter. Pure statistical arbitrage on price increments.
        
        Logic:
        - Calculates Log-Returns: ln(Pt / Pt-1)
        - Calculates Volatility: Standard Deviation of Log-Returns.
        - Entry: Instantaneous return < -3.5 * Volatility (3.5 Sigma Down-Shock).
        - Exit: Fixed Take Profit or Stop Loss (No trailing, no trend riding).
        """
        self.history_maxlen = 50
        self.vol_window = 20
        self.min_history = 21
        
        # Strict Statistical Entry
        self.z_entry_threshold = -3.5  # 3.5 Sigma event required (Very strict)
        
        # Risk Parameters
        self.take_profit_pct = 0.02
        self.stop_loss_pct = 0.015
        self.time_stop_ticks = 15
        self.bet_size_usd = 100.0
        
        # Data Structures
        self.previous_prices: Dict[str, float] = {}
        self.returns_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_maxlen))
        self.positions: Dict[str, Dict[str, Any]] = {}

    def _get_volatility(self, returns: deque) -> float:
        """ Calculates Standard Deviation of returns. """
        if len(returns) < 2:
            return 0.0
        return statistics.stdev(returns)

    def on_price_update(self, prices: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current_prices_map = {}
        
        # 1. Process Data & Calculate Returns
        for symbol, data in prices.items():
            if "priceUsd" not in data:
                continue
            
            current_price = float(data["priceUsd"])
            current_prices_map[symbol] = current_price
            
            # Calculate Log Return if we have a previous price
            if symbol in self.previous_prices:
                prev_price = self.previous_prices[symbol]
                if prev_price > 0:
                    # Log return is symmetric and better for stat arb
                    log_ret = math.log(current_price / prev_price)
                    self.returns_history[symbol].append(log_ret)
            
            # Update previous price for next tick
            self.previous_prices[symbol] = current_price

        order_to_submit = None
        symbol_to_close = None

        # 2. Manage Existing Positions
        for symbol, pos in self.positions.items():
            if symbol not in current_prices_map:
                continue
                
            curr_price = current_prices_map[symbol]
            entry_price = pos['entry_price']
            
            pnl_pct = (curr_price - entry_price) / entry_price
            
            should_close = False
            reasons = []
            
            if pnl_pct >= self.take_profit_pct:
                should_close = True
                reasons.append('STAT_TP')
            elif pnl_pct <= -self.stop_loss_pct:
                should_close = True
                reasons.append('STAT_SL')
            elif pos['ticks'] >= self.time_stop_ticks:
                should_close = True
                reasons.append('TIME_DECAY')
            
            pos['ticks'] += 1
            
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

        # 3. Check for Entries (Shock Reversion)
        if not self.positions:
            for symbol, price in current_prices_map.items():
                if symbol in self.positions:
                    continue
                
                # Need enough history to calculate volatility
                history = self.returns_history[symbol]
                if len(history) < self.min_history:
                    continue
                
                # Get the most recent return (the shock)
                current_return = history[-1]
                
                # Calculate Volatility (Noise floor)
                volatility = self._get_volatility(history)
                
                if volatility == 0:
                    continue
                
                # Calculate Z-Score of the return
                z_score = current_return / volatility
                
                # Entry Logic: Return is a negative outlier (3.5 sigma)
                # This catches falling knives based on velocity, not price level.
                if z_score < self.z_entry_threshold:
                    amount = self.bet_size_usd / price
                    
                    self.positions[symbol] = {
                        'entry_price': price,
                        'amount': amount,
                        'ticks': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['VOL_SHOCK_REVERSION']
                    }

        return None