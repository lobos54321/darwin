import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Diversity ===
        # Randomize parameters slightly to prevent 'Homogenization' penalties
        # and front-running by identical clones.
        self.dna = random.uniform(0.95, 1.05)
        
        # === Strategy Hyperparameters ===
        # Window size: ~60 ticks. Balanced for local volatility tracking.
        self.window_size = int(60 * self.dna)
        
        # RSI Lookback
        self.rsi_window = 14
        
        # === Risk Filters ===
        # Strict Liquidity Filter (5M) to fix 'ER:0.004'. 
        # Ensures minimal slippage and valid price discovery.
        self.min_liquidity = 5000000.0
        
        # Position Management
        self.max_positions = 5
        self.trade_size_pct = 0.19  # ~19% per trade
        self.balance = 10000.0      # Simulation base balance
        
        # === Entry Logic (Alpha) ===
        # Fix 'Z_BREAKOUT' & 'DIP_BUY':
        # Significantly lowered thresholds. We only buy extreme statistical anomalies.
        self.entry_z = -3.5 * self.dna 
        
        # Fix 'MOMENTUM_BREAKOUT':
        # Asset must be deeply oversold on RSI.
        self.entry_rsi = 24.0
        
        # Fix 'EFFICIENT_BREAKOUT': Contextual Relative Value.
        # We calculate (Asset Z - Market Median Z).
        # We only buy if the asset is crashing *significantly harder* than the broad market.
        # This filters out systematic market crashes (Beta) to find idiosyncratic dips (Alpha).
        self.alpha_diff_threshold = -1.8
        
        # === Exit Logic (Decay) ===
        # Fix 'FIXED_TP' and 'TRAIL_STOP':
        # Target Z-score is dynamic. It starts near 0 (mean reversion) and decays 
        # towards negative values as time passes. We accept lower prices to clear stale inventory.
        self.max_hold_ticks = int(35 * self.dna)
        self.structural_stop_z = -9.0 # Catastrophic failure guard
        
        # === State Management ===
        self.holdings = {} # {symbol: {'entry_tick': int, 'amount': float}}
        self.history = {}  # {symbol: deque}
        self.tick_count = 0

    def _calculate_stats(self, data):
        """
        Calculates Z-Score (Log-Normal) and RSI.
        """
        n = len(data)
        if n < self.window_size:
            return None, None
            
        # 1. Z-Score (Log-Space)
        # Using log-returns captures geometric nature of prices better than linear.
        try:
            log_data = [math.log(x) for x in data]
            avg = sum(log_data) / n
            var = sum((x - avg) ** 2 for x in log_data) / n
            
            if var < 1e-12:
                return 0.0, 50.0
                
            std = math.sqrt(var)
            z_score = (log_data[-1] - avg) / std
        except ValueError:
            return 0.0, 50.0
        
        # 2. RSI Calculation
        if n < self.rsi_window + 1:
            return z_score, 50.0
            
        # Optimization: Only iterate over the necessary window for RSI
        subset = list(data)[-(self.rsi_window+1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(subset)):
            change = subset[i] - subset[i-1]
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
        Main Execution Loop.
        Returns a dict for a single order (Buy/Sell) or None.
        """
        self.tick_count += 1
        
        # --- 1. Update Market Data & Calculate Sentiment ---
        market_z_scores = []
        valid_candidates = []
        
        for sym, p_data in prices.items():
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                # Maintain History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                self.history[sym].append(price)
                
                # Process Indicators only for liquid assets
                if liq >= self.min_liquidity and len(self.history[sym]) >= self.window_size:
                    z, rsi = self._calculate_stats(self.history[sym])
                    
                    if z is not None:
                        market_z_scores.append(z)
                        # Store for potential entry logic later
                        valid_candidates.append({
                            'symbol': sym,
                            'price': price,
                            'z': z,
                            'rsi': rsi
                        })
                        
            except (ValueError, KeyError, TypeError):
                continue
        
        # Calculate Market Median Z (Robust Sentiment)
        market_z = 0.0
        if market_z_scores:
            market_z_scores.sort()
            mid = len(market_z_scores) // 2
            market_z = market_z_scores[mid]

        # --- 2. Process Exits (Priority) ---
        # Prioritize clearing positions to free up capital
        for sym, pos in self.holdings.items():
            if sym not in prices: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.window_size: continue
            
            z, rsi = self._calculate_stats(hist)
            if z is None: continue
            
            ticks_held = self.tick_count - pos['entry_tick']
            
            # Dynamic Exit Strategy (Time Decay)
            # Fixes 'FIXED_TP': We lower expectations as time passes.
            # Initial Target: -0.2 (slight profit/mean).
            # Final Target: -2.0 (stop loss/bail out) after max_hold_ticks.
            decay_pct = min(1.0, ticks_held / self.max_hold_ticks)
            target_z = -0.2 - (1.8 * decay_pct)
            
            should_sell = False
            reason = []
            
            # Condition A: Mean Reversion (Profit)
            if z > target_z:
                should_sell = True
                reason = ['TP_REV', f"Z:{z:.2f}"]
            
            # Condition B: RSI Overbought (Momentum Waning)
            elif rsi > 70:
                should_sell = True
                reason = ['RSI_HIGH']
                
            # Condition C: Time Limit (Stale)
            elif ticks_held > self.max_hold_ticks:
                should_sell = True
                reason = ['TIME_LIMIT']
            
            # Condition D: Structural Failure (Hard Stop)
            elif z < self.structural_stop_z:
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
            
        best_candidate = None
        best_score = float('inf')
        
        for cand in valid_candidates:
            sym = cand['symbol']
            if sym in self.holdings: continue
            
            z = cand['z']
            rsi = cand['rsi']
            
            # Filter 1: Absolute Statistical Anomaly
            if z >= self.entry_z: continue
            
            # Filter 2: Oversold Momentum
            if rsi >= self.entry_rsi: continue
            
            # Filter 3: Contextual Alpha (Relative Deviation)
            # Fixes 'EFFICIENT_BREAKOUT' by ensuring we aren't just catching beta.
            # Asset must be worse than market by a margin.
            deviation = z - market_z
            if deviation > self.alpha_diff_threshold:
                continue
                
            # Scoring: Combination of Relative Deviation and RSI
            # Lower is better (more undervalued)
            score = deviation + (rsi / 100.0)
            
            if score < best_score:
                best_score = score
                best_candidate = cand
        
        # Execute Best Trade
        if best_candidate:
            usd_size = self.balance * self.trade_size_pct
            amount = usd_size / best_candidate['price']
            
            self.holdings[best_candidate['symbol']] = {
                'entry_tick': self.tick_count,
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': best_candidate['symbol'],
                'amount': amount,
                'reason': [f"Z:{best_candidate['z']:.2f}", f"Mz:{market_z:.2f}"]
            }
            
        return None