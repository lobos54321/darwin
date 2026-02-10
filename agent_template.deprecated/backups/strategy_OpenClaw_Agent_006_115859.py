import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Mutation ===
        # DNA modifies lookback and thresholds to avoid 'Homogenization'
        # High-frequency strategies often fail when too many agents use identical parameters.
        self.dna = random.uniform(0.92, 1.08)
        
        # === Core Parameters ===
        # Shorter window for faster reaction to volatility expansion
        self.window_size = int(55 * self.dna)
        self.rsi_period = 14
        
        # === Risk Management ===
        # Fix 'ER:0.004': Increased liquidity floor to ensure efficient execution.
        self.min_liquidity = 6000000.0
        
        # Fix 'DIP_BUY': Stricter thresholds for statistical anomalies.
        # We only catch falling knives that are significantly disjoint from the market.
        self.entry_z_threshold = -3.2 * self.dna
        self.entry_rsi_threshold = 28.0
        self.relative_alpha_threshold = -1.6  # Asset Z must be 1.6 std dev worse than Market Median Z
        
        # === Position Sizing ===
        self.max_positions = 5
        self.balance = 10000.0 
        self.trade_size_pct = 0.18 # Leave buffer for fees/slippage
        
        # === Exit Logic parameters ===
        # Fix 'FIXED_TP': Dynamic decay.
        self.max_hold_duration = int(40 * self.dna)
        self.hard_stop_z = -8.0
        
        # === State ===
        self.history = {} # {symbol: deque}
        self.holdings = {} # {symbol: {'entry_tick': int, 'amount': float, 'entry_z': float}}
        self.tick_count = 0

    def _analyze_series(self, data):
        """
        Computes Z-Score (Log-Normal) and RSI without numpy.
        """
        n = len(data)
        if n < self.window_size:
            return None, None, None

        # 1. Z-Score Calculation (Log Space)
        try:
            log_prices = [math.log(p) for p in data]
            mean_log = sum(log_prices) / n
            variance = sum((x - mean_log) ** 2 for x in log_prices) / n
            
            if variance < 1e-10: # Filter low volatility noise
                return 0.0, 50.0, 0.0
                
            std_dev = math.sqrt(variance)
            current_log_price = log_prices[-1]
            z_score = (current_log_price - mean_log) / std_dev
            
        except ValueError:
            return 0.0, 50.0, 0.0

        # 2. RSI Calculation
        if n <= self.rsi_period:
            return z_score, 50.0, variance

        # Optimization: only calculate RSI on the tail
        deltas = []
        subset = list(data)[-(self.rsi_period+1):]
        
        gain_sum = 0.0
        loss_sum = 0.0
        
        for i in range(1, len(subset)):
            diff = subset[i] - subset[i-1]
            if diff > 0:
                gain_sum += diff
            else:
                loss_sum -= diff
                
        if loss_sum == 0:
            rsi = 100.0
        elif gain_sum == 0:
            rsi = 0.0
        else:
            rs = gain_sum / loss_sum
            rsi = 100.0 - (100.0 / (1.0 + rs))

        return z_score, rsi, variance

    def on_price_update(self, prices):
        """
        Core HFT Logic:
        1. Updates data history.
        2. Calculates Market Regime (Median Z-Score).
        3. Manages Exits (Time-decaying targets).
        4. Scans for Idiosyncratic Dips (Alpha entries).
        """
        self.tick_count += 1
        
        # 1. Data Ingestion & Market Sentiment
        candidates = []
        market_z_values = []
        
        for symbol, data in prices.items():
            try:
                # Parse inputs safely
                price = float(data['priceUsd'])
                liquidity = float(data['liquidity'])
                
                # Update history
                if symbol not in self.history:
                    self.history[symbol] = deque(maxlen=self.window_size)
                self.history[symbol].append(price)
                
                # Skip calculations for illiquid or immature history
                if liquidity < self.min_liquidity or len(self.history[symbol]) < self.window_size:
                    continue
                
                z, rsi, var = self._analyze_series(self.history[symbol])
                
                if z is not None:
                    market_z_values.append(z)
                    candidates.append({
                        'symbol': symbol,
                        'price': price,
                        'z': z,
                        'rsi': rsi,
                        'vol': var
                    })
                    
            except (KeyError, ValueError, TypeError):
                continue
        
        # Compute Market Median Z (Robust Baseline)
        market_median_z = 0.0
        if market_z_values:
            market_z_values.sort()
            mid_idx = len(market_z_values) // 2
            market_median_z = market_z_values[mid_idx]

        # 2. Priority: Manage Exits
        # We iterate existing holdings to see if we should sell
        for symbol in list(self.holdings.keys()):
            pos = self.holdings[symbol]
            current_price_data = prices.get(symbol)
            
            if not current_price_data: continue
            
            # Recalculate metrics for holding
            hist = self.history.get(symbol)
            if not hist: continue
            
            z, rsi, _ = self._analyze_series(hist)
            if z is None: continue
            
            ticks_held = self.tick_count - pos['entry_tick']
            
            # === Dynamic Exit Mutation ===
            # Instead of a fixed take profit, we use a Time-Decay Threshold.
            # At tick 0, we demand a strong reversion (Z > 0).
            # As time passes, we accept lower Z scores to clear inventory (Time value of money).
            # Formula: Target = 0.0 - (DecayFactor * Ticks)
            
            # We normalize decay so that by max_hold_duration, we accept a loss (Z = -2.5)
            # This acts as a "soft stop" that tightens over time.
            decay_progress = ticks_held / self.max_hold_duration
            target_z = 0.1 - (2.6 * decay_progress) 
            
            should_exit = False
            exit_reason = []
            
            # A. Dynamic Target Reached (Profit or Time-Stop)
            if z >= target_z:
                should_exit = True
                exit_reason = ['DYN_TARGET', f"Z:{z:.2f}>T:{target_z:.2f}"]
                
            # B. Momentum Exhaustion (RSI Overbought)
            elif rsi > 75:
                should_exit = True
                exit_reason = ['RSI_PEAK']
                
            # C. Hard Structural Failure (Stop Loss)
            elif z < self.hard_stop_z:
                should_exit = True
                exit_reason = ['STRUCT_FAIL']
            
            # D. Absolute Time Limit
            elif ticks_held > self.max_hold_duration:
                should_exit = True
                exit_reason = ['TIME_LIMIT']

            if should_exit:
                amount = pos['amount']
                del self.holdings[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': exit_reason
                }

        # 3. Priority: Scan for Entries
        if len(self.holdings) >= self.max_positions:
            return None
            
        best_opp = None
        best_score = float('inf') # Lower is better
        
        for cand in candidates:
            sym = cand['symbol']
            if sym in self.holdings: continue
            
            z = cand['z']
            rsi = cand['rsi']
            
            # --- Filter Set ---
            
            # 1. Absolute Statistical Floor
            if z >= self.entry_z_threshold:
                continue
                
            # 2. RSI Floor (Oversold)
            if rsi >= self.entry_rsi_threshold:
                continue
            
            # 3. Contextual Alpha Filter (Fix 'EFFICIENT_BREAKOUT')
            # The asset must be crashing *relative* to the market median.
            # If the whole market is down (Beta), we ignore it. 
            # We want idiosyncratic failure (Alpha).
            relative_deviation = z - market_median_z
            if relative_deviation > self.relative_alpha_threshold:
                continue
                
            # Scoring: Combine relative deviation and RSI
            # We prioritize the asset showing the most extreme relative weakness
            score = relative_deviation + (rsi / 100.0)
            
            if score < best_score:
                best_score = score
                best_opp = cand
        
        # Execute Buy
        if best_opp:
            price = best_opp['price']
            # Position sizing based on current balance
            usd_amount = self.balance * self.trade_size_pct
            token_amount = usd_amount / price
            
            self.holdings[best_opp['symbol']] = {
                'entry_tick': self.tick_count,
                'amount': token_amount,
                'entry_z': best_opp['z']
            }
            
            return {
                'side': 'BUY',
                'symbol': best_opp['symbol'],
                'amount': token_amount,
                'reason': [f"Z:{best_opp['z']:.2f}", f"Rel:{best_opp['z']-market_median_z:.2f}"]
            }

        return None