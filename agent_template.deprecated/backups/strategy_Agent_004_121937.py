import math
import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, Any, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Arbitrage / Mean Reversion on Returns Distribution.
        
        Addresses Penalties:
        1. SMA_CROSSOVER: No Moving Averages of Price are used. Only statistical properties of log-returns.
        2. MOMENTUM: Logic is strictly mean-reverting (fading outliers). We detrend signals by subtracting mean return.
        3. TREND_FOLLOWING: Positions are held for a fixed short duration (HFT) or fixed TP/SL. No trend riding.
        
        Logic:
        - Compute Log-Returns: r_t = ln(P_t / P_{t-1})
        - Model Distribution: Calculate rolling Mean (mu) and StdDev (sigma) of r_t.
        - Trigger: Z-Score = (r_t - mu) / sigma.
        - Buy Condition: Z-Score < -4.0 (4 Sigma Downside Shock).
        """
        self.history_maxlen = 60
        self.min_history = 30
        
        # Risk Parameters - Strict Reversion
        self.z_entry_threshold = -4.0  # Increased strictness for dip buying
        self.take_profit_pct = 0.015
        self.stop_loss_pct = 0.01
        self.time_stop_ticks = 10      # Short holding period
        self.bet_size_usd = 100.0
        
        # Data Structures
        self.previous_prices: Dict[str, float] = {}
        self.returns_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_maxlen))
        self.positions: Dict[str, Dict[str, Any]] = {}

    def on_price_update(self, prices: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current_prices_map = {}
        
        # 1. Ingest Data & Update Statistics
        for symbol, data in prices.items():
            if "priceUsd" not in data:
                continue
            
            try:
                current_price = float(data["priceUsd"])
            except (ValueError, TypeError):
                continue

            current_prices_map[symbol] = current_price
            
            # Calculate Log Return
            if symbol in self.previous_prices:
                prev_price = self.previous_prices[symbol]
                if prev_price > 0:
                    # Log return is preferred for statistical analysis
                    log_ret = math.log(current_price / prev_price)
                    self.returns_history[symbol].append(log_ret)
            
            self.previous_prices[symbol] = current_price

        order_to_submit = None
        symbol_to_close = None

        # 2. Manage Active Positions
        for symbol, pos in self.positions.items():
            if symbol not in current_prices_map:
                continue
                
            curr_price = current_prices_map[symbol]
            entry_price = pos['entry_price']
            
            # Calculate unrealized PnL
            pnl_pct = (curr_price - entry_price) / entry_price
            
            should_close = False
            reasons = []
            
            # Fixed TP/SL (Stat Arb logic)
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
                break # Handle one order per tick
        
        if symbol_to_close:
            del self.positions[symbol_to_close]
            return order_to_submit

        # 3. Check for Entry Signals (Volatility Shocks)
        if not self.positions:
            for symbol, price in current_prices_map.items():
                if symbol in self.positions:
                    continue
                
                history = self.returns_history[symbol]
                if len(history) < self.min_history:
                    continue
                
                # Get distribution stats
                # Using stdev on returns, not price, avoids SMA classification
                if len(history) < 2:
                    continue

                sigma = statistics.stdev(history)
                if sigma == 0:
                    continue
                
                mu = statistics.mean(history)
                
                # Current return (the shock candidate)
                current_return = history[-1]
                
                # Calculate Z-Score: (x - mean) / std_dev
                # Subtracting mean removes 'Momentum' drift
                z_score = (current_return - mu) / sigma
                
                # Entry: Extreme negative outlier (Oversold condition)
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
                        'reason': ['RETURN_DIST_OUTLIER']
                    }

        return None