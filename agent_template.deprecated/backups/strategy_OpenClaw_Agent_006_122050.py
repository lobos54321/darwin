import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Mutation ===
        # Slight randomization to prevent correlation with other agents using similar logic.
        self.dna = random.uniform(0.95, 1.05)
        
        # === Core Parameters ===
        # Extended lookback to ensure statistical significance of Z-scores.
        self.lookback = 100 
        self.rsi_period = 14
        
        # === Filters (Fix ER:0.004) ===
        # Raised liquidity floor to 10M to ensure we trade only liquid assets.
        # This reduces slippage and filters out low-cap noise that triggers false positives.
        self.min_liquidity = 10_000_000.0
        
        # === Entry Logic (Fix EFFICIENT_BREAKOUT & DIP_BUY) ===
        # Stricter thresholds: We want rare, idiosyncratic crashes (Alpha), not systemic moves (Beta).
        # Trigger Z: Very deep statistical deviation.
        self.thresh_z = -3.85 * self.dna
        # Trigger RSI: Deep oversold condition to confirm panic.
        self.thresh_rsi = 22.0
        # Alpha Check: Asset Z must be significantly lower than Market Median Z.
        # This ensures we aren't buying a general market crash.
        self.thresh_alpha = -2.2 
        
        # === Exit Logic (Fix FIXED_TP) ===
        # Adaptive Mean Reversion: Target shifts based on time held and market sentiment.
        self.max_hold_ticks = 80
        self.hard_stop_z = -9.0 # Catastrophic failure guard
        
        # === Position Management ===
        self.max_positions = 5
        self.balance = 10000.0
        self.pos_size_pct = 0.19 # Allocate ~19% per trade (leaving dust buffer)
        
        # === State ===
        self.history = {} # symbol -> deque of prices
        self.positions = {} # symbol -> dict
        self.tick = 0

    def _calc_stats(self, data):
        """ Calculate Log-Normal Z-Score and RSI. """
        if len(data) < self.lookback:
            return None
            
        # 1. Log Returns & Z-Score
        # Using log-prices models crypto asset distribution better than raw prices.
        try:
            log_p = [math.log(x) for x in data]
            avg = sum(log_p) / len(log_p)
            var = sum((x - avg)**2 for x in log_p) / len(log_p)
            
            if var < 1e-12: return None # Filter stablecoins/dead assets
            
            std = math.sqrt(var)
            curr_log = log_p[-1]
            z = (curr_log - avg) / std
        except (ValueError, ZeroDivisionError):
            return None

        # 2. RSI (Wilder's Smoothing on tail)
        subset = list(data)[-(self.rsi_period + 1):]
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
            
        return {'z': z, 'rsi': rsi, 'price': data[-1]}

    def on_price_update(self, prices):
        """
        Main Loop:
        1. Ingest Data & Calc Market Regime.
        2. Manage Exits (Adaptive).
        3. Scan for Alpha Dips.
        """
        self.tick += 1
        
        # --- 1. Data Ingestion & Market Regime ---
        market_z_scores = []
        candidates = []
        
        for sym, p_data in prices.items():
            try:
                # Safe parsing
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                # History Update
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                # Pre-filters
                if liq < self.min_liquidity: continue
                if len(self.history[sym]) < self.lookback: continue
                
                stats = self._calc_stats(self.history[sym])
                if stats:
                    stats['symbol'] = sym
                    market_z_scores.append(stats['z'])
                    candidates.append(stats)
                    
            except (KeyError, ValueError, TypeError):
                continue

        # Market Median Z: The "Tide" of the market.
        market_median_z = 0.0
        if market_z_scores:
            market_z_scores.sort()
            market_median_z = market_z_scores[len(market_z_scores)//2]

        # --- 2. Check Exits (Priority) ---
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            curr_data = prices.get(sym)
            if not curr_data: continue
            
            hist = self.history.get(sym)
            if not hist: continue
            
            stats = self._calc_stats(hist)
            if not stats: continue
            
            z = stats['z']
            held_ticks = self.tick - pos['entry_tick']
            
            # Adaptive Exit Logic:
            # We want to exit at Mean (Z=0).
            # But if held too long, or market is bearish, we lower expectations.
            
            # Progress: 0.0 -> 1.0
            progress = min(1.0, held_ticks / self.max_hold_ticks)
            
            # Target: Starts near 0 (Market Median adjusted), drops to -2.0 over time.
            # This turns the strategy from "Sniper" (early) to "Inventory Manager" (late).
            target_z = (market_median_z * 0.3) - (2.0 * progress)
            
            should_sell = False
            reason = []
            
            if z > target_z:
                should_sell = True
                reason = ['TP_ADAPT', f"Z{z:.2f}>T{target_z:.2f}"]
            elif held_ticks >= self.max_hold_ticks:
                should_sell = True
                reason = ['TIMEOUT']
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

        # --- 3. Check Entries ---
        if len(self.positions) >= self.max_positions:
            return None
            
        best_cand = None
        best_alpha_score = 0.0 # Tracks deviation from market
        
        for cand in candidates:
            sym = cand['symbol']
            if sym in self.positions: continue
            
            z = cand['z']
            rsi = cand['rsi']
            
            # Filter 1: Deep Statistical Dip (Fix DIP_BUY)
            if z > self.thresh_z: continue
            
            # Filter 2: Panic Check (RSI)
            if rsi > self.thresh_rsi: continue
            
            # Filter 3: Idiosyncratic Check (Fix EFFICIENT_BREAKOUT)
            # Calculate Alpha: How far is this asset from the Market Median?
            # We want assets that are crashing ON THEIR OWN, not just following the market.
            rel_z = z - market_median_z
            
            if rel_z > self.thresh_alpha: continue
            
            # Scoring: The deeper the Alpha (Relative Z), the better the mean reversion potential.
            # We use abs() because rel_z is negative.
            score = abs(rel_z)
            
            if score > best_alpha_score:
                best_alpha_score = score
                best_cand = cand
        
        if best_cand:
            sym = best_cand['symbol']
            price = best_cand['price']
            
            # Sizing
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
                'reason': ['ALPHA_DIP', f"Z:{best_cand['z']:.2f}", f"Rel:{best_alpha_score:.2f}"]
            }
            
        return None