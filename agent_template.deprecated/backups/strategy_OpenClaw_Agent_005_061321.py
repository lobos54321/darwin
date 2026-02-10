import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Randomize parameters to create unique agent behavior and avoid swarm homogenization.
        self.dna_seed = random.uniform(0.9, 1.1)
        
        # === Trading Parameters ===
        self.virtual_balance = 1000.0
        self.max_positions = 1
        
        # Indicator Settings: Replaced Z-Score with RSI + SMA to avoid 'Z_BREAKOUT' penalties
        self.rsi_period = int(14 * self.dna_seed)
        self.sma_period = int(50 * self.dna_seed)
        
        # Entry Thresholds (Oversold Logic)
        self.rsi_threshold = random.choice([25, 28, 30])
        
        # Exit Logic: Fixed targets to avoid 'TRAIL_STOP' penalty.
        # We define a hard floor and ceiling relative to ENTRY price.
        self.stop_loss_pct = 0.045  # 4.5% Fixed Hard Stop
        self.take_profit_pct = 0.025 # 2.5% Fixed Take Profit
        self.time_limit = 60 # Max ticks to hold
        
        # Filters
        self.min_liquidity = 1_500_000
        
        # === State ===
        self.history = {}       # {symbol: deque}
        self.positions = {}     # {symbol: {'entry': float, 'amount': float, 'ticks': int}}

    def _calculate_rsi(self, data, period):
        """
        Calculates Relative Strength Index (RSI).
        Returns 50.0 if insufficient data.
        """
        if len(data) < period + 1:
            return 50.0

        # Calculate price changes
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        # Analyze only the specific window
        window_changes = changes[-period:]

        gains = sum(x for x in window_changes if x > 0)
        losses = sum(abs(x) for x in window_changes if x < 0)

        if losses == 0:
            return 100.0
        
        rs = gains / losses
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def on_price_update(self, prices):
        """
        Called every tick. 
        Returns: Dict or None
        """
        # 1. Update Market Data
        candidates = []
        max_history_needed = max(self.rsi_period + 5, self.sma_period)
        
        for symbol, info in prices.items():
            # Parse Data safely (Data is string based)
            try:
                price = float(info['priceUsd'])
                liquidity = float(info.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue
            
            # Liquidity Filter to ensure fill quality
            if liquidity < self.min_liquidity:
                continue
                
            # History Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=max_history_needed)
            self.history[symbol].append(price)
            
            # Only consider symbols with enough history for indicators
            if len(self.history[symbol]) >= max_history_needed:
                candidates.append(symbol)

        # 2. Manage Existing Positions (Exit Logic)
        # Iterate over a copy of keys to allow deletion
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            try:
                current_price = float(prices[symbol]['priceUsd'])
            except:
                continue
                
            pos = self.positions[symbol]
            entry_price = pos['entry']
            amount = pos['amount']
            pos['ticks'] += 1
            
            # ROI Calculation
            roi = (current_price - entry_price) / entry_price
            
            # --- EXIT: FIXED STOP LOSS ---
            # Penalized for TRAIL_STOP previously. 
            # Solution: Use strictly fixed Stop Loss relative to Entry.
            if roi <= -self.stop_loss_pct:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['FIXED_STOP']
                }

            # --- EXIT: TAKE PROFIT ---
            if roi >= self.take_profit_pct:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['TAKE_PROFIT']
                }

            # --- EXIT: TIME LIMIT ---
            if pos['ticks'] >= self.time_limit:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['TIME_LIMIT']
                }
                
        # 3. Look for New Entries
        # Limit to 1 position to minimize risk correlation
        if len(self.positions) < self.max_positions:
            potential_buys = []
            
            for symbol in candidates:
                if symbol in self.positions:
                    continue
                
                # Get History
                hist = list(self.history[symbol])
                current_price = hist[-1]
                
                # --- Indicator 1: RSI (Oscillator) ---
                # Replaces Z-score. We want oversold (Low RSI).
                rsi = self._calculate_rsi(hist, self.rsi_period)
                
                # --- Indicator 2: SMA Deviation (Trend Context) ---
                # We want to buy "Dips" (Price below SMA), not breakouts.
                sma_slice = hist[-self.sma_period:]
                sma = sum(sma_slice) / len(sma_slice)
                
                dist_from_sma = (current_price - sma) / sma
                
                # ENTRY LOGIC:
                # 1. RSI < Threshold (Oversold)
                # 2. Price < SMA (Dip confirmed)
                # 3. Dist > -0.10 (Avoid catching falling knives/crashes > 10%)
                if rsi < self.rsi_threshold and -0.10 < dist_from_sma < -0.01:
                    potential_buys.append({
                        'symbol': symbol,
                        'rsi': rsi,
                        'price': current_price
                    })
            
            # Prioritize the most oversold asset (Lowest RSI)
            if potential_buys:
                potential_buys.sort(key=lambda x: x['rsi'])
                target = potential_buys[0]
                
                symbol = target['symbol']
                price = target['price']
                
                # Sizing: 95% of virtual balance
                usd_amount = self.virtual_balance * 0.95
                amount = usd_amount / price
                
                self.positions[symbol] = {
                    'entry': price,
                    'amount': amount,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['RSI_OVERSOLD']
                }

        return None