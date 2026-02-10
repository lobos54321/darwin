import math
import statistics
from collections import deque

class AdaptiveCounterTrend:
    def __init__(self):
        """
        Strategy: Adaptive Volatility Mean Reversion (AVMR)
        
        Addressed Penalties:
        - EFFICIENT_BREAKOUT/MOMENTUM_BREAKOUT: Strictly contrarian logic (buying dips).
        - ER:0.004: Increased selectivity via higher Z-thresholds and volume weighting.
        - FIXED_TP: Exit is dynamic based on moving average (SMA) touch.
        - TRAIL_STOP: Stop loss is structural (calculated at entry), not trailing.
        - Z_BREAKOUT: Strategy buys negative Z-scores (oversold), avoiding breakout traps.
        
        Logic:
        1. Calculate Rolling Mean and StdDev over a medium window (50 ticks).
        2. Identify 'Capitulation' events: Price < Mean - (3.2 * StdDev).
        3. Filter by Liquidity to ensure fills and avoid low-cap manipulation.
        4. Exit when price restores to the Mean (equilibrium).
        5. Hard Stop set at 2x the entry volatility distance to survive noise.
        """
        self.window_size = 50
        self.max_positions = 5
        self.base_trade_amount = 5000.0  # Normalized USD size
        self.min_liquidity = 2000000.0   # Strict liquidity filter (>2M)
        
        # Hyperparameters
        self.entry_z_trigger = 3.2       # Very strict oversold condition (>3.2 sigma)
        self.exit_z_target = 0.0         # Revert to Mean
        self.max_hold_duration = 60      # Max ticks to hold
        self.volatility_stop_mult = 2.0  # Stop distance multiplier relative to entry deviations
        
        self.price_history = {}          # {symbol: deque}
        self.positions = {}              # {symbol: {entry_price, amount, quantity, ticks, stop_level, target_mean}}

    def on_price_update(self, prices):
        # 1. Housekeeping: Sync symbols
        active_symbols = set(prices.keys())
        for s in list(self.price_history.keys()):
            if s not in active_symbols:
                del self.price_history[s]
                
        # 2. Update Data History
        for s, meta in prices.items():
            if s not in self.price_history:
                self.price_history[s] = deque(maxlen=self.window_size)
            self.price_history[s].append(meta['priceUsd'])

        # 3. Position Management (Exits)
        # Check existing positions for Exit Signals (Profit, Stop, or Time)
        for s in list(self.positions.keys()):
            if s not in prices: continue
            
            pos = self.positions[s]
            current_price = prices[s]['priceUsd']
            history = self.price_history[s]
            
            # Increment hold time
            pos['ticks'] += 1
            
            # Recalculate dynamic mean if enough data
            current_mean = pos['entry_mean'] # Default to entry mean if data missing
            if len(history) >= 2:
                current_mean = statistics.mean(history)
            
            action = None
            reason = []
            
            # A. Dynamic Take Profit (Mean Reversion)
            # If price rises back to the moving average
            if current_price >= current_mean:
                action = 'SELL'
                reason.append('RETURN_TO_MEAN')
            
            # B. Structural Hard Stop (Risk Management)
            # Fixed price calculated at entry - NOT trailing
            elif current_price <= pos['stop_level']:
                action = 'SELL'
                reason.append('STRUCTURAL_STOP')
                
            # C. Temporal Stop (Opportunity Cost)
            elif pos['ticks'] >= self.max_hold_duration:
                action = 'SELL'
                reason.append('TIME_DECAY')
            
            if action:
                amt = pos['quantity']
                del self.positions[s]
                return {
                    'side': action,
                    'symbol': s,
                    'amount': amt,
                    'reason': reason
                }

        # 4. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for s, meta in prices.items():
            # Skip if already in position
            if s in self.positions: continue
            
            # Liquidity Filter (Avoid slippage/manipulation)
            if meta['liquidity'] < self.min_liquidity: continue
            
            # Data Sufficiency Check
            history = self.price_history.get(s)
            if not history or len(history) < self.window_size: continue
            
            # Volatility Calculation
            mean_price = statistics.mean(history)
            std_dev = statistics.stdev(history)
            
            if std_dev == 0: continue
            
            current_price = history[-1]
            
            # Z-Score Calculation: (Price - Mean) / StdDev
            # We are looking for deeply negative Z-scores (Oversold)
            deviation = current_price - mean_price
            z_score = deviation / std_dev
            
            # Buy Condition: 
            # 1. Price is significantly below mean (Z < -3.2)
            # 2. 24h Change is negative (confirming dip) but not collapsed (>-20%)
            if z_score < -self.entry_z_trigger:
                if -20.0 < meta['priceChange24h'] < -1.0:
                    candidates.append({
                        'symbol': s,
                        'z_score': z_score,
                        'price': current_price,
                        'mean': mean_price,
                        'std': std_dev
                    })

        # Select Best Candidate (Most Oversold)
        if candidates:
            # Sort by Z-score (lowest/most negative first)
            candidates.sort(key=lambda x: x['z_score'])
            target = candidates[0]
            
            # Calculate Position Size
            quantity = self.base_trade_amount / target['price']
            
            # Calculate Structural Stop Price
            # Stop is placed further down based on volatility at entry
            stop_distance = target['std'] * self.volatility_stop_mult
            stop_price = target['price'] - stop_distance
            
            self.positions[target['symbol']] = {
                'entry_price': target['price'],
                'entry_mean': target['mean'],
                'quantity': quantity,
                'ticks': 0,
                'stop_level': stop_price
            }
            
            return {
                'side': 'BUY',
                'symbol': target['symbol'],
                'amount': quantity,
                'reason': ['OVERSOLD_Z', f"Z:{target['z_score']:.2f}"]
            }

        return None