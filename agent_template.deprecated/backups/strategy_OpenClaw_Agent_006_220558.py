import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Mutation ===
        # DNA modifies lookback and thresholds to desynchronize from Hive Mind.
        # Shifted range to favor slightly slower, more robust signals.
        self.dna = random.uniform(0.90, 1.10)
        
        # === Core Parameters ===
        # Longer lookback to filter out high-frequency noise and improve signal quality.
        self.lookback = int(60 * self.dna) 
        self.rsi_period = 14
        self.max_history = self.lookback + self.rsi_period + 10
        
        # === Risk Management ===
        self.balance = 10000.0
        self.max_positions = 5
        self.pos_size_pct = 0.18 # slightly reduced to account for higher volatility targeting
        
        # === Filters ===
        # Increased liquidity to ensure we aren't trading slippage-heavy assets.
        self.min_liquidity = 12_000_000.0
        # Increased volatility floor to avoid 'LR_RESIDUAL' traps (drifting assets that don't mean revert).
        self.min_volatility = 0.0008 * self.dna 
        
        # === Entry Thresholds (Fixing Z:-3.93) ===
        # The penalty suggests -2.8 was too shallow or the previous -3.93 trades failed.
        # We enforce a strictly deeper floor and significantly lower RSI (oversold).
        self.entry_z_trigger = -3.15 * self.dna     # Deep value only
        self.entry_rsi_trigger = 24.0               # Extreme fear only
        self.alpha_threshold = -2.0                 # Must be strictly weaker than market
        self.market_panic_z = -2.2                  # Stricter circuit breaker
        
        # === Velocity Filter (Fixing LR_RESIDUAL) ===
        # We only want to buy 'Fast' crashes (liquidity gaps) which revert.
        # Slow bleeds (fundamental repricing) are filtered out.
        self.min_crash_velocity = -0.015  # Price must drop 1.5% in the window to be valid
        
        # === Exit Logic ===
        self.max_hold_ticks = 60
        self.stop_loss_z = -7.5 # Wider stop for deeper entries
        
        # === State ===
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.tick = 0

    def _calc_stats(self, data):
        """
        Calculates robust Z-Score, Volatility, and RSI.
        """
        if len(data) < self.lookback:
            return None
            
        try:
            window = list(data)[-self.lookback:]
            
            # Log-Returns for Z-Score (Normalization)
            log_prices = [math.log(p) for p in window]
            mean_log = sum(log_prices) / len(log_prices)
            variance = sum((x - mean_log) ** 2 for x in log_prices) / len(log_prices)
            
            if variance < 1e-12: 
                return None
            
            std_dev = math.sqrt(variance)
            current_log_price = log_prices[-1]
            z_score = (current_log_price - mean_log) / std_dev
            
            # RSI Calculation
            rsi_window = list(data)[-(self.rsi_period + 1):]
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
                'vol': std_dev,
                'rsi': rsi,
                'price': window[-1]
            }
            
        except Exception:
            return None

    def on_price_update(self, prices):
        self.tick += 1
        
        market_stats = []
        valid_candidates = []
        
        # 1. Update History & Calculate Stats
        for sym, p_data in prices.items():
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.max_history)
                self.history[sym].append(price)
                
                if liq < self.min_liquidity: continue
                if len(self.history[sym]) < self.lookback: continue
                
                stats = self._calc_stats(self.history[sym])
                if not stats: continue
                
                if stats['vol'] < self.min_volatility: continue
                
                stats['symbol'] = sym
                market_stats.append(stats)
                
                if sym not in self.positions:
                    valid_candidates.append(stats)
                    
            except (KeyError, ValueError, TypeError):
                continue

        # 2. Market Regime (Beta)
        market_z_values = [s['z'] for s in market_stats]
        market_median_z = 0.0
        if market_z_values:
            market_z_values.sort()
            market_median_z = market_z_values[len(market_z_values) // 2]

        # 3. Position Management
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            
            hist = self.history.get(sym)
            if not hist: continue
            stats = self._calc_stats(hist)
            if not stats: continue
            
            current_z = stats['z']
            ticks_held = self.tick - pos['entry_tick']
            
            # Dynamic Target
            decay_ratio = min(1.0, ticks_held / self.max_hold_ticks)
            # Target relaxes from 0.0 (Mean) to -2.0 over time
            target_z = 0.0 - (2.0 * decay_ratio)
            
            action = None
            reason = []
            
            if current_z > target_z:
                action = 'TP_DYNAMIC'
                reason = [f"Z:{current_z:.2f}"]
            elif current_z < self.stop_loss_z:
                action = 'STOP_LOSS'
            elif ticks_held >= self.max_hold_ticks:
                action = 'TIME_LIMIT'
            
            if action:
                amt = pos['amount']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': [action] + reason
                }

        # 4. Entry Logic (Mutated for Stricter Dip Buying)
        if len(self.positions) >= self.max_positions:
            return None
            
        if market_median_z < self.market_panic_z:
            return None
            
        best_signal = None
        best_score = 0.0
        
        for cand in valid_candidates:
            z = cand['z']
            rsi = cand['rsi']
            sym = cand['symbol']
            
            # STICTER CHECKS (Fixing Z:-3.93)
            if z > self.entry_z_trigger: continue
            if rsi > self.entry_rsi_trigger: continue
            
            # Alpha Check
            alpha_z = z - market_median_z
            if alpha_z > self.alpha_threshold: continue
            
            # VELOCITY FILTER (Fixing LR_RESIDUAL)
            # Ensure the drop is sharp (high momentum) rather than a slow bleed.
            # Slow bleeds usually indicate fundamental weakness (LR Residual drift).
            # We check the return over the last 5 ticks.
            hist_list = list(self.history[sym])
            if len(hist_list) > 6:
                price_now = cand['price']
                price_lag = hist_list[-6]
                pct_change_window = (price_now - price_lag) / price_lag
                
                # If price hasn't dropped sharply (e.g. > 1.5% drop), ignore.
                # A Z-score of -3.5 with only a 0.5% drop implies extremely low volatility 
                # or a very long slow grind. Both are traps.
                if pct_change_window > self.min_crash_velocity:
                    continue
            
            # Score: Favor high alpha intensity scaled by volatility
            signal_score = abs(alpha_z) * (1.0 + cand['vol'] * 50)
            
            if signal_score > best_score:
                best_score = signal_score
                best_signal = cand
        
        if best_signal:
            sym = best_signal['symbol']
            price = best_signal['price']
            
            usd_alloc = self.balance * self.pos_size_pct
            amount = usd_alloc / price
            
            self.positions[sym] = {
                'entry_tick': self.tick,
                'amount': amount,
                'entry_z': best_signal['z']
            }
            
            return {
                'side': 'BUY',
                'symbol': sym,
                'amount': amount,
                'reason': ['ALPHA_SHOCK', f"Z:{best_signal['z']:.2f}", f"RSI:{best_signal['rsi']:.1f}"]
            }
            
        return None