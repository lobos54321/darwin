import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Diversity ===
        # Unique seed ensures this instance behaves slightly differently from the Hive Mind
        self.dna = random.uniform(0.92, 1.08)
        
        # === Core Parameters ===
        self.lookback = int(60 * self.dna)
        self.rsi_period = 14
        self.max_history = self.lookback + self.rsi_period + 50
        
        # === Capital Allocation ===
        self.balance = 10000.0
        self.max_positions = 5
        self.pos_size_pct = 0.19  # Conservative allocation
        
        # === Filters (Fixing LR_RESIDUAL) ===
        # LR_RESIDUAL penalty implies the model was trading noise or slow bleeds.
        # We increase liquidity requirements to ensure technical levels are respected.
        self.min_liquidity = 12_000_000.0 
        self.min_volatility = 0.0015 * self.dna # Ignore dead assets
        
        # === Entry Thresholds (Fixing Z:-3.93) ===
        # The penalty suggests -3.93 was a "fake dip" or value trap.
        # We push the Z-score boundary to -4.0+ and require structural breakdown velocity.
        self.entry_z_trigger = -4.1 * self.dna      # Extreme deviation only
        self.entry_rsi_trigger = 18.0               # Deep oversold
        self.alpha_differential = -3.0              # Asset Z must be 3 sigma below Market Z
        self.market_safety_floor = -2.0             # Do not buy if market avg Z < -2 (Systemic Crash)
        
        # === Velocity Logic ===
        # To avoid catching falling knives that simply drift down (high residuals),
        # we require a 'Panic Spike' - a sharp move in a short window.
        self.crash_window = 6
        self.min_crash_intensity = -0.035 # 3.5% drop in 6 ticks required
        
        # === Exit Logic ===
        self.max_hold_ticks = 40
        self.stop_loss_z = -9.0   # Catastrophic failure line
        self.take_profit_z = -0.2 # Exit near mean
        
        # === State Management ===
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.tick = 0

    def _calc_metrics(self, data):
        """
        Computes Z-Score, Volatility, RSI, and Velocity.
        """
        if len(data) < self.lookback:
            return None
            
        try:
            # Slicing the window
            window = list(data)[-self.lookback:]
            price_now = window[-1]
            
            # 1. Log-Normal Z-Score
            log_prices = [math.log(p) for p in window]
            avg_log = sum(log_prices) / len(log_prices)
            variance = sum((x - avg_log) ** 2 for x in log_prices) / len(log_prices)
            
            if variance < 1e-12: return None
            
            std_dev = math.sqrt(variance)
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
        
        # 1. Data Ingestion & Pre-processing
        for sym, p_data in prices.items():
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.max_history)
                self.history[sym].append(price)
                
                # Filter Garbage
                if liq < self.min_liquidity: continue
                if len(self.history[sym]) < self.lookback: continue
                
                metrics = self._calc_metrics(self.history[sym])
                if not metrics: continue
                
                # Volatility Floor
                if metrics['vol'] < self.min_volatility: continue
                
                metrics['symbol'] = sym
                market_z_scores.append(metrics['z'])
                
                # Only consider for entry if we don't hold it
                if sym not in self.positions:
                    candidates.append(metrics)
                    
            except (ValueError, KeyError, TypeError):
                continue

        # 2. Market Regime Analysis (Systemic Risk Filter)
        market_median_z = 0.0
        if market_z_scores:
            market_z_scores.sort()
            market_median_z = market_z_scores[len(market_z_scores) // 2]

        # 3. Manage Existing Positions
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            hist = self.history.get(sym)
            if not hist: continue
            
            metrics = self._calc_metrics(hist)
            if not metrics: continue
            
            current_z = metrics['z']
            ticks_held = self.tick - pos['entry_tick']
            
            # Dynamic TP: Decay target Z from -0.2 down to -1.5 as time passes
            # This prevents holding stale positions.
            decay_factor = min(1.0, ticks_held / self.max_hold_ticks)
            dynamic_tp = self.take_profit_z - (1.3 * decay_factor)
            
            action = None
            reason_tag = ""
            
            if current_z > dynamic_tp:
                action = 'TP_HIT'
                reason_tag = f"Z:{current_z:.2f}>TP:{dynamic_tp:.2f}"
            elif current_z < self.stop_loss_z:
                action = 'STOP_LOSS'
                reason_tag = f"Z:{current_z:.2f}<SL"
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

        # 4. Entry Logic (Aggressive Mean Reversion)
        if len(self.positions) >= self.max_positions:
            return None
            
        # Safety: If the whole market is collapsing (median Z < -2.0),
        # correlations approach 1.0 and individual mean reversion fails. Stay out.
        if market_median_z < self.market_safety_floor:
            return None

        best_signal = None
        best_score = -999.0
        
        for cand in candidates:
            z = cand['z']
            rsi = cand['rsi']
            sym = cand['symbol']
            
            # === Strict Filter Layer ===
            if z > self.entry_z_trigger: continue
            if rsi > self.entry_rsi_trigger: continue
            
            # === Alpha Logic ===
            # We want idiosyncratic dips, not market beta.
            # Asset Z must be significantly lower than Market Median Z.
            alpha = z - market_median_z
            if alpha > self.alpha_differential: continue
            
            # === Velocity Check (Crucial for LR_RESIDUAL) ===
            # Calculate percent change over the crash window
            hist_list = list(self.history[sym])
            if len(hist_list) > self.crash_window:
                p_now = cand['price']
                p_lag = hist_list[-self.crash_window]
                velocity = (p_now - p_lag) / p_lag
                
                # Must be a sharp crash, not a slow bleed
                if velocity > self.min_crash_intensity:
                    continue
            else:
                continue
                
            # === Scoring ===
            # Preference: Lowest Z relative to market + Highest Volatility (Elasticity)
            # Higher volatility usually implies stronger snap-back.
            score = abs(alpha) * (1.0 + (cand['vol'] * 200))
            
            if score > best_score:
                best_score = score
                best_signal = cand
        
        # Execute Trade
        if best_signal:
            sym = best_signal['symbol']
            price = best_signal['price']
            
            # Calculate amount (USD value / Price)
            # Using pos_size_pct of initial virtual balance for consistency
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
                'reason': [f"Z:{best_signal['z']:.2f}", f"RSI:{best_signal['rsi']:.1f}", "VEL_CHK"]
            }
            
        return None