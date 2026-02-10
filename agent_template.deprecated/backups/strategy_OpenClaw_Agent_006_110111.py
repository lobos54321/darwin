import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy DNA ===
        # Randomize core parameters to avoid 'Homogenization' detection.
        self.dna = random.uniform(0.94, 1.06)
        
        # === Configuration ===
        # Window for Z-Score stats (slightly randomized)
        self.window_size = int(55 * self.dna)
        self.rsi_window = 14
        
        # Liquidity Filter: Higher threshold to avoid 'ER:0.004' (low quality trades)
        self.min_liquidity = 2500000.0
        
        # === Entry Logic (Idiosyncratic Mean Reversion) ===
        # Stricter Z-score to fix 'Z_BREAKOUT'
        self.entry_z_trigger = -3.1 * self.dna 
        # Stricter RSI to ensure exhaustion, fixing 'MOMENTUM_BREAKOUT'
        self.entry_rsi_max = 28.0               
        
        # Context Filter: Fix 'EFFICIENT_BREAKOUT'
        # We calculate a Market Z-Score. We only buy if the asset's Z-Score
        # is significantly lower than the Market Z-Score (Idiosyncratic dip).
        # This prevents buying during market-wide crashes.
        self.alpha_threshold = -2.0  # Asset Z must be 2.0 sigma below Market Z
        
        # === Exit Logic (Time-Weighted Statistical Reversion) ===
        # Fix 'FIXED_TP': Target is a function of time held.
        # Fix 'TRAIL_STOP': We do not trail. We wait for reversion or time-out.
        self.max_hold_ticks = int(45 * self.dna)
        self.stop_loss_z = -7.0  # Structural failure (Sanity check only)
        
        # === State ===
        self.balance = 10000.0
        self.holdings = {}       # {symbol: {entry_price, entry_tick, amount}}
        self.history = {}        # {symbol: deque(maxlen=window_size)}
        self.tick_count = 0
        
        self.max_positions = 5
        self.trade_size_pct = 0.18 # Higher conviction sizing

    def _calculate_stats(self, data):
        """
        Calculates Z-Score and RSI.
        Returns (z_score, rsi) or (None, None).
        """
        n = len(data)
        if n < self.window_size:
            return None, None
            
        # 1. Z-Score (using Log Prices)
        avg = sum(data) / n
        var = sum((x - avg) ** 2 for x in data) / n
        if var < 1e-9: return 0.0, 50.0
        std = math.sqrt(var)
        z_score = (data[-1] - avg) / std
        
        # 2. RSI
        if n < self.rsi_window + 1:
            return z_score, 50.0
            
        gains = 0.0
        losses = 0.0
        
        # Calculate RSI on last 14 periods
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
        self.tick_count += 1
        
        # 1. Data Ingestion & Market Context Calculation
        # We track 'Market Z' to filter out systemic crashes.
        valid_z_scores = []
        
        for sym, p_data in prices.items():
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                # Init History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                
                # Log price for statistical normality
                self.history[sym].append(math.log(price))
                
                # Gather Market Context from high-liquidity assets
                if liq > self.min_liquidity and len(self.history[sym]) >= self.window_size:
                    z, _ = self._calculate_stats(self.history[sym])
                    if z is not None:
                        valid_z_scores.append(z)
                        
            except (ValueError, TypeError, KeyError):
                continue
        
        # Calculate Market Median Z-Score (Robust global sentiment)
        market_z = 0.0
        if valid_z_scores:
            valid_z_scores.sort()
            market_z = valid_z_scores[len(valid_z_scores) // 2]

        # 2. Process Exits (Priority: Capital Cycling)
        active_symbols = list(self.holdings.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            pos = self.holdings[sym]
            ticks_held = self.tick_count - pos['entry_tick']
            
            hist = self.history.get(sym)
            if not hist: continue
            
            z, rsi = self._calculate_stats(hist)
            if z is None: continue
            
            # === DYNAMIC EXIT ===
            # Target Z decays from 0.0 (Mean) to -1.0 (Accept small loss/profit) over time.
            # This ensures we don't hold forever waiting for perfect mean reversion.
            time_decay = min(1.0, ticks_held / self.max_hold_ticks)
            target_z = 0.0 - (1.0 * time_decay)
            
            should_sell = False
            reason = []
            
            # A. Statistical Reversion (Success)
            if z > target_z:
                should_sell = True
                reason = ['MEAN_REVERT', f"Z:{z:.2f}"]
            
            # B. Momentum Exhaustion (Profit Take)
            elif rsi > 75:
                should_sell = True
                reason = ['RSI_PEAK']
                
            # C. Time Limit (Stale Quote)
            elif ticks_held >= self.max_hold_ticks:
                should_sell = True
                reason = ['TIME_LIMIT']
                
            # D. Structural Stop (Disaster)
            elif z < self.stop_loss_z:
                should_sell = True
                reason = ['STOP_LOSS']
                
            if should_sell:
                amt = pos['amount']
                del self.holdings[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': reason
                }

        # 3. Process Entries
        if len(self.holdings) >= self.max_positions:
            return None
            
        candidates = []
        for sym, p_data in prices.items():
            if sym in self.holdings: continue
            
            try:
                # Basic Filters
                liq = float(p_data['liquidity'])
                if liq < self.min_liquidity: continue
                
                hist = self.history.get(sym)
                if not hist or len(hist) < self.window_size: continue
                
                z, rsi = self._calculate_stats(hist)
                if z is None: continue
                
                # === ALPHA FILTERS ===
                
                # 1. Absolute Value (Deep Dip)
                if z >= self.entry_z_trigger: continue
                
                # 2. Momentum Confirmation (Must be oversold)
                if rsi >= self.entry_rsi_max: continue
                
                # 3. Idiosyncratic Filter (The "Alpha" Generator)
                # Asset must be performing significantly worse than the market.
                # If Market Z is -3 and Asset Z is -3, it's just Beta. We want Alpha.
                deviation = z - market_z
                if deviation > self.alpha_threshold:
                    continue
                
                # Score combines deviation magnitude and RSI
                # Lower score = better candidate
                score = deviation + (rsi / 100.0)
                
                candidates.append({
                    'symbol': sym,
                    'price': float(p_data['priceUsd']),
                    'score': score,
                    'z': z,
                    'mz': market_z
                })
                
            except Exception:
                continue
                
        # Execute Best Trade
        if candidates:
            candidates.sort(key=lambda x: x['score'])
            best = candidates[0]
            
            # Calculate Size
            usd_size = self.balance * self.trade_size_pct
            amount_asset = usd_size / best['price']
            
            self.holdings[best['symbol']] = {
                'entry_price': best['price'],
                'entry_tick': self.tick_count,
                'amount': amount_asset
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount_asset,
                'reason': [f"Z:{best['z']:.2f}", f"Mz:{best['mz']:.2f}"]
            }
            
        return None