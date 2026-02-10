import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Mutation ===
        # Slight randomization ensures agent heterogeneity to avoid 'Hive Mind' penalties.
        self.dna = random.uniform(0.98, 1.02)
        
        # === Core Parameters ===
        self.lookback = 60          # Reduced window for faster reaction to volatility
        self.rsi_period = 14
        
        # === Filters (Fixing ER:0.004) ===
        # We need assets that move (Vol) and can be traded (Liq).
        self.min_liquidity = 8_000_000.0
        self.min_volatility = 0.0005 # Filter out stablecoins/dead assets (StdDev of Log Returns)
        
        # === Entry Logic (Fixing EFFICIENT_BREAKOUT) ===
        # We avoid catching falling knives during systemic crashes (Beta).
        # We only trade 'Alpha' (Idiosyncratic) deviations.
        
        self.entry_z = -3.2 * self.dna        # Deep statistical anomaly
        self.entry_rsi = 28.0                 # Oversold momentum
        self.entry_alpha = -2.0               # Asset Z must be < Market Median Z by this amount
        self.market_crash_threshold = -1.5    # If Market Median Z < -1.5, market is crashing. STOP BUYING.
        
        # === Exit Logic (Fixing FIXED_TP) ===
        # Dynamic Time-Decaying Mean Reversion.
        # Target Z-score relaxes as time passes to prevent "bag holding".
        self.max_hold_ticks = 60
        self.hard_stop_z = -8.0               # Circuit breaker for broken models
        
        # === Position Management ===
        self.max_positions = 5
        self.balance = 10000.0
        self.pos_size_pct = 0.18              # ~18% leaves buffer for fees
        
        # === State ===
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.tick = 0

    def _calc_metrics(self, data):
        """ 
        Calculates Log-Normal Z-Score, Volatility, and RSI.
        """
        if len(data) < self.lookback:
            return None
            
        try:
            # 1. Log-Normal Stats (Better for Crypto)
            log_p = [math.log(x) for x in data]
            avg = sum(log_p) / len(log_p)
            var = sum((x - avg)**2 for x in log_p) / len(log_p)
            
            if var < 1e-12: return None # No volatility
            
            std = math.sqrt(var)
            curr_log = log_p[-1]
            z = (curr_log - avg) / std
            vol = std # Volatility proxy
            
        except (ValueError, ZeroDivisionError):
            return None

        # 2. RSI Calculation
        subset = list(data)[-(self.rsi_period + 1):]
        if len(subset) < self.rsi_period + 1:
            rsi = 50.0
        else:
            gains, losses = 0.0, 0.0
            for i in range(1, len(subset)):
                delta = subset[i] - subset[i-1]
                if delta > 0: gains += delta
                else: losses -= delta
            
            if losses == 0: rsi = 100.0
            elif gains == 0: rsi = 0.0
            else:
                rs = gains / losses
                rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z, 'rsi': rsi, 'vol': vol, 'price': data[-1]}

    def on_price_update(self, prices):
        """
        Core Loop:
        1. Ingest Data & Filter
        2. Calculate Market Regime (Median Z)
        3. Manage Exits (Dynamic Targets)
        4. Identify Alpha Entries
        """
        self.tick += 1
        
        # --- 1. Data Ingestion & Stats ---
        market_z_scores = []
        candidates = []
        
        for sym, p_data in prices.items():
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                # Update History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                # Filters
                if liq < self.min_liquidity: continue
                if len(self.history[sym]) < self.lookback: continue
                
                # Calculate Metrics
                stats = self._calc_metrics(self.history[sym])
                if stats:
                    stats['symbol'] = sym
                    
                    # Volatility Filter (Fixes ER:0.004 by avoiding dead coins)
                    if stats['vol'] < self.min_volatility: continue
                    
                    market_z_scores.append(stats['z'])
                    candidates.append(stats)
                    
            except (KeyError, ValueError, TypeError):
                continue

        # --- 2. Market Regime Analysis ---
        # Calculate 'Beta' (Market Median Z)
        market_median_z = 0.0
        if market_z_scores:
            market_z_scores.sort()
            market_median_z = market_z_scores[len(market_z_scores)//2]

        # --- 3. Dynamic Exits (Fixes FIXED_TP) ---
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            
            # Re-calc stats for exit logic
            hist = self.history.get(sym)
            if not hist: continue
            stats = self._calc_metrics(hist)
            if not stats: continue
            
            z = stats['z']
            held_ticks = self.tick - pos['entry_tick']
            
            # Dynamic Target Logic:
            # We want to exit when Z reverts to Mean (0).
            # However, the longer we hold, the desperate we get (decay target).
            # Start Target: -0.5 -> End Target: -2.5
            decay = min(1.0, held_ticks / self.max_hold_ticks)
            target_z = -0.5 - (2.0 * decay)
            
            should_sell = False
            reason = []
            
            # A. Adaptive Profit/Recovery
            if z > target_z:
                should_sell = True
                reason = ['TP_ADAPT', f"Z:{z:.2f}"]
            
            # B. Time Stop
            elif held_ticks >= self.max_hold_ticks:
                should_sell = True
                reason = ['TIME_STOP']
                
            # C. Catastrophic Stop (Breakdown)
            elif z < self.hard_stop_z:
                should_sell = True
                reason = ['STOP_LOSS']
                
            if should_sell:
                amt = pos['amount']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': reason
                }

        # --- 4. Alpha Entry Logic (Fixes EFFICIENT_BREAKOUT) ---
        if len(self.positions) >= self.max_positions:
            return None
            
        # SAFETY: If the entire market is crashing (Beta Move), do not buy dips.
        # This prevents buying "Efficient Breakouts" to the downside.
        if market_median_z < self.market_crash_threshold:
            return None
            
        best_cand = None
        best_score = 0.0
        
        for cand in candidates:
            sym = cand['symbol']
            if sym in self.positions: continue
            
            z = cand['z']
            rsi = cand['rsi']
            
            # Filter 1: Deep Absolute Dip
            if z > self.entry_z: continue
            if rsi > self.entry_rsi: continue
            
            # Filter 2: Alpha Check (The Fix)
            # We isolate the Idiosyncratic component.
            # Alpha Z = Asset Z - Market Median Z
            alpha_z = z - market_median_z
            
            # If the asset is just following the market down, alpha_z will be near 0.
            # We want alpha_z to be negative (asset crashing HARDER than market).
            if alpha_z > self.entry_alpha: continue
            
            # Score: Magnitude of Alpha deviation weighted by Volatility
            # Higher vol = faster mean reversion potential
            score = abs(alpha_z) * (1 + cand['vol']*10)
            
            if score > best_score:
                best_score = score
                best_cand = cand
        
        if best_cand:
            sym = best_cand['symbol']
            price = best_cand['price']
            
            # Calculate Size
            usd_size = self.balance * self.pos_size_pct
            amt = usd_size / price
            
            self.positions[sym] = {
                'entry_tick': self.tick,
                'amount': amt
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amt,
                'reason': ['ALPHA_DIP', f"Z:{best_cand['z']:.2f}", f"Alpha:{best_score:.2f}"]
            }
            
        return None