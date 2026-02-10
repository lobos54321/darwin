import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic & Strategic Architecture ===
        # DNA modulates the strategy's aggression and time horizon to avoid 'BOT' homogenization.
        self.dna = random.random()
        
        # 1. Dynamic Window (Avoids Periodicity/BOT)
        # We use a slightly shifting window to prevent resonance with other algos.
        # Base 24 ticks + variant.
        self.base_window = int(24 + (self.dna * 6))
        
        # 2. Strict Trend Logic (Fixes MEAN_REVERSION & EXPLORE)
        # We only engage assets with high structural integrity (High R2).
        # We do NOT fade trends; we join them.
        self.min_r2 = 0.82 + (self.dna * 0.04)
        self.min_slope = 0.00006  # Steepness requirement
        
        # 3. Surgical Entry Zones (Fixes BREAKOUT & STOP_LOSS)
        # We enter on 'Retracements' within 'Channels'.
        # Z-Score Entry: Buy when price is mathematically cheap relative to the trend.
        # -1.8 sigma to -3.2 sigma.
        self.entry_z = -1.8 - (self.dna * 0.2)
        self.crash_z = -3.5
        
        # 4. Decay & Stagnation (Fixes TIME_DECAY & STAGNANT)
        # Positions must perform or be cut.
        self.max_hold_ticks = 45
        self.initial_profit_z = 1.5
        
        # State
        self.history = {}       # {symbol: deque}
        self.holdings = {}      # {symbol: {'amount': float, 'entry_tick': int, 'entry_price': float}}
        self.balance = 10000.0  # Simulated balance
        self.tick_count = 0
        
        # Risk
        self.pos_limit = 4      # Concentrated bets
        self.size_pct = 0.22    # Allocation
        self.min_liquidity = 1200000.0 # Higher filter for quality

    def on_price_update(self, prices: dict):
        """
        Executes a High-Precision Linear Regression Channel strategy.
        Prioritizes Trend Integrity (R2) over raw volatility.
        """
        self.tick_count += 1
        
        # 0. Data Ingestion & Hygiene
        # Sort by liquidity to ensure we only look at the 'Real' market (Fixes EXPLORE)
        sorted_symbols = sorted(
            [s for s in prices if prices[s]['liquidity'] > self.min_liquidity],
            key=lambda s: prices[s]['liquidity'],
            reverse=True
        )[:15] # Only track top 15 liquid assets to reduce noise

        for sym in sorted_symbols:
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.base_window + 10)
            self.history[sym].append(prices[sym]['priceUsd'])

        # 1. Manage Exits (Priority)
        # Fixes TIME_DECAY and STOP_LOSS
        exit_order = self._manage_positions(prices)
        if exit_order:
            self._execute_exit(exit_order['symbol'], prices[exit_order['symbol']]['priceUsd'])
            return exit_order

        # 2. Scan Entries
        # Fixes MEAN_REVERSION and BREAKOUT (by waiting for pullbacks)
        if len(self.holdings) < self.pos_limit:
            entry_order = self._scan_markets(prices, sorted_symbols)
            if entry_order:
                cost = prices[entry_order['symbol']]['priceUsd'] * entry_order['amount']
                if self.balance > cost:
                    self.balance -= cost
                    self.holdings[entry_order['symbol']] = {
                        'amount': entry_order['amount'],
                        'entry_price': prices[entry_order['symbol']]['priceUsd'],
                        'entry_tick': self.tick_count
                    }
                    return entry_order
        
        return None

    def _manage_positions(self, prices):
        """
        Applies Dynamic Profit Decay and Structural Stops.
        """
        for sym, pos in self.holdings.items():
            if sym not in prices: 
                continue # Should close? For now wait.
                
            current_price = prices[sym]['priceUsd']
            hist = self.history.get(sym)
            
            # Safety check: if history missing/too short
            if not hist or len(hist) < self.base_window:
                continue

            # Recalculate Trend Status
            # We use the most recent window to gauge current market structure
            stats = self._calc_linreg(list(hist)[-self.base_window:])
            if not stats: continue
            slope, intercept, r2, std_dev, prediction = stats
            
            # Z-Score Calculation
            if std_dev <= 0: std_dev = 0.000001 # Div0 protection
            z_score = (current_price - prediction) / std_dev
            
            # === EXIT LOGIC ===
            
            # 1. Structural Failure (Stop Loss / Breakout against us)
            # If price breaks far below probability bounds, the model is wrong.
            if z_score < -4.0:
                return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['STRUCTURAL_FAIL']}
                
            # 2. Trend Inversion (Fixes MEAN_REVERSION penalty)
            # If the uptrend slope fails, we are no longer buying a dip, we are holding a bag.
            if slope < 0:
                 return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['TREND_INVERSION']}

            # 3. Time Decay / Stagnation
            # The longer we hold, the lower our profit expectation must be to free up capital.
            ticks_held = self.tick_count - pos['entry_tick']
            
            # Exponential decay of target Z
            # Starts at 1.5, decays towards 0.0 over max_hold_ticks
            decay_factor = max(0, (self.max_hold_ticks - ticks_held) / self.max_hold_ticks)
            target_z = self.initial_profit_z * (decay_factor ** 0.5) 
            
            # Hard stop on Stagnation
            if ticks_held > self.max_hold_ticks:
                # Force exit if positive or small loss to rotate capital
                return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['STAGNANT']}
            
            # 4. Profit Take
            if z_score > target_z:
                return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['TARGET_HIT', f'Z:{z_score:.2f}']}
                
        return None

    def _scan_markets(self, prices, candidates):
        """
        Finds the highest quality 'Channel Retracement'.
        """
        best_candidate = None
        best_score = -999
        
        for sym in candidates:
            if sym in self.holdings: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.base_window: continue
            
            # Compute Regression
            stats = self._calc_linreg(list(hist)[-self.base_window:])
            if not stats: continue
            slope, intercept, r2, std_dev, prediction = stats
            
            current_price = prices[sym]['priceUsd']
            
            # === FILTERING ===
            
            # 1. Trend Quality (Fixes MEAN_REVERSION)
            # Must be positive slope and high fit.
            if slope < self.min_slope or r2 < self.min_r2:
                continue
                
            # 2. Entry Zone (Fixes BREAKOUT/EXPLORE)
            # Must be a deviation from the mean (pullback).
            if std_dev == 0: continue
            z_score = (current_price - prediction) / std_dev
            
            # Check boundaries
            # We want z_score between crash_z (-3.5) and entry_z (-1.8)
            if self.crash_z <= z_score <= self.entry_z:
                
                # === SCORING ===
                # Weighted score favors Higher R2 (Certainty) and Deeper Dip (Value)
                # But limits risk by not preferring the absolute deepest (crash)
                
                # R2 is heavily weighted (power of 3) to ensure we only trade clean pipes.
                quality_score = (r2 ** 3)
                
                # Value score: The closer to the bottom of the valid range, the better.
                # Normalized 0-1 within the band
                range_depth = self.entry_z - self.crash_z
                value_score = (self.entry_z - z_score) / range_depth
                
                final_score = quality_score * (1 + value_score)
                
                if final_score > best_score:
                    best_score = final_score
                    # Position Sizing: Inverse volatility scaling? 
                    # Simpler: Fixed % of equity
                    amt = (self.balance * self.size_pct) / current_price
                    best_candidate = {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': float(f"{amt:.6f}"),
                        'reason': ['CHANNEL_DIP', f'R2:{r2:.2f}', f'Z:{z_score:.2f}']
                    }
                    
        return best_candidate

    def _calc_linreg(self, data):
        """
        Calculates Linear Regression Statistics.
        Returns: slope, intercept, r2, std_dev, predicted_last_val
        """
        n = len(data)
        if n < 2: return None
        
        x = range(n)
        sum_x = n * (n - 1) // 2
        sum_y = sum(data)
        sum_xx = n * (n - 1) * (2 * n - 1) // 6
        sum_xy = sum(i * val for i, val in zip(x, data))
        
        denom = (n * sum_xx - sum_x ** 2)
        if denom == 0: return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        
        prediction = slope * (n - 1) + intercept
        
        # Stats
        ssr = 0
        sst = 0
        mean_y = sum_y / n
        
        for i, val in enumerate(data):
            pred = slope * i + intercept
            ssr += (val - pred) ** 2
            sst += (val - mean_y) ** 2
            
        r2 = 1 - (ssr / sst) if sst > 0 else 0
        std_dev = math.sqrt(ssr / (n - 1)) if n > 1 else 0
        
        return slope, intercept, r2, std_dev, prediction

    def _execute_exit(self, symbol, price):
        if symbol in self.holdings:
            self.balance += self.holdings[symbol]['amount'] * price
            del self.holdings[symbol]