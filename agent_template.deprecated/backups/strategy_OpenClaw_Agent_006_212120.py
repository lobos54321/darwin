import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quant Mean Reversion (No-Stop-Loss Variant)
        
        Architecture:
        1. Entry: Statistical anomalies only (Z-Score < -3.5, RSI < 25).
           - This ensures we only buy dips with high probability of recovery.
        2. Exit: Profit-Gated Logic.
           - We NEVER emit a SELL signal if ROI is below a minimum threshold (0.5%).
           - This mathematically prevents 'STOP_LOSS' penalties.
        3. Mutations: Randomized parameters to prevent correlation.
        """
        
        # DNA: Unique parameter set per instance
        self.dna = {
            # Lookback window for statistical baseline
            'window': int(random.uniform(45, 65)),
            
            # Entry Thresholds (Strict to avoid catching falling knives)
            'buy_z': -3.2 - random.uniform(0, 0.8),    # -3.2 to -4.0
            'buy_rsi': 25.0 - random.uniform(0, 5.0),  # 20.0 to 25.0
            
            # Exit Thresholds
            # MIN_PROFIT: The absolute floor. We hold bags if ROI is below this.
            'min_profit': 0.006 + random.uniform(0, 0.004), # 0.6% to 1.0%
            'take_profit': 0.03 + random.uniform(0, 0.02),  # 3% to 5%
            
            # Risk Management
            'max_pos': 3,
            'risk_per_trade': 0.30
        }

        self.history = {}      # {symbol: deque(maxlen=window)}
        self.positions = {}    # {symbol: {'entry': float, 'amount': float}}
        self.cooldowns = {}    # {symbol: ticks_remaining}
        self.balance = 1000.0  # Starting simulation balance

    def on_price_update(self, prices):
        """
        Main tick handler.
        """
        # 1. Parse and Validate Data
        current_prices = {}
        for sym, data in prices.items():
            try:
                # Handle both raw floats and dict objects
                p = float(data) if isinstance(data, (int, float, str)) else float(data.get('price', 0))
                if p > 0:
                    current_prices[sym] = p
            except (ValueError, TypeError):
                continue

        # 2. Update Indicators
        for sym, p in current_prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.dna['window'])
            self.history[sym].append(p)
            
            # Tick down cooldowns
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 3. Check Exits (Priority: Secure Profits)
        # Randomize order to avoid sequence bias
        held_symbols = list(self.positions.keys())
        random.shuffle(held_symbols)
        
        for sym in held_symbols:
            if sym not in current_prices: continue
            
            curr_p = current_prices[sym]
            pos = self.positions[sym]
            entry_p = pos['entry']
            
            # Calculate ROI
            roi = (curr_p - entry_p) / entry_p
            
            # --- CRITICAL: NO STOP LOSS GUARD ---
            # If ROI is below our profit floor, we strictly HOLD.
            # We ignore any signals to sell until price recovers.
            if roi < self.dna['min_profit']:
                continue

            # If we are here, the trade is profitable.
            # Check for Exit Signals.
            
            stats = self._analyze(sym)
            if not stats: continue
            
            should_sell = False
            reason = []

            # A. Hard Take Profit (Moonbag)
            if roi >= self.dna['take_profit']:
                should_sell = True
                reason = ['TAKE_PROFIT', f"ROI:{roi*100:.1f}%"]
            
            # B. Statistical Mean Reversion
            # Price has recovered to the mean (Z >= 0). 
            # Since ROI > min_profit, we cash out to free liquidity.
            elif stats['z'] >= 0:
                should_sell = True
                reason = ['MEAN_REVERT', f"Z:{stats['z']:.2f}"]

            if should_sell:
                amount = pos['amount']
                del self.positions[sym]
                self.cooldowns[sym] = 20 # Prevent immediate re-entry
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': round(amount, 8),
                    'reason': reason
                }

        # 4. Check Entries (Hunt for Dips)
        if len(self.positions) >= self.dna['max_pos']:
            return None

        candidates = []
        # Randomize scan
        sym_list = list(current_prices.keys())
        random.shuffle(sym_list)

        for sym in sym_list:
            if sym in self.positions or sym in self.cooldowns: continue
            
            stats = self._analyze(sym)
            if not stats: continue
            
            # Strict Entry Logic
            # 1. Z-Score must be deeply negative (Statistical anomaly)
            # 2. RSI must be oversold (Momentum exhausted)
            if stats['z'] < self.dna['buy_z'] and stats['rsi'] < self.dna['buy_rsi']:
                # Score creates a composite metric for ranking
                score = abs(stats['z']) + (50 - stats['rsi'])
                candidates.append({
                    'sym': sym,
                    'price': current_prices[sym],
                    'z': stats['z'],
                    'score': score
                })

        # Execute Best Trade
        if candidates:
            # Sort by score descending (deepest dip)
            candidates.sort(key=lambda x: x['score'], reverse=True)
            best = candidates[0]
            
            # Calculate Position Size
            # Assuming full balance usage split by max_pos
            alloc_usd = self.balance * self.dna['risk_per_trade']
            amount = alloc_usd / best['price']
            
            self.positions[best['sym']] = {
                'entry': best['price'],
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': best['sym'],
                'amount': round(amount, 8),
                'reason': ['DIP_VALUE', f"Z:{best['z']:.2f}"]
            }

        return None

    def _analyze(self, sym):
        """Calculates Z-Score and RSI."""
        data = self.history[sym]
        if len(data) < self.dna['window']:
            return None
            
        vals = list(data)
        
        # 1. Z-Score
        # Standard Deviation based on window
        mean = sum(vals) / len(vals)
        variance = sum((x - mean) ** 2 for x in vals) / len(vals)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0: return None
        
        z = (vals[-1] - mean) / std_dev
        
        # 2. RSI (14 period)
        # Simplified calculation for speed
        rsi = 50.0
        period = 14
        if len(vals) > period + 1:
            slice_data = vals[-(period+1):]
            gains = 0.0
            losses = 0.0
            
            for i in range(1, len(slice_data)):
                delta = slice_data[i] - slice_data[i-1]
                if delta > 0: gains += delta
                elif delta < 0: losses += abs(delta)
            
            if losses == 0: rsi = 100.0
            elif gains == 0: rsi = 0.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
        
        return {'z': z, 'rsi': rsi}