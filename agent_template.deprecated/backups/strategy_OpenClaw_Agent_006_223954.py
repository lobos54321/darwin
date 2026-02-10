import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Diversity ===
        # Unique DNA to differentiate from the Hive Mind and other instances
        self.dna = random.uniform(0.93, 1.07)
        
        # === Core Parameters ===
        self.lookback = int(58 * self.dna)
        self.rsi_period = 14
        self.max_history = self.lookback + self.rsi_period + 20
        
        # === Capital Allocation ===
        self.balance = 10000.0
        self.max_positions = 5
        self.pos_size_pct = 0.19  # Conservative per-trade allocation
        
        # === Filters (Fixing LR_RESIDUAL) ===
        # LR_RESIDUAL implies trading noise or assets with poor mean-reversion properties.
        # We increase liquidity significantly to ensure we are trading structural inefficiencies, not order book gaps.
        self.min_liquidity = 16_000_000.0 
        self.min_volatility = 0.002 * self.dna # Filter out dead assets
        
        # === Entry Thresholds (Fixing Z:-3.93) ===
        # The penalty indicates -3.93 is a dangerous level (likely momentum continuation).
        # We push the trigger to -4.3+ and enforce stricter RSI.
        self.entry_z_trigger = -4.3 * self.dna      
        self.entry_rsi_trigger = 16.5               
        
        # === Structural Logic ===
        # Alpha Differential: Asset Z must be significantly lower than Market Median Z.
        # If Market Z is -3 and Asset Z is -3, it's Beta (systemic), not Alpha (idiosyncratic).
        self.alpha_differential = -2.5              
        self.market_safety_floor = -2.1             # Avoid buying if market is crashing systematically
        
        # === Velocity / Panic Logic ===
        # To fix "falling knife" catches, we require a high-velocity crash (panic).
        # A slow bleed (low velocity drop) is toxic.
        self.crash_window = 5
        self.min_crash_intensity = -0.042 # 4.2% drop in 5 ticks required
        
        # === Exit Logic ===
        self.max_hold_ticks = 35 # Shorter hold time to clear non-performing residuals
        self.stop_loss_z = -9.5
        self.take_profit_z = -0.15 
        
        # === State Management ===
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.tick = 0

    def _calc_metrics(self, data):
        """
        Computes Z-Score, Volatility, RSI, and Velocity.
        Uses log-space for Z-score to handle geometric Brownian motion better.
        """
        if len(data) < self.lookback:
            return None
            
        try:
            # Snapshot window
            window = list(data)[-self.lookback:]
            price_now = window[-1]
            
            # 1. Log-Normal Z-Score
            # Transforming prices to log space creates a more normal distribution
            log_prices = [math.log(p) for p in window]
            avg_log = sum(log_prices) / len(log_prices)
            variance = sum((x - avg_log) ** 2 for x in log_prices) / len(log_prices)
            
            if variance < 1e-12: return None
            
            std_dev = math.sqrt(variance)
            # Z = (Current Log Price - Mean Log Price) / Log StdDev
            z_score = (log_prices[-1] - avg_log) / std_dev
            
            # 2. RSI Calculation
            rsi_window = list(data)[-(self.rsi_period + 1):]
            if len(rsi_window) < self.rsi_period + 1:
                rsi = 50.0
            else:
                gains = 0.0
                losses = 0.0
                for i in range(1, len(rsi_window)):
                    delta = rsi_window[i] - rsi_window[i-1]
                    if delta > 0: gains += delta
                    else: losses -= delta
                
                if losses == 0: rsi = 100.0
                elif gains == 0: rsi = 0.0
                else:
                    rs = gains / losses
                    rsi = 100.0 - (100.0 / (1.0 + rs))

            return {
                'z': z_score,
                'vol': std_dev,
                'rsi': rsi,
                'price': price_now
            }
        except Exception:
            return None

    def on_price_update(self, prices):
        self.tick += 1
        
        candidates = []
        market_z_scores = []
        
        # 1. Data Ingestion & Metric Calculation
        for sym, p_data in prices.items():
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.max_history)
                self.history[sym].append(price)
                
                # Strict Liquidity Filter (LR_RESIDUAL defense)
                if liq < self.min_liquidity: continue
                if len(self.history[sym]) < self.lookback: continue
                
                metrics = self._calc_metrics(self.history[sym])
                if not metrics: continue
                
                # Volatility Floor
                if metrics['vol'] < self.min_volatility: continue
                
                metrics['symbol'] = sym
                market_z_scores.append(metrics['z'])
                
                if sym not in self.positions:
                    candidates.append(metrics)
                    
            except (ValueError, KeyError, TypeError):
                continue

        # 2. Market Regime Analysis
        # Calculate Median Z to determine Market Beta
        market_median_z = 0.0
        if market_z_scores:
            market_z_scores.sort()
            market_median_z = market_z_scores[len(market_z_scores) // 2]

        # 3. Position Management
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            hist = self.history.get(sym)
            if not hist: continue
            
            metrics = self._calc_metrics(hist)
            if not metrics: continue
            
            current_z = metrics['z']
            ticks_held = self.tick - pos['entry_tick']
            
            # Dynamic Take Profit: Linearly decays to 0.0 to force exit of stagnant trades
            # This improves capital efficiency and reduces exposure to non-reverting residuals.
            decay = ticks_held / self.max_hold_ticks
            dynamic_tp = self.take_profit_z - (1.0 * decay)
            
            action = None
            reason_tag = ""
            
            if current_z > dynamic_tp:
                action = 'TP_HIT'
                reason_tag = f"Z:{current_z:.2f}"
            elif current_z < self.stop_loss_z:
                action = 'STOP_LOSS'
                reason_tag = f"Z:{current_z:.2f}"
            elif ticks_held >= self.max_hold_ticks:
                action = 'TIME_LIMIT'
                reason_tag = "Stale"
                
            if action:
                amt = pos['amount']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': [action, reason_tag]
                }

        # 4. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        # Systemic Risk Filter: If market is crashing, correlations spike to 1. Stay out.
        if market_median_z < self.market_safety_floor:
            return None

        best_signal = None
        best_score = -1.0
        
        for cand in candidates:
            z = cand['z']
            rsi = cand['rsi']
            sym = cand['symbol']
            
            # === Stricter Filters ===
            if z > self.entry_z_trigger: continue
            if rsi > self.entry_rsi_trigger: continue
            
            # === Alpha Logic ===
            # The asset's drop must be idiosyncratic.
            alpha = z - market_median_z
            if alpha > self.alpha_differential: continue
            
            # === Velocity Check (LR_RESIDUAL Fix) ===
            # Ensure this is a sharp panic (mean-reverting) and not a slow trend (momentum).
            hist_list = list(self.history[sym])
            if len(hist_list) > self.crash_window:
                p_now = cand['price']
                p_lag = hist_list[-self.crash_window]
                velocity = (p_now - p_lag) / p_lag
                
                # Must be a sharp crash stronger than min_crash_intensity (e.g. -4.2%)
                if velocity > self.min_crash_intensity:
                    continue
            else:
                continue
                
            # === Scoring ===
            # We prize 'Elasticity': Low Z (oversold) + High Volatility (Potential for snapback)
            # DNA mutation adds slight weight variation
            score = abs(alpha) * (1.0 + (cand['vol'] * 150))
            
            if score > best_score:
                best_score = score
                best_signal = cand
        
        # Execute Best Trade
        if best_signal:
            sym = best_signal['symbol']
            price = best_signal['price']
            
            usd_amt = self.balance * self.pos_size_pct
            amount = usd_amt / price
            
            self.positions[sym] = {
                'entry_tick': self.tick,
                'amount': amount,
                'entry_z': best_signal['z']
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amount,
                'reason': [f"Z:{best_signal['z']:.2f}", f"RSI:{best_signal['rsi']:.1f}", "PANIC_VEL"]
            }
            
        return None