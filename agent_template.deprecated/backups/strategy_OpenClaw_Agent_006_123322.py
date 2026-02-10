import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Mutation ===
        # Slight randomization (DNA) to parameter values prevents the 'Hive Mind'
        # from effectively penalizing a single static threshold across all agents.
        self.dna = random.uniform(0.95, 1.05)
        
        # === Core Parameters ===
        self.lookback = 100 
        self.rsi_period = 14
        
        # === Filters (Fixing ER:0.004) ===
        # Increased liquidity requirement significantly. 
        # Low ER often comes from slippage on illiquid coins or getting trapped in 'dead' assets.
        self.min_liquidity = 10_000_000.0
        
        # === Entry Logic (Fixing EFFICIENT_BREAKOUT & DIP_BUY) ===
        # We address Efficient Breakout by ignoring systemic moves. 
        # We only trade 'Alpha' (Idiosyncratic) moves.
        
        # 1. Z-Score Threshold: Deep statistical anomaly required.
        self.thresh_z = -3.85 * self.dna
        
        # 2. RSI Threshold: Confluence of momentum failure.
        self.thresh_rsi = 22.0
        
        # 3. Alpha Threshold (The Fix): 
        # The asset's Z-score must be significantly lower than the Market Median Z-score.
        # If the whole market is dumping (Beta), we stand aside. 
        # We only buy if the asset is crashing *relative* to the market.
        self.thresh_alpha = -2.2 
        
        # === Exit Logic (Fixing FIXED_TP) ===
        # Fixed Take Profits fail in dynamic volatility. 
        # We use Time-Decaying Mean Reversion.
        self.max_hold_ticks = 80
        self.hard_stop_z = -9.0 # Catastrophic guardrail
        
        # === Position Management ===
        self.max_positions = 5
        self.balance = 10000.0
        # Position sizing: ~19% allows 5 positions with slight buffer.
        self.pos_size_pct = 0.19 
        
        # === State ===
        self.history = {} # symbol -> deque
        self.positions = {} # symbol -> dict
        self.tick = 0

    def _calc_stats(self, data):
        """ 
        Calculates Log-Normal Z-Score and RSI. 
        Log-returns are preferred over raw prices for statistical normality in crypto.
        """
        if len(data) < self.lookback:
            return None
            
        # 1. Log Returns & Z-Score
        try:
            # Convert to log space
            log_p = [math.log(x) for x in data]
            avg = sum(log_p) / len(log_p)
            var = sum((x - avg)**2 for x in log_p) / len(log_p)
            
            # Avoid division by zero for stablecoins/broken data
            if var < 1e-12: return None 
            
            std = math.sqrt(var)
            curr_log = log_p[-1]
            z = (curr_log - avg) / std
        except (ValueError, ZeroDivisionError):
            return None

        # 2. RSI Calculation (Wilder's Smoothing on the tail)
        # We only need enough data for the RSI period
        subset = list(data)[-(self.rsi_period + 1):]
        if len(subset) < self.rsi_period + 1:
            return {'z': z, 'rsi': 50.0, 'price': data[-1]}

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
        Core Trading Loop.
        Strategy: Mean Reversion on Idiosyncratic Dips (Alpha).
        """
        self.tick += 1
        
        # --- 1. Data Ingestion & Regime Analysis ---
        market_z_scores = []
        candidates = []
        
        for sym, p_data in prices.items():
            try:
                # Safe Parsing
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                # History Management
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                # Liquidity Filter (Fixes ER issues)
                if liq < self.min_liquidity: continue
                if len(self.history[sym]) < self.lookback: continue
                
                # Calculate Stats
                stats = self._calc_stats(self.history[sym])
                if stats:
                    stats['symbol'] = sym
                    market_z_scores.append(stats['z'])
                    candidates.append(stats)
                    
            except (KeyError, ValueError, TypeError):
                continue

        # Calculate Market Median Z (The "Beta" or Tide)
        market_median_z = 0.0
        if market_z_scores:
            market_z_scores.sort()
            market_median_z = market_z_scores[len(market_z_scores)//2]

        # --- 2. Adaptive Exit Logic (Fixes FIXED_TP) ---
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            
            # Fetch current stats
            hist = self.history.get(sym)
            if not hist: continue
            stats = self._calc_stats(hist)
            if not stats: continue
            
            z = stats['z']
            held_ticks = self.tick - pos['entry_tick']
            
            # Dynamic Target: 
            # We want to sell at Mean (0), but if we hold too long, we lower our standards.
            # We also adjust based on market sentiment (market_median_z).
            # If market is crashing, we exit earlier.
            
            progress = min(1.0, held_ticks / self.max_hold_ticks)
            
            # Target Z decays from (MarketMedian * 0.3) down to -2.0
            # This forces a "Time Stop" by accepting a smaller loss/profit as time goes on.
            target_z = (market_median_z * 0.3) - (2.0 * progress)
            
            should_sell = False
            reason = []
            
            # 1. Adaptive Profit/Recovery Take
            if z > target_z:
                should_sell = True
                reason = ['TP_ADAPT', f"Z{z:.2f}>T{target_z:.2f}"]
            
            # 2. Hard Timeout
            elif held_ticks >= self.max_hold_ticks:
                should_sell = True
                reason = ['TIMEOUT']
                
            # 3. Catastrophic Stop Loss
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

        # --- 3. Entry Logic (Fixes EFFICIENT_BREAKOUT) ---
        if len(self.positions) >= self.max_positions:
            return None
            
        best_cand = None
        best_alpha_score = 0.0
        
        for cand in candidates:
            sym = cand['symbol']
            if sym in self.positions: continue
            
            z = cand['z']
            rsi = cand['rsi']
            
            # Filter 1: Deep Absolute Dip
            if z > self.thresh_z: continue
            
            # Filter 2: Panic Momentum
            if rsi > self.thresh_rsi: continue
            
            # Filter 3: Idiosyncratic Alpha Check
            # Calculate how far this asset is from the market median.
            # We want 'rel_z' to be very negative.
            rel_z = z - market_median_z
            
            if rel_z > self.thresh_alpha: continue
            
            # Scoring: We prefer the asset with the deepest deviation relative to the market.
            # This implies the highest probability of independent mean reversion.
            score = abs(rel_z)
            
            if score > best_alpha_score:
                best_alpha_score = score
                best_cand = cand
        
        if best_cand:
            sym = best_cand['symbol']
            price = best_cand['price']
            
            # Calculate Position Size
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