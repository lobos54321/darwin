import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Mutation ===
        # DNA modifies lookback and thresholds to prevent 'Homogenization'.
        # Random variance allows the agent to find unique pockets of liquidity.
        self.dna_risk = random.uniform(0.9, 1.1)
        self.dna_time = random.uniform(0.95, 1.05)
        
        # === Core Parameters ===
        self.lookback = int(60 * self.dna_time)
        self.rsi_period = 14
        
        # === Filters (Fix ER:0.004) ===
        # Raised liquidity floor significantly (8.5M) to filter 'ghost' volume and reduce slippage.
        # High liquidity assets respect statistical bounds better than low cap noise.
        self.min_liquidity = 8500000.0 
        
        # === Entry Logic (Fix EFFICIENT_BREAKOUT) ===
        # We require a 'Snap' (high volatility dip) rather than a 'Slide' (trend change).
        # Stricter thresholds ensure we only catch deviations, not repricing.
        self.entry_z_trigger = -3.45 * self.dna_risk 
        self.entry_rsi_max = 26.0
        
        # Alpha Check: The asset must be crashing *relative* to the market.
        # If Market Z is -3 and Asset Z is -3, it's Beta (systemic). We want Alpha (idiosyncratic).
        self.alpha_z_dist = -1.8 # Asset must be 1.8 std devs below the MARKET median
        
        # === Exit Logic (Fix FIXED_TP) ===
        # Replaced Fixed TP with Adaptive Mean Reversion.
        # Target adjusts based on Market Sentiment and Holding Time.
        self.max_hold_time = int(50 * self.dna_time)
        self.hard_stop_z = -9.0 # Catastrophic failure line
        
        # === Position Management ===
        self.max_pos = 5
        self.balance = 10000.0 
        self.pos_size_pct = 0.18 # Conservative sizing
        
        # === State ===
        self.prices_history = {} # symbol -> deque
        self.positions = {} # symbol -> dict
        self.tick = 0

    def _calc_stats(self, data):
        """ Calculate Z-Score (Log-Normal) and RSI efficiently without numpy. """
        if len(data) < self.lookback:
            return None
            
        # 1. Log Returns & Z-Score
        # Using log-prices aligns better with geometric Brownian motion of crypto assets
        try:
            log_p = [math.log(x) for x in data]
            avg = sum(log_p) / len(log_p)
            # Variance calculation
            var = sum((x - avg)**2 for x in log_p) / len(log_p)
            
            if var < 1e-12: return None # Filter flatline/dead assets
            
            std = math.sqrt(var)
            curr_log = log_p[-1]
            z = (curr_log - avg) / std
        except (ValueError, ZeroDivisionError):
            return None

        # 2. RSI (Wilder's Smoothing approximation on tail)
        # Optimization: Only calculate RSI on the relevant subset
        subset = list(data)[-(self.rsi_period + 1):]
        gains, losses = 0.0, 0.0
        
        for i in range(1, len(subset)):
            delta = subset[i] - subset[i-1]
            if delta > 0: gains += delta
            else: losses -= delta
            
        if losses == 0: 
            rsi = 100.0
        elif gains == 0: 
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z, 'rsi': rsi, 'price': data[-1]}

    def on_price_update(self, prices):
        """
        Executes HFT logic:
        1. Aggregates data & Calculates Market Regime (Median Z).
        2. Checks Exits using Adaptive Targets.
        3. Scans for Idiosyncratic Alpha Dips.
        """
        self.tick += 1
        
        # 1. Ingest Data & Calculate Market State
        market_zs = []
        candidates = []
        
        for sym, p_data in prices.items():
            try:
                # Safe parsing of string inputs
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                # History Management
                if sym not in self.prices_history:
                    self.prices_history[sym] = deque(maxlen=self.lookback)
                self.prices_history[sym].append(price)
                
                # Pre-filters
                if liq < self.min_liquidity: continue
                if len(self.prices_history[sym]) < self.lookback: continue
                
                stats = self._calc_stats(self.prices_history[sym])
                if stats:
                    stats['symbol'] = sym
                    market_zs.append(stats['z'])
                    candidates.append(stats)
                    
            except (KeyError, ValueError, TypeError):
                continue

        # Market Regime: Median Z
        # Used to normalize individual asset performance against the "tide".
        # This prevents buying "cheap" assets that are actually just following a market crash.
        market_median_z = 0.0
        if market_zs:
            market_zs.sort()
            market_median_z = market_zs[len(market_zs)//2]

        # 2. Check Exits (Priority 1)
        # Fix FIXED_TP: Use Adaptive Mean Reversion
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            curr_data = prices.get(sym)
            if not curr_data: continue
            
            hist = self.prices_history.get(sym)
            if not hist: continue
            
            stats = self._calc_stats(hist)
            if not stats: continue
            
            z = stats['z']
            rsi = stats['rsi']
            held_ticks = self.tick - pos['entry_tick']
            
            # --- Dynamic Exit Threshold ---
            # Ideally, we want to sell when Z returns to Mean (0).
            # However, we adjust for Market Median and Time Decay.
            
            # Decay factor: 0.0 to 1.0 over max_hold_time
            decay = min(1.0, held_ticks / self.max_hold_time)
            
            # Base Target: Slightly better than the market median
            base_target = max(0.0, market_median_z + 0.5)
            
            # Decayed Target: Acceptance of loss to clear inventory (Soft Stop)
            # Moves from Base Target down to -2.0
            exit_threshold = base_target - (3.0 * decay) 
            
            should_sell = False
            reason = []
            
            if z > exit_threshold:
                should_sell = True
                reason = ['ADAPTIVE_TP', f"Z{z:.2f}>T{exit_threshold:.2f}"]
            elif rsi > 78:
                should_sell = True
                reason = ['RSI_CLIMAX']
            elif z < self.hard_stop_z:
                should_sell = True
                reason = ['STOP_LOSS']
            elif held_ticks >= self.max_hold_time:
                should_sell = True
                reason = ['TIMEOUT']
                
            if should_sell:
                amt = pos['amount']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': reason
                }

        # 3. Check Entries (Priority 2)
        if len(self.positions) >= self.max_pos:
            return None
            
        # Scoring: Find the most disconnected asset (Deepest relative dip)
        best_candidate = None
        best_score = 999.0
        
        for cand in candidates:
            sym = cand['symbol']
            if sym in self.positions: continue
            
            z = cand['z']
            rsi = cand['rsi']
            
            # Filter 1: Deep Value (Stricter DIP_BUY thresholds)
            if z > self.entry_z_trigger: continue
            
            # Filter 2: RSI Verification (Oversold)
            if rsi > self.entry_rsi_max: continue
            
            # Filter 3: Alpha Check (Fix EFFICIENT_BREAKOUT)
            # Ensure the drop is idiosyncratic.
            # Calculate distance from Market Median. If the whole market is down -3 sigma,
            # an asset at -3.2 sigma is NOT a buy. It must be an outlier.
            rel_z = z - market_median_z
            if rel_z > self.alpha_z_dist: continue
            
            # Score: Minimize Relative Z (The more disjoint from market, the better)
            score = rel_z
            
            if score < best_score:
                best_score = score
                best_candidate = cand
        
        if best_candidate:
            sym = best_candidate['symbol']
            price = best_candidate['price']
            
            # Sizing
            usd_size = self.balance * self.pos_size_pct
            amt = usd_size / price
            
            self.positions[sym] = {
                'entry_tick': self.tick,
                'amount': amt,
                'entry_z': best_candidate['z']
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amt,
                'reason': ['ALPHA_DIP', f"Z:{best_candidate['z']:.2f}", f"Rel:{best_score:.2f}"]
            }
            
        return None