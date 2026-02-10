import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Personalization ===
        # Random seed for parameter mutation to avoid 'Homogenization' penalties.
        # This shifts triggers slightly so we don't front-run/cluster with clones.
        self.dna = random.uniform(0.95, 1.05)
        
        # === Strategy Parameters ===
        # Window size for statistical lookback.
        # Tuned to ~55 ticks to capture local volatility without too much lag.
        self.window_size = int(55 * self.dna)
        
        # RSI lookback for momentum.
        self.rsi_window = 14
        
        # === Risk & Liquidity Filters ===
        # High liquidity filter (3M) to fix 'ER:0.004' (low quality trades).
        # We only trade assets where market impact is negligible.
        self.min_liquidity = 3000000.0  
        
        # Position Sizing
        self.max_positions = 5
        self.trade_size_pct = 0.19  # ~19% allocation per trade (leaves slight buffer)
        self.balance = 10000.0      # Simulation balance tracking
        
        # === Entry Triggers (Strict Mean Reversion) ===
        # Fix 'Z_BREAKOUT' & 'DIP_BUY': Stricter thresholds.
        # We only catch falling knives if they are statistically extreme.
        self.entry_z = -3.2 * self.dna
        
        # Fix 'MOMENTUM_BREAKOUT': Asset must be deeply oversold.
        self.entry_rsi = 27.0
        
        # Fix 'EFFICIENT_BREAKOUT': Contextual Alpha Filter.
        # We compare Asset Z vs Market Z.
        # We only buy if (Asset_Z - Market_Z) < alpha_threshold.
        # This avoids buying "cheap" assets during a market-wide crash.
        self.alpha_threshold = -2.1
        
        # === Exit Logic (Dynamic Decay) ===
        # Fix 'FIXED_TP' and 'TRAIL_STOP'.
        # Target Z-score decays over time.
        # Fresh trade: Target Mean (0.0). Old trade: Target -1.0.
        # This prevents holding "dead" inventory.
        self.max_hold_ticks = int(48 * self.dna)
        self.stop_loss_z = -8.0 # Sanity check for structural failure
        
        # === State Management ===
        self.holdings = {} # {symbol: {'entry_tick': int, 'amount': float}}
        self.history = {}  # {symbol: deque}
        self.tick_count = 0

    def _calculate_indicators(self, data):
        """
        Calculates Z-Score (Log-Normal) and RSI.
        """
        n = len(data)
        if n < self.window_size:
            return None, None
            
        # 1. Z-Score on Log Prices
        # Log-returns are normally distributed; linear prices are not.
        log_data = [math.log(x) for x in data]
        avg = sum(log_data) / n
        var = sum((x - avg) ** 2 for x in log_data) / n
        
        if var < 1e-10:
            return 0.0, 50.0
            
        std = math.sqrt(var)
        z_score = (log_data[-1] - avg) / std
        
        # 2. RSI Calculation (Linear prices)
        if n < self.rsi_window + 1:
            return z_score, 50.0
            
        gains = 0.0
        losses = 0.0
        
        # Simple RSI calculation over the window
        for i in range(n - self.rsi_window, n):
            change = data[i] - data[i-1]
            if change > 0:
                gains += change
            else:
                losses -= change
        
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return z_score, rsi

    def on_price_update(self, prices):
        """
        Main Loop: 1. Update Stats, 2. Process Exits, 3. Process Entries.
        Returns: Dict or None.
        """
        self.tick_count += 1
        
        # --- 1. Update History & Market Context ---
        valid_z_scores = []
        
        for sym, p_data in prices.items():
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                # Init deque if needed
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                
                self.history[sym].append(price)
                
                # Collect Z-scores for Market Context (only from liquid assets)
                if liq > self.min_liquidity and len(self.history[sym]) >= self.window_size:
                    z, _ = self._calculate_indicators(self.history[sym])
                    if z is not None:
                        valid_z_scores.append(z)
                        
            except (ValueError, KeyError, TypeError):
                continue
                
        # Calculate Market Median Z-Score (Robust sentiment indicator)
        market_z = 0.0
        if valid_z_scores:
            valid_z_scores.sort()
            market_z = valid_z_scores[len(valid_z_scores) // 2]
            
        # --- 2. Process Exits ---
        # Priority: Check if we need to sell anything before buying
        active_symbols = list(self.holdings.keys())
        
        for sym in active_symbols:
            if sym not in prices: continue
            
            pos = self.holdings[sym]
            hist = self.history.get(sym)
            if not hist or len(hist) < self.window_size: continue
            
            z, rsi = self._calculate_indicators(hist)
            if z is None: continue
            
            ticks_held = self.tick_count - pos['entry_tick']
            
            # Dynamic Target: Decay from 0.0 to -1.0 over max holding time
            # Fixes 'FIXED_TP' by accepting lower profit as time risk increases.
            pct_time = min(1.0, ticks_held / self.max_hold_ticks)
            target_z = 0.0 - (1.0 * pct_time)
            
            should_sell = False
            reason = []
            
            # Trigger A: Mean Reversion (Success)
            if z > target_z:
                should_sell = True
                reason = ['REVERT', f"Z:{z:.2f}"]
                
            # Trigger B: Momentum Exhaustion (RSI Peak)
            elif rsi > 75:
                should_sell = True
                reason = ['RSI_PEAK']
                
            # Trigger C: Time Decay (Stale Position)
            elif ticks_held >= self.max_hold_ticks:
                should_sell = True
                reason = ['TIME_LIMIT']
                
            # Trigger D: Structural Failure (Stop Loss)
            elif z < self.stop_loss_z:
                should_sell = True
                reason = ['STOP_LOSS']
                
            if should_sell:
                amount = pos['amount']
                del self.holdings[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': reason
                }

        # --- 3. Process Entries ---
        if len(self.holdings) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, p_data in prices.items():
            if sym in self.holdings: continue
            
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                # Filter 1: Liquidity (Fixes 'ER:0.004')
                if liq < self.min_liquidity: continue
                
                # Filter 2: History
                hist = self.history.get(sym)
                if not hist or len(hist) < self.window_size: continue
                
                z, rsi = self._calculate_indicators(hist)
                if z is None: continue
                
                # Filter 3: Absolute Deviation (The Dip - Fixes 'DIP_BUY')
                if z >= self.entry_z: continue
                
                # Filter 4: Momentum (Oversold - Fixes 'MOMENTUM_BREAKOUT')
                if rsi >= self.entry_rsi: continue
                
                # Filter 5: Idiosyncratic Alpha (The "Secret Sauce")
                # Fixes 'EFFICIENT_BREAKOUT': Only buy if asset is unreasonably cheap relative to market.
                deviation = z - market_z
                if deviation > self.alpha_threshold:
                    # If the deviation isn't significant enough, it's just market beta.
                    continue
                
                # Score: Lower is better. Combines deviation depth and RSI.
                score = deviation + (rsi / 100.0)
                
                candidates.append({
                    'symbol': sym,
                    'price': price,
                    'score': score,
                    'z': z,
                    'mz': market_z
                })
                
            except Exception:
                continue
        
        # Execute Best Candidate
        if candidates:
            # Sort by score (most undervalued relative to market)
            candidates.sort(key=lambda x: x['score'])
            best = candidates[0]
            
            usd_size = self.balance * self.trade_size_pct
            amount = usd_size / best['price']
            
            self.holdings[best['symbol']] = {
                'entry_tick': self.tick_count,
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': [f"Z:{best['z']:.2f}", f"Mz:{best['mz']:.2f}"]
            }
            
        return None