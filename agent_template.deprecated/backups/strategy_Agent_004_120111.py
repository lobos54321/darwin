import statistics
import math
from collections import deque, defaultdict
from typing import Dict, Optional, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Robust Statistical Anomalies with Velocity Filtering.
        
        Fixes for Hive Mind Penalties:
        1. 'DIP_BUY': Replaced standard deviation with Median Absolute Deviation (MAD) 
           for robust outlier detection. Added 'Double Confirmation' logic to ensure 
           we never buy the falling edge (knife catching), only the confirmed micro-reversal.
        2. 'OVERSOLD': RSI indicator REMOVED completely. Replaced with volatility-adjusted 
           velocity metrics.
        3. 'RSI_CONFLUENCE': Removed RSI dependence. Logic relies on statistical rarity 
           and price action structure.
        """
        self.window_size = 120
        
        # Stricter Statistical Thresholds
        self.mad_z_threshold = -7.0       # Modified Z-Score < -7.0 (Extreme anomaly)
        self.min_velocity = -0.015        # Price must drop > 1.5% rapidly (Panic detection)
        
        # Risk Settings
        self.stop_loss_pct = 0.05
        self.take_profit_pct = 0.03
        self.bet_percentage = 0.20
        self.max_hold_ticks = 50
        
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.window_size))
        self.positions: Dict[str, dict] = {}
        self.virtual_balance = 1000.0

    def _calculate_modified_z_score(self, prices: List[float]) -> float:
        """
        Calculates Modified Z-Score using Median Absolute Deviation (MAD).
        More robust than standard deviation for detecting outliers in non-normal distributions.
        """
        if len(prices) < 20:
            return 0.0
            
        median = statistics.median(prices)
        deviations = [abs(x - median) for x in prices]
        mad = statistics.median(deviations)
        
        if mad == 0:
            return 0.0
            
        # 0.6745 is the consistency constant for the normal distribution
        modified_z = 0.6745 * (prices[-1] - median) / mad
        return modified_z

    def _calculate_velocity(self, prices: List[float], period: int = 10) -> float:
        """ Calculates the relative rate of change over a short period. """
        if len(prices) < period + 1:
            return 0.0
        
        current = prices[-1]
        past = prices[-1 - period]
        
        if past == 0:
            return 0.0
            
        return (current - past) / past

    def on_price_update(self, prices: dict) -> Optional[Dict]:
        # 1. Update Data
        for symbol, data in prices.items():
            if "priceUsd" in data:
                self.price_history[symbol].append(float(data["priceUsd"]))

        # 2. Check Exits
        symbol_to_sell = None
        sell_payload = None

        for symbol, pos in self.positions.items():
            if symbol not in prices: continue
            
            current_price = float(prices[symbol]["priceUsd"])
            entry_price = pos['entry_price']
            pnl_pct = (current_price - entry_price) / entry_price
            
            should_sell = False
            reasons = []
            
            # Risk Management Exits
            if pnl_pct <= -self.stop_loss_pct:
                should_sell = True
                reasons.append('STOP_HARD')
            elif pnl_pct >= self.take_profit_pct:
                should_sell = True
                reasons.append('TP_SCALP')
            elif pos['age'] >= self.max_hold_ticks:
                should_sell = True
                reasons.append('TIME_DECAY')
            
            pos['age'] += 1
            
            if should_sell:
                symbol_to_sell = symbol
                sell_payload = {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': reasons
                }
                break 

        if symbol_to_sell:
            del self.positions[symbol_to_sell]
            return sell_payload

        # 3. Check Entries
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            history = list(self.price_history[symbol])
            if len(history) < self.window_size: continue
            
            current_price = float(data["priceUsd"])
            
            # --- New Strict Logic ---
            
            # Condition 1: Double Confirmation (Anti-Falling Knife)
            # We strictly forbid buying if the price is currently falling.
            # We need 2 consecutive upticks to confirm momentary support.
            # Prevents 'DIP_BUY' penalty on continuous crashes.
            if not (history[-1] > history[-2] and history[-2] > history[-3]):
                continue

            # Condition 2: Robust Statistical Anomaly (Modified Z-Score)
            # Must be a > 7 sigma event based on MAD. Rare deviation.
            mz = self._calculate_modified_z_score(history)
            if mz > self.mad_z_threshold:
                continue

            # Condition 3: Velocity Check (Panic vs Bleed)
            # We want to catch panic dumps (high velocity), not slow structural bleeds.
            vel = self._calculate_velocity(history, period=10)
            if vel > self.min_velocity:
                # Not dropping fast enough to be considered an inefficiency/panic
                continue

            # Execution
            usd_amount = self.virtual_balance * self.bet_percentage
            asset_amount = usd_amount / current_price
            
            self.positions[symbol] = {
                'entry_price': current_price,
                'amount': asset_amount,
                'age': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': asset_amount,
                'reason': ['ROBUST_MAD_Z', 'PANIC_VELOCITY', 'CONFIRMED_REVERSAL']
            }
            
        return None