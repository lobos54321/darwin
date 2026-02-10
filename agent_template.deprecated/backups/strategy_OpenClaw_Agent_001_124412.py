import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Regime-Filtered Mean Reversion (RFMR)
        
        Addressed Penalties:
        1. EFFICIENT_BREAKOUT: 
           - Implemented a Volatility Ratio Filter. We compare Short-Term Volatility (last 6 ticks)
             against Long-Term Volatility (40 ticks). If the ratio is high (> 1.8), it indicates
             a breakout or crash regime rather than normal noise. We pause trading to avoid falling knives.
             
        2. ER:0.004 (Low Edge):
           - Tightened Entry Criteria: Z-Score must be < -3.0 (Deep Value) and RSI < 26.
           - Increased Minimum Liquidity to ensure we trade stable, mean-reverting assets.
           - Sort candidates by Z-score to pick only the most statistically significant deviations.
           
        3. FIXED_TP:
           - Replaced fixed take-profit with Dynamic Z-Reversion Exit.
           - Trades exit when Z-score recovers to 0.2 (just above mean), adapting to the
             moving average rather than a rigid percentage.
           - Added Time-Decay exit to recycle capital if reversion fails to materialize quickly.
        """
        # Configuration
        self.window_size = 40           # Sufficient for statistical significance
        self.min_liquidity = 10000000.0 # High liquidity to ensure true mean reversion behavior
        self.max_positions = 3          # Concentrate capital on best setups
        self.trade_size_usd = 2000.0    # Fixed notional size per trade
        
        # Entry Filters (Stricter)
        self.entry_z_trigger = -3.0     # 3 Sigma deviation
        self.entry_rsi_trigger = 26     # Deep oversold
        self.vol_shock_threshold = 1.8  # Max allowed Volatility Ratio (ST/LT)
        
        # Exit Logic (Dynamic)
        self.exit_z_target = 0.2        # Target: Return to mean (slightly positive)
        self.stop_loss_pct = 0.07       # 7% Hard Stop
        self.max_hold_ticks = 60        # ~1 hour in minute-data terms (assuming 1m ticks)
        
        # State Management
        self.history = {}               # symbol -> deque(maxlen=window)
        self.positions = {}             # symbol -> dict (entry data)
        self.tick_count = 0

    def get_metrics(self, symbol, current_price):
        """Calculates Z-Score, RSI, and Volatility Regime Ratio."""
        if symbol not in self.history or len(self.history[symbol]) < self.window_size:
            return None
            
        prices = list(self.history[symbol])
        # Ensure current price is included in stats context if not already appended
        # (Though we append before calling this usually, safe to use list)
        
        # 1. Calculate Volatility & Z-Score
        try:
            mean = statistics.mean(prices)
            stdev = statistics.stdev(prices)
        except statistics.StatisticsError:
            return None
            
        if stdev == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        
        # 2. Volatility Regime Filter (Anti-Breakout)
        # Calculate short-term standard deviation (last 6 ticks)
        subset_prices = prices[-6:]
        if len(subset_prices) > 2:
            try:
                st_stdev = statistics.stdev(subset_prices)
                # Ratio of Short-Term Vol to Long-Term Vol
                # If > 1.0, vol is expanding. If > 1.8, it's a shock/breakout.
                vol_ratio = st_stdev / stdev
            except:
                vol_ratio = 1.0
        else:
            vol_ratio = 1.0

        # 3. RSI (Relative Strength Index) - 14 period
        rsi_period = 14
        if len(prices) > rsi_period:
            # Use last N prices for RSI
            rsi_subset = prices[-(rsi_period+1):]
            deltas = [rsi_subset[i] - rsi_subset[i-1] for i in range(1, len(rsi_subset))]
            
            gains = [d for d in deltas if d > 0]
            losses = [-d for d in deltas if d < 0]
            
            if not losses:
                rsi = 100
            elif not gains:
                rsi = 0
            else:
                avg_gain = sum(gains) / len(deltas) # Smoothed avg approximation
                avg_loss = sum(losses) / len(deltas)
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
        else:
            rsi = 50

        return {
            'z': z_score,
            'rsi': rsi,
            'vol_ratio': vol_ratio,
            'mean': mean
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Data Ingestion
        # We must update history for all eligible assets to maintain stats
        active_candidates = []
        
        for symbol, data in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(data['priceUsd'])
            
            # Filter for liquidity and history length
            if data['liquidity'] >= self.min_liquidity and len(self.history[symbol]) == self.window_size:
                active_candidates.append(symbol)

        # 2. Manage Exits (Priority)
        # Returns immediately if an exit is generated
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            metrics = self.get_metrics(symbol, current_price)
            
            should_sell = False
            reason = ''
            
            # ROI Calculation
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            
            # A. Stop Loss (Safety)
            if roi < -self.stop_loss_pct:
                should_sell = True
                reason = 'STOP_LOSS'
            
            # B. Time Decay (Opportunity Cost)
            elif self.tick_count - pos['entry_tick'] > self.max_hold_ticks:
                should_sell = True
                reason = 'TIMEOUT'
            
            # C. Dynamic Mean Reversion Exit (Fixes FIXED_TP)
            # If Z-score reverts to mean (or slightly above), the edge is captured.
            elif metrics and metrics['z'] >= self.exit_z_target:
                should_sell = True
                reason = 'MEAN_REVERSION_TARGET'
                
            if should_sell:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0, # 0.0 usually signals 'close full position'
                    'reason': [reason]
                }

        # 3. Manage Entries
        if len(self.positions) < self.max_positions:
            potential_trades = []
            
            for symbol in active_candidates:
                if symbol in self.positions:
                    continue
                    
                current_price = prices[symbol]['priceUsd']
                stats = self.get_metrics(symbol, current_price)
                
                if not stats:
                    continue
                
                # Check Entry Filters
                # 1. Deep Value (Z-Score)
                if stats['z'] < self.entry_z_trigger:
                    
                    # 2. Oversold (RSI)
                    if stats['rsi'] < self.entry_rsi_trigger:
                        
                        # 3. Volatility Regime Filter (Anti-EFFICIENT_BREAKOUT)
                        # We reject trades if short-term volatility is exploding relative to long-term
                        if stats['vol_ratio'] < self.vol_shock_threshold:
                            potential_trades.append((symbol, stats['z'], current_price))
            
            # Sort by deepest Z-score to prioritize the most extreme deviations
            potential_trades.sort(key=lambda x: x[1])
            
            if potential_trades:
                best_symbol, best_z, price = potential_trades[0]
                
                # Calculate Quantity based on USD size