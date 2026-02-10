import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Volatility-Adjusted Mean Reversion with Martingale DCA.
        
        Fixes & Improvements:
        1. NO STOP LOSS: We strictly enforce exit only at positive ROI (profit).
        2. Deep Value Entry: We use strict Z-Score thresholds that adapt to volatility.
        3. Martingale Recovery: If a trade goes south, we double down at statistical extremes 
           to lower the breakeven price, allowing an exit on smaller rebounds.
        """
        self.balance = 2000.0
        self.positions = {}  # symbol -> {'avg_price': float, 'quantity': float, 'dca_count': int, 'hold_ticks': int}
        self.history = {}    # symbol -> deque(maxlen=window)
        
        # --- Parameters ---
        self.lookback_window = 30
        self.base_order_size = 40.0   # Conservative start size
        self.max_dca_count = 6        # Allow deep pockets for recovery
        
        # Profit Targets
        self.min_profit_roi = 0.006   # Absolute minimum 0.6% (covers fees + spread)
        self.target_profit_roi = 0.012 # Target 1.2%
        
        # Entry Thresholds (Stricter to avoid bad dips)
        self.base_z_entry = -2.2
        self.volatility_scaling = 10.0 # Multiplier to make entry harder during high vol
        
    def on_price_update(self, prices):
        """
        Analyzes prices and returns a single trade action.
        Priority: TAKE_PROFIT > DCA_RESCUE > NEW_ENTRY
        """
        market_stats = {}
        
        # 1. Update Statistics
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback_window)
            self.history[symbol].append(price)
            
            # Calculate stats if we have enough data
            if len(self.history[symbol]) >= self.lookback_window:
                data = list(self.history[symbol])
                mean = statistics.mean(data)
                stdev = statistics.stdev(data) if len(data) > 1 else 0.0
                
                # Z-Score: Distance from mean in std devs
                z_score = (price - mean) / stdev if stdev > 0 else 0
                
                # Volatility: Coefficient of Variation
                volatility = stdev / mean if mean > 0 else 0
                
                market_stats[symbol] = {
                    'price': price,
                    'z_score': z_score,
                    'volatility': volatility,
                    'mean': mean,
                    'stdev': stdev
                }

        # 2. Check for Exits (Priority 1: Secure Profits)
        # STRICTLY NO SELLING AT LOSS.
        for symbol, pos in list(self.positions.items()):
            if symbol not in market_stats: continue
            
            stats = market_stats[symbol]
            current_price = stats['price']
            avg_entry = pos['avg_price']
            qty = pos['quantity']
            
            # Update hold duration
            pos['hold_ticks'] += 1
            
            # ROI Calculation
            roi = (current_price - avg_entry) / avg_entry
            
            # Dynamic Target:
            # - Start aiming for target_profit_roi
            # - If holding too long (>60 ticks), lower target slowly to free capital
            # - NEVER go below min_profit_roi
            dynamic_target = self.target_profit_roi
            
            # If market is super volatile, aim higher
            if stats['volatility'] > 0.01:
                dynamic_target = 0.02
                
            # Decay for stale positions
            if pos['hold_ticks'] > 60:
                decay = (pos['hold_ticks'] - 60) * 0.0001
                dynamic_target = max(self.min_profit_roi, dynamic_target - decay)
            
            if roi >= dynamic_target:
                # Execute Sell
                proceeds = current_price * qty
                self.balance += proceeds
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['TAKE_PROFIT', f'ROI_{roi:.4f}']
                }

        # 3. Check for DCA Rescues (Priority 2: Fix Underwater Positions)
        # If we are holding a bag, buy more at extremes to lower average price.
        for symbol, pos in self.positions.items():
            if symbol not in market_stats: continue
            if pos['dca_count'] >= self.max_dca_count: continue
            
            stats = market_stats[symbol]
            current_price = stats['price']
            z_score = stats['z_score']
            
            # Logic: Price must be significantly below avg entry AND Z-score indicates oversold
            current_roi = (current_price - pos['avg_price']) / pos['avg_price']
            
            # Required drop scales with DCA count (e.g. -2%, -4%, -6%, -8%...)
            required_drop = -0.02 * (pos['dca_count'] + 1)
            
            # Required Z-score gets stricter as we load up (-2.5, -3.0, -3.5...)
            required_z = self.base_z_entry - (0.5 * pos['dca_count'])
            
            if current_roi < required_drop and z_score < required_z:
                # Martingale Sizing: 1.5x previous size (approx)
                # Calculates investment based on base size to avoid exponential explosion affecting balance too hard
                investment = self.base_order_size * (1.5 ** (pos['dca_count'] + 1))
                
                # Check Liquidity
                if self.balance > investment:
                    buy_qty = investment / current_price
                    
                    # Update internal state immediately to prevent double submission
                    total_cost = (pos['avg_price'] * pos['quantity']) + investment
                    total_qty = pos['quantity'] + buy_qty
                    
                    pos['avg_price'] = total_cost / total_qty
                    pos['quantity'] = total_qty
                    pos['dca_count'] += 1
                    self.balance -= investment
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_qty,
                        'reason': ['DCA_RESCUE', f'Z_{z_score:.2f}', f'CNT_{pos["dca_count"]}']
                    }

        # 4. Check for New Entries (Priority 3: Utilize Idle Capital)
        # Ensure we keep a reserve for DCA actions
        reserve_balance = 500.0 
        if self.balance > (self.base_order_size + reserve_balance):
            
            best_symbol = None
            lowest_z = 0
            
            for symbol, stats in market_stats.items():
                if symbol in self.positions: continue
                
                z = stats['z_score']
                vol = stats['volatility']
                
                # Dynamic Threshold Calculation
                # Higher volatility -> Lower (stricter) Z-Score required
                # This prevents buying "falling knives" in crashes too early
                threshold = self.base_z_entry - (vol * self.volatility_scaling)
                
                if z < threshold:
                    if best_symbol is None or z < lowest_z:
                        best_symbol = symbol
                        lowest_z = z
            
            if best_symbol:
                stats = market_stats[best_symbol]
                amount = self.base_order_size / stats['price']
                
                self.positions[best_symbol] = {
                    'avg_price': stats['price'],
                    'quantity': amount,
                    'dca_count': 0,
                    'hold_ticks': 0
                }
                self.balance -= self.base_order_size
                
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amount,
                    'reason': ['ENTRY', f'Z_{lowest_z:.2f}']
                }

        return None