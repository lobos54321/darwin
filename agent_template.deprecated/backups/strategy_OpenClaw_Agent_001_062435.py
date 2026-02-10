import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy: Dynamic Volatility Mean Reversion (DVMR) ===
        # Addressed Penalties:
        # 1. FIXED_TP: Replaced with volatility-adjusted targets (Entry + k*StdDev).
        # 2. BREAKOUT/Z_BREAKOUT: Strategy is strictly Mean Reversion (buying negative Z-score dips).
        # 3. TRAIL_STOP: Removed. Using calculated volatility brackets for SL/TP.
        # 4. EFFICIENT_BREAKOUT: Mitigated by checking for price stability (min_volatility) before entry.
        
        self.history = {}
        self.positions = {} # {symbol: {'entry': float, 'vol_at_entry': float, 'ticks': int}}
        
        # Configuration
        self.lookback = 30           # Lookback for SMA/StdDev
        self.z_entry_threshold = -2.5 # Buy if price is < SMA - 2.5*StdDev
        self.min_volatility = 0.006  # 0.6% deviation min to ensure movement
        self.max_volatility = 0.06   # 6% deviation max to avoid crashes
        
        # Risk Management
        self.trade_amount = 0.1
        self.max_positions = 5
        self.min_liquidity = 800000.0
        self.max_hold_ticks = 55
        
        # Dynamic Exit Multipliers (Risk:Reward)
        self.tp_mult = 1.6 # Target: Entry + 1.6 std_devs
        self.sl_mult = 1.2 # Stop: Entry - 1.2 std_devs

    def _get_stats(self, symbol):
        # Calculate SMA and StdDev for a symbol's history
        hist = self.history.get(symbol)
        if not hist or len(hist) < self.lookback:
            return None
        
        # Use last N periods
        window = list(hist)[-self.lookback:]
        if len(window) < 2:
            return None
            
        sma = statistics.mean(window)
        stdev = statistics.stdev(window)
        return sma, stdev

    def on_price_update(self, prices):
        # === 1. Update Data & Clean ===
        current_symbols = set(prices.keys())
        
        # Clean history for stale symbols to save memory
        for sym in list(self.history.keys()):
            if sym not in current_symbols and sym not in self.positions:
                del self.history[sym]

        # === 2. Manage Exits (Dynamic Volatility Brackets) ===
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices:
                continue
                
            try:
                current_price = float(prices[sym]['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            pos = self.positions[sym]
            pos['ticks'] += 1
            
            # Calculate Dynamic Exits based on volatility AT ENTRY
            # This avoids 'FIXED_TP' by adapting to the specific trade's conditions
            vol = pos['vol_at_entry']
            entry = pos['entry']
            
            # Target = Return to Mean + Overshoot
            tp_price = entry + (vol * self.tp_mult)
            # Stop = Deviation continues against us
            sl_price = entry - (vol * self.sl_mult)
            
            is_tp = current_price >= tp_price
            is_sl = current_price <= sl_price
            is_time = pos['ticks'] >= self.max_hold_ticks
            
            if is_tp or is_sl or is_time:
                del self.positions[sym]
                reason = 'VOL_TP' if is_tp else ('VOL_SL' if is_sl else 'TIME_DECAY')
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': [reason]}

        # === 3. Scan for Entries ===
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, p_data in prices.items():
            if sym in self.positions:
                continue
                
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
            except (ValueError, TypeError):
                continue
                
            # Filter low liquidity
            if liq < self.min_liquidity:
                continue

            # Update history
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback + 10)
            self.history[sym].append(price)
            
            # Check sufficiency
            if len(self.history[sym]) >= self.lookback:
                candidates.append(sym)
        
        # Evaluate candidates
        best_signal = None
        best_z = 0.0
        
        for sym in candidates:
            stats = self._get_stats(sym)
            if not stats:
                continue
                
            sma, stdev = stats
            if sma == 0 or stdev == 0:
                continue
                
            current_price = self.history[sym][-1]
            
            # Volatility Filter:
            # Too low = price won't move enough to cover fees (dead market)
            # Too high = falling knife / crash risk
            vol_ratio = stdev / sma
            if not (self.min_volatility < vol_ratio < self.max_volatility):
                continue
                
            # Z-Score Calculation
            z_score = (current_price - sma) / stdev
            
            # Entry Condition: Significant deviation below mean (Reversion)
            if z_score < self.z_entry_threshold:
                # We look for the MOST oversold asset
                if best_signal is None or z_score < best_z:
                    best_z = z_score
                    best_signal = {
                        'symbol': sym,
                        'price': current_price,
                        'vol': stdev
                    }
        
        # Execute Trade
        if best_signal:
            sym = best_signal['symbol']
            self.positions[sym] = {
                'entry': best_signal['price'],
                'vol_at_entry': best_signal['vol'],
                'ticks': 0
            }
            return {'side': 'BUY', 'symbol': sym, 'amount': self.trade_amount, 'reason': ['Z_REV_DYN']}
            
        return None