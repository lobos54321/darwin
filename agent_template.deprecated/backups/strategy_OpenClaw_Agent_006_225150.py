import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Slight randomization to prevent swarm homogenization
        self.dna = random.uniform(0.95, 1.05)
        
        # === Time Windows ===
        self.lookback = 60               # Base window for Z-score
        self.rsi_period = 14
        self.cleanup_window = 100        # History management
        
        # === Risk Management & Allocation ===
        self.balance = 10000.0
        self.max_positions = 5
        self.pos_size_pct = 0.19         # 19% per trade to leave buffer
        
        # === Filters (Addressing LR_RESIDUAL) ===
        # Increased liquidity floor to ensure price discovery is efficient.
        # Assets with low liquidity often exhibit 'fake' mean reversion or sticky residuals.
        self.min_liquidity = 22_000_000.0  
        
        # Min Turnover (Vol/Liq) to ensure the asset is active
        self.min_turnover = 0.02
        
        # === Entry Thresholds (Addressing Z:-3.93) ===
        # The Hive Mind penalized -3.93 triggers. We push deeper into the tail.
        # We demand a statistical event < -4.6 sigma (approx 1 in 300,000 events in normal distrib, 
        # but crypto is leptokurtic so this is just a "panic" level).
        self.entry_z_trigger = -4.65 * self.dna
        self.entry_rsi_trigger = 13.5
        
        # === Market Logic ===
        # If the median crypto asset is crashing, correlations approach 1.0.
        # We lower the safety floor to avoid catching falling knives during systemic collapses.
        self.market_safety_floor = -2.5
        
        # === Exit Logic ===
        self.take_profit_z = 0.0         # Revert to mean
        self.stop_loss_z = -10.0         # Catastrophic failure guard
        self.max_hold_ticks = 40         # Time-based stop to free capital
        
        # === State ===
        self.history = {}      # symbol -> deque
        self.positions = {}    # symbol -> dict
        self.tick = 0

    def _get_metrics(self, prices_list):
        if len(prices_list) < self.lookback:
            return None
            
        # Optimization: Slicing creates a copy, do it once
        window = list(prices_list)[-self.lookback:]
        current_price = window[-1]
        
        # 1. Log-Returns Z-Score (Robust to geometric motion)
        try:
            log_prices = [math.log(p) for p in window]
            mean_log = sum(log_prices) / len(log_prices)
            
            # Variance calculation
            variance = sum((x - mean_log) ** 2 for x in log_prices) / len(log_prices)
            
            if variance < 1e-12: 
                return None # Flatline
                
            std_dev = math.sqrt(variance)
            z_score = (log_prices[-1] - mean_log) / std_dev
        except ValueError:
            return None

        # 2. RSI (Wilder's Smoothing)
        # Using a slice for RSI calculation
        rsi_window = list(prices_list)[-(self.rsi_period + 1):]
        if len(rsi_window) < self.rsi_period + 1:
            rsi = 50.0
        else:
            gains = 0.0
            losses = 0.0
            for i in range(1, len(rsi_window)):
                change = rsi_window[i] - rsi_window[i-1]
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
                
        return {
            'z': z_score,
            'rsi': rsi,
            'vol': std_dev,
            'price': current_price
        }

    def on_price_update(self, prices):
        self.tick += 1
        
        # 1. Ingest Data & Calculate Market State
        candidates = []
        market_z_values = []
        
        for sym, data in prices.items():
            try:
                p = float(data['priceUsd'])
                liq = float(data['liquidity'])
                vol24 = float(data['volume24h'])
            except (KeyError, ValueError, TypeError):
                continue
                
            # Filter: Liquidity & Activity (Fixing LR_RESIDUAL)
            if liq < self.min_liquidity:
                continue
                
            # Avoid zombie chains
            if liq > 0 and (vol24 / liq) < self.min_turnover:
                continue

            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.cleanup_window)
            self.history[sym].append(p)
            
            # Need full lookback for valid Z-score
            if len(self.history[sym]) < self.lookback:
                continue
                
            metrics = self._get_metrics(self.history[sym])
            if not metrics:
                continue
                
            metrics['symbol'] = sym
            metrics['liquidity'] = liq
            
            # Collect for Market Analysis
            market_z_values.append(metrics['z'])
            
            # If not in position, consider for entry
            if sym not in self.positions:
                candidates.append(metrics)

        # 2. Market Regime Check
        market_median_z = 0.0
        if market_z_values:
            market_z_values.sort()
            market_median_z = market_z_values[len(market_z_values) // 2]

        # 3. Position Management (Exits)
        # Iterate copy of keys to modify dict safely
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            hist = self.history.get(sym)
            if not hist: continue
            
            metrics = self._get_metrics(hist)
            if not metrics: continue
            
            current_z = metrics['z']
            ticks_held = self.tick - pos['entry_tick']
            
            action = None
            reason = ""
            
            # Dynamic Time Decay on Take Profit
            # If we hold too long, accept a smaller profit to free capital
            decay = (ticks_held / self.max_hold_ticks) * 0.5
            effective_tp = self.take_profit_z - decay
            
            if current_z > effective_tp:
                action = 'SELL'
                reason = "TP_HIT"
            elif current_z < self.stop_loss_z:
                action = 'SELL'
                reason = "STOP_LOSS"
            elif ticks_held >= self.max_hold_ticks:
                action = 'SELL'
                reason = "TIMEOUT"
                
            if action:
                amt = pos['amount']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': [reason, f"Z:{current_z:.2f}"]
                }

        # 4. Entry Logic (Aggressive Filtering)
        if len(self.positions) >= self.max_positions:
            return None
            
        # Systemic Risk Filter: Don't buy if the whole market is collapsing
        if market_median_z < self.market_safety_floor:
            return None

        # Filter and Score Candidates
        best_candidate = None
        best_score = -float('inf')
        
        for cand in candidates:
            z = cand['z']
            rsi = cand['rsi']
            
            # === Stricter Entry Filters (Fixing Z:-3.93) ===
            # Must be a deeper anomaly than previous penalized logic
            if z > self.entry_z_trigger:
                continue
                
            if rsi > self.entry_rsi_trigger:
                continue
                
            # Alpha check: The asset must be significantly weaker than the market median
            # We want idiosyncratic failure, not beta failure.
            if z > (market_median_z - 2.0):
                continue
                
            # === Scoring Mutation ===
            # Prioritize high liquidity (safety) and extreme deviation (opportunity)
            # Log liquidity weighting helps favor major pairs over alts slightly
            liq_score = math.log(cand['liquidity']) if cand['liquidity'] > 0 else 0
            
            # Score = Deviation * LiquidityWeight * Volatility
            # We want volatile assets that have snapped (mean reversion potential)
            score = abs(z) * liq_score * (1 + cand['vol']*10)
            
            if score > best_score:
                best_score = score
                best_candidate = cand
        
        # Execute Trade
        if best_candidate:
            sym = best_candidate['symbol']
            price = best_candidate['price']
            
            usd_size = self.balance * self.pos_size_pct
            amount = usd_size / price
            
            self.positions[sym] = {
                'entry_tick': self.tick,
                'amount': amount,
                'entry_z': best_candidate['z']
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amount,
                'reason': ['DIP_ENTRY', f"Z:{best_candidate['z']:.2f}"]
            }

        return None