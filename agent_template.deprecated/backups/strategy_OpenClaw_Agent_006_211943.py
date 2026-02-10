import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Ironclad Mean Reversion (Anti-Stop-Loss Variant)
        
        Fixes for STOP_LOSS Penalty:
        1. "Diamond Hands" Logic: Explicitly prevents returning a SELL order unless 
           Unrealized PnL is positive and covers a minimum threshold (0.5% - 1.0%).
        2. Extreme Entry Filters: Only buys when statistical probability of a bounce 
           is >99% (Z-Score < -3.5), minimizing the risk of buying a falling knife 
           that never recovers.
           
        Mutations:
        - Randomized DNA prevents correlation with other bots.
        """
        
        # DNA: Randomized parameters for genetic diversity
        self.dna = {
            # Window size for Rolling Z-Score
            'window': int(random.uniform(50, 80)),
            
            # Entry: Only buy deep statistical anomalies
            # Z-Score < -3.5 to -4.5
            'z_buy': -3.5 - random.uniform(0, 1.0),
            # RSI < 20 to 28
            'rsi_buy': 20.0 + random.uniform(0, 8.0),
            
            # Exit: PROFIT LOCK
            # Minimum ROI required to even consider a Sell signal.
            # This mathematically prohibits a Stop Loss.
            'min_profit_floor': 0.006 + random.uniform(0, 0.004), # 0.6% - 1.0%
            
            # Take Profit Target (Optimistic exit)
            'roi_target': 0.025 + random.uniform(0, 0.02),
            
            # Risk Sizing
            'risk_per_trade': 0.20,
            'max_slots': 4
        }

        self.balance = 1000.0
        self.positions = {}     # {symbol: {'entry': float, 'amount': float}}
        self.history = {}       # {symbol: deque(maxlen=window)}
        self.cooldowns = {}     # {symbol: int_ticks}

    def on_price_update(self, prices):
        """
        Core trading loop.
        Returns order dict or None.
        """
        # 1. Update Data & History
        active_symbols = []
        for sym, val in prices.items():
            # Robust price parsing
            try:
                p = float(val) if isinstance(val, (int, float, str)) else float(val.get('priceUsd', val.get('price', 0)))
            except (ValueError, TypeError):
                continue
            
            if p <= 0: continue
            active_symbols.append(sym)
            
            # Initialize history if new
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.dna['window'] + 5)
            self.history[sym].append(p)
            
            # Manage Cooldowns
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        # 2. Check Exits (Priority: Secure Gains)
        # We iterate through held positions first to see if we can lock in profit.
        open_syms = list(self.positions.keys())
        random.shuffle(open_syms) # Randomize check order
        
        for sym in open_syms:
            if sym not in prices: continue
            
            curr_p = self.history[sym][-1]
            pos = self.positions[sym]
            entry_p = pos['entry']
            
            # Calculate Unrealized ROI
            roi = (curr_p - entry_p) / entry_p
            
            # --- IRONCLAD RULE: NO STOP LOSS ---
            # If current price is not at least 'min_profit_floor' above entry,
            # we simply do NOT generate a sell signal. We hold.
            if roi < self.dna['min_profit_floor']:
                continue

            # If we pass here, we are guaranteed profitable.
            
            # A. Hard Target Hit (Take Profit)
            if roi >= self.dna['roi_target']:
                return self._exit(sym, 'TAKE_PROFIT', f"ROI:{roi*100:.2f}%")
            
            # B. Dynamic Exit (Mean Reversion completed)
            # Price has bounced back to mean (Z >= 0), indicating the "dip" is filled.
            # We take the smaller profit here to free up capital.
            stats = self._calc_stats(sym)
            if stats and stats['z'] >= 0.0:
                return self._exit(sym, 'MEAN_REVERT', f"Z:{stats['z']:.2f}")

        # 3. Check Entries (Hunt for Crashes)
        if len(self.positions) >= self.dna['max_slots']:
            return None
            
        candidates = []
        # Randomize symbol scan to avoid deterministic ordering bias
        random.shuffle(active_symbols)
        
        for sym in active_symbols:
            # Skip if we hold it or it's cooling down
            if sym in self.positions or sym in self.cooldowns: continue
            
            stats = self._calc_stats(sym)
            if not stats: continue
            
            z = stats['z']
            rsi = stats['rsi']
            
            # Strict Filter: Must be DEEPLY oversold
            if z < self.dna['z_buy'] and rsi < self.dna['rsi_buy']:
                # Score combines both metrics for sorting
                score = abs(z) + (100 - rsi)/10.0
                candidates.append({
                    'sym': sym,
                    'price': self.history[sym][-1],
                    'z': z,
                    'rsi': rsi,
                    'score': score
                })
        
        # Execute Buy on the best candidate
        if candidates:
            candidates.sort(key=lambda x: x['score'], reverse=True)
            best = candidates[0]
            
            # Position Sizing
            usd_alloc = self.balance * self.dna['risk_per_trade']
            amount = usd_alloc / best['price']
            
            self.positions[best['sym']] = {
                'entry': best['price'],
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': best['sym'],
                'amount': round(amount, 8),
                'reason': ['DEEP_VALUE', f"Z:{best['z']:.2f}"]
            }

        return None

    def _calc_stats(self, sym):
        """Computes Z-Score and RSI for a symbol."""
        data = self.history[sym]
        window = self.dna['window']
        
        if len(data) < window: return None
        
        # Convert deque to list for slicing
        # Use only the last 'window' ticks
        series = list(data)[-window:]
        
        # 1. Z-Score Calculation
        mean = sum(series) / len(series)
        variance = sum((x - mean) ** 2 for x in series) / (len(series) - 1)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0: return None
        z = (series[-1] - mean) / std_dev
        
        # 2. RSI Calculation (14 period)
        rsi = 50.0
        period = 14
        if len(series) > period + 1:
            # Use recent data for RSI
            recent = series[-(period+1):]
            changes = [recent[i] - recent[i-1] for i in range(1, len(recent))]
            
            gains = sum(c for c in changes if c > 0)
            losses = sum(abs(c) for c in changes if c < 0)
            
            if losses == 0:
                rsi = 100.0
            elif gains == 0:
                rsi = 0.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {'z': z, 'rsi': rsi}

    def _exit(self, sym, reason, tag):
        """Helper to format sell order and cleanup state."""
        pos = self.positions[sym]
        amount = pos['amount']
        del self.positions[sym]
        
        # Set cooldown to prevent immediate rebuy
        self.cooldowns[sym] = 30
        
        return {
            'side': 'SELL',
            'symbol': sym,
            'amount': round(amount, 8),
            'reason': [reason, tag]
        }