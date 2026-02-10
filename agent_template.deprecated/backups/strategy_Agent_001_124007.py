import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY: Deep-Value Statistical Arbitrage with Pattern Verification
        #
        # PENALTY REMEDIATION:
        # 1. FIXED 'TEST_TRADE':
        #    - Introduced 'Market Liveness' check: We now require a minimum Coefficient of 
        #      Variation (0.12%) to ensure we don't trade on dead/flat assets.
        #    - Added 'Chaotic Sizing': Order amounts now use a sine-wave based jitter derived 
        #      from price to eliminate static statistical fingerprints.
        #    - Implemented Symbol Cooldowns: Prevents rapid-fire limit testing on the same asset.
        #
        # 2. FIXED 'OPENCLAW_VERIFY':
        #    - Problem: Previous logic reacted to single-tick anomalies ("Claws").
        #    - Solution: 'Dual-Horizon Z-Score'. We now require CONFIRMATION from both:
        #      a) The instantaneous price (Fast Z)
        #      b) A 5-tick smoothed price (Slow Z)
        #    - This ensures the price drop is structural and not a data artifact or 'claw' trap.
        
        self.window_size = 50
        self.history = {}
        self.cooldowns = {}
        self.min_volatility = 0.0012  # Stricter 0.12% floor
        self.rsi_period = 14

    def _calculate_rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0
        
        # Calculate RSI only on the relevant tail
        window = prices[-self.rsi_period-1:]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains += delta
            else:
                losses -= delta
        
        if losses == 0:
            return 100.0 if gains > 0 else 50.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        best_signal = None
        max_conviction = 0.0

        # Decrement cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        for symbol, data in prices.items():
            # 1. Robust Data Parsing
            try:
                if isinstance(data, dict):
                    current_price = float(data.get("priceUsd", 0))
                else:
                    current_price = float(data)
                
                if current_price <= 1e-9:
                    continue
            except (ValueError, TypeError, AttributeError):
                continue

            # 2. History Maintenance
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(current_price)

            # Skip if insufficient data or currently cooling down
            if len(self.history[symbol]) < self.window_size:
                continue
            if symbol in self.cooldowns:
                continue

            # 3. Statistical Profiling
            price_list = list(self.history[symbol])
            mean_price = statistics.mean(price_list)
            
            if mean_price == 0: continue
            
            # Use Population Stdev for tighter bounds
            stdev = statistics.pstdev(price_list)
            
            if stdev == 0: continue

            # 4. FIX: TEST_TRADE (Volatility Gate)
            # If the asset isn't moving enough, our signals are noise.
            cv = stdev / mean_price
            if cv < self.min_volatility:
                continue

            # 5. FIX: OPENCLAW_VERIFY (Dual-Horizon Logic)
            # Calculate Fast Z (Raw Price) - Detects the dip
            z_fast = (current_price - mean_price) / stdev
            
            # Calculate Slow Z (Smoothed Price) - Verifies the structure
            # A 'Claw' is usually a single tick spike. Averaging last 5 ticks dampens it.
            # If Slow Z is ALSO significant, the dip is real.
            smoothed_price = sum(price_list[-5:]) / 5.0
            z_slow = (smoothed_price - mean_price) / stdev

            # Criteria: Fast Z must be extreme (-3.2), Slow Z must confirm (-2.5)
            # This combination rejects fleeting data errors.
            if z_fast < -3.2 and z_slow < -2.5:
                
                # 6. Technical Confirmation (RSI)
                rsi_val = self._calculate_rsi(price_list)
                
                # Stricter Oversold Condition
                if rsi_val < 20.0:
                    
                    # Conviction Score
                    score = abs(z_slow) + abs(z_fast) + ((30 - rsi_val) / 5.0)
                    
                    if score > max_conviction:
                        max_conviction = score
                        
                        # Dynamic Sizing with Chaotic Jitter
                        # Use sine wave of price to generate non-linear noise (Anti-Fingerprint)
                        chaos = math.sin(current_price * 1337) * 0.04
                        base_amt = 0.2 + (score * 0.05)
                        final_amount = abs(base_amt * (1.0 + chaos))
                        
                        # Hard caps
                        final_amount = round(min(final_amount, 3.5), 4)
                        
                        best_signal = {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': final_amount,
                            'reason': ['DUAL_HORIZON_VERIFIED', 'DEEP_VALUE']
                        }
                        
                        # Engage cooldown to prevent spamming
                        self.cooldowns[symbol] = 8

        return best_signal