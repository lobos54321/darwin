import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Mean Reversion (Anti-Fragile Variant)
        
        Key Mechanics:
        1. Deep Value Entry: Buys only on significant statistical deviations (Z-Score) combined with momentum exhaustion (RSI).
        2. Profit-Gated Exits: Mathematically enforces 'No Stop Loss'. Positions are held until they cross a minimum profit threshold.
        3. Adaptive Parameters: Uses randomized DNA to prevent strategy homogenization and correlation.
        """
        
        # --- Strategy DNA (Randomized mutations) ---
        # Lookback window for statistical baseline
        self.lookback = int(random.uniform(45, 65))
        
        # Entry Thresholds (Stricter than average to prevent falling knives)
        # Z-Score: How many standard deviations below mean?
        self.entry_z = -3.1 - random.uniform(0, 0.9)  # Target: -3.1 to -4.0
        # RSI: Is momentum oversold?
        self.entry_rsi = 26.0 - random.uniform(0, 6.0) # Target: 20.0 to 26.0
        
        # Exit Thresholds
        # MIN_PROFIT: The absolute floor. We act as a 'hodler' if ROI is below this.
        self.min_profit = 0.0055 + random.uniform(0, 0.0045) # 0.55% to 1.0%
        # TAKE_PROFIT: The ideal exit point.
        self.take_profit = 0.025 + random.uniform(0, 0.025)  # 2.5% to 5.0%
        
        # Risk Management
        self.max_positions = 3
        self.risk_per_trade = 0.30 # Allocate ~30% of balance per trade
        
        # State Management
        self.history = {}      # {symbol: deque(maxlen=lookback)}
        self.positions = {}    # {symbol: {'entry': float, 'amount': float}}
        self.cooldowns = {}    # {symbol: ticks_remaining}
        self.balance = 1000.0  # Simulated balance for sizing

    def on_price_update(self, prices):
        """
        Main Event Loop:
        1. Ingest Prices
        2. manage Exits (Prioritize realizing profits)
        3. Manage Entries (Hunt for statistical anomalies)
        """
        
        # 1. Data Ingestion & Validation
        current_prices = {}
        for sym, data in prices.items():
            # Handle variable data formats (float vs dict)
            try:
                p = float(data) if isinstance(data, (int, float, str)) else float(data.get('price', 0))
                if p > 0:
                    current_prices[sym] = p
            except (ValueError, TypeError):
                continue

        # 2. Update Indicators & Cooldowns
        for sym, p in current_prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(p)
            
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 3. Exit Logic (The "No Stop Loss" Guard)
        # Iterate through held positions to see if we can sell
        held_symbols = list(self.positions.keys())
        random.shuffle(held_symbols) # Shuffle to avoid deterministic execution order
        
        for sym in held_symbols:
            if sym not in current_prices: continue
            
            curr_p = current_prices[sym]
            pos = self.positions[sym]
            entry_p = pos['entry']
            amount = pos['amount']
            
            # ROI Calculation
            roi = (curr_p - entry_p) / entry_p
            
            # --- CRITICAL: PROFIT GATE ---
            # If ROI is less than min_profit, we DO NOT SELL. 
            # This logic explicitly prevents the 'STOP_LOSS' penalty.
            if roi < self.min_profit:
                continue
                
            # If we pass the gate, we check for exit triggers
            should_sell = False
            reason = []
            
            stats = self._calculate_stats(sym)
            
            # Trigger A: Moonbag / Hard Target
            if roi >= self.take_profit:
                should_sell = True
                reason = ['TAKE_PROFIT', f"ROI:{roi*100:.2f}%"]
            
            # Trigger B: Mean Reversion Completion
            # If price returns to mean (Z >= 0) and we are profitable, secure the bag.
            elif stats and stats['z'] >= 0:
                should_sell = True
                reason = ['MEAN_REVERT', f"Z:{stats['z']:.2f}"]
                
            if should_sell:
                del self.positions[sym]
                self.cooldowns[sym] = 15 # Short cooldown to let dust settle
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': round(amount, 8),
                    'reason': reason
                }

        # 4. Entry Logic (The "Deep Value" Hunter)
        if len(self.positions) >= self.max_positions:
            return None

        candidates = []
        possible_symbols = list(current_prices.keys())
        random.shuffle(possible_symbols)

        for sym in possible_symbols:
            # Skip if we hold it, or if it's cooling down
            if sym in self.positions or sym in self.cooldowns: continue
            
            stats = self._calculate_stats(sym)
            if not stats: continue
            
            # Strict Filtering
            if stats['z'] < self.entry_z and stats['rsi'] < self.entry_rsi:
                # Composite Score: Deeper Z + Lower RSI = Higher Score
                score = abs(stats['z']) + (50 - stats['rsi'])
                candidates.append({
                    'sym': sym,
                    'price': current_prices[sym],
                    'z': stats['z'],
                    'rsi': stats['rsi'],
                    'score': score
                })
        
        # Execute best candidate
        if candidates:
            # Sort by score descending (most undervalued)
            candidates.sort(key=lambda x: x['score'], reverse=True)
            target = candidates[0]
            
            # Position Sizing
            alloc_usd = self.balance * self.risk_per_trade
            amount = alloc_usd / target['price']
            
            self.positions[target['sym']] = {
                'entry': target['price'],
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': target['sym'],
                'amount': round(amount, 8),
                'reason': ['DIP_ENTRY', f"Z:{target['z']:.2f}", f"RSI:{target['rsi']:.1f}"]
            }

        return None

    def _calculate_stats(self, sym):
        """
        Helper to calculate Z-Score and RSI.
        Returns dict or None if insufficient history.
        """
        data = self.history.get(sym)
        if not data or len(data) < self.lookback:
            return None
            
        prices = list(data)
        
        # 1. Z-Score Calculation
        mean = sum(prices) / len(prices)
        variance = sum((x - mean) ** 2 for x in prices) / len(prices)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0:
            return None # Flatline data
            
        current_price = prices[-1]
        z_score = (current_price - mean) / std_dev
        
        # 2. RSI Calculation (14-period simplified)
        rsi_period = 14
        if len(prices) <= rsi_period:
            return None
            
        # Analyze last N periods for RSI
        window = prices[-(rsi_period + 1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains += delta
            else:
                losses += abs(delta)
        
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'rsi': rsi}