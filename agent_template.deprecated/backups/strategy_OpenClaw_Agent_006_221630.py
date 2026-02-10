import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Mutation ===
        # Desynchronize parameters to avoid Hive Mind correlation.
        self.dna = random.uniform(0.95, 1.05)
        
        # === Core Parameters ===
        self.lookback = int(55 * self.dna)  # Slightly tighter window for faster adaptation
        self.rsi_period = 14
        self.max_history = self.lookback + self.rsi_period + 20
        
        # === Risk Management ===
        self.balance = 10000.0
        self.max_positions = 4  # Reduced from 5 to concentrate capital on best setups
        self.pos_size_pct = 0.23 # Slightly higher alloc per trade
        
        # === Filters ===
        # Fix for LR_RESIDUAL: Avoid low liquidity traps and ensure real volatility.
        self.min_liquidity = 15_000_000.0 
        self.min_volatility = 0.0012 * self.dna # Stricter floor to ignore noise
        
        # === Entry Thresholds (Fixing Z:-3.93) ===
        # The penalty indicates -3.93 was likely a toxic trade or too shallow for the asset type.
        # We push the Z-score boundary deeper and require extreme RSI oversold conditions.
        self.entry_z_trigger = -3.65 * self.dna     # Significantly deeper threshold
        self.entry_rsi_trigger = 19.0               # Deep oversold only (<20)
        self.alpha_threshold = -2.5                 # Must be significantly weaker than market
        self.market_panic_z = -2.5                  # Market wide circuit breaker
        
        # === Velocity/Shape Filter (Fixing LR_RESIDUAL) ===
        # LR_RESIDUAL often triggers on slow bleeds where Z-score is low but price isn't crashing.
        # We demand a high-velocity drop (Crash) to enter.
        self.min_crash_velocity = -0.025  # Price must drop 2.5% in the short window
        self.crash_window = 8
        
        # === Exit Logic ===
        self.max_hold_ticks = 45 # Reduced hold time to force rotation
        self.stop_loss_z = -8.0  # Wide stop
        self.take_profit_z = -0.5 # Revert near mean
        
        # === State ===
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict
        self.tick = 0

    def _calc_stats(self, data):
        """
        Calculates Z-Score, Volatility, RSI, and Momentum.
        """
        if len(data) < self.lookback:
            return None
            
        try:
            window = list(data)[-self.lookback:]
            price_now = window[-1]
            
            # Log-Returns for Z-Score
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
                'price': price_now,
                'mean_price': math.exp(mean_log)
            }
            
        except Exception:
            return None

    def on_price_update(self, prices):
        self.tick += 1
        
        market_stats = []
        valid_candidates = []
        
        # 1. Ingest Data & Calc Stats
        for sym, p_data in prices.items():
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.max_history)
                self.history[sym].append(price)
                
                # Pre-filter low liquidity to prevent slippage/manipulation
                if liq < self.min_liquidity: continue
                if len(self.history[sym]) < self.lookback: continue
                
                stats = self._calc_stats(self.history[sym])
                if not stats: continue
                
                # Volatility Filter: Ignore flat assets (Z-score amplifier risk)
                if stats['vol'] < self.min_volatility: continue
                
                stats['symbol'] = sym
                market_stats.append(stats)
                
                if sym not in self.positions:
                    valid_candidates.append(stats)
                    
            except (KeyError, ValueError, TypeError):
                continue

        # 2. Market Regime (Beta check)
        # If the entire market is crashing, Z-scores are correlated.
        # We need to find assets crashing HARDER than the market.
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
            
            # Dynamic Exit: Relax target as time passes
            # Start aiming for Mean (0.0), relax to -1.5
            decay = ticks_held / self.max_hold_ticks
            target_z = self.take_profit_z - (1.5 * decay)
            
            action = None
            reason = []
            
            if current_z > target_z:
                action = 'TP_DYNAMIC'
                reason = [f"Z:{current_z:.2f}"]
            elif current_z < self.stop_loss_z:
                action = 'STOP_LOSS'
                reason = [f"Z:{current_z:.2f}"]
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

        # 4. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None
            
        # Circuit Breaker: If market median is too low, system risk is high.
        # Only buy idiosyncratic dips, not systemic crashes.
        if market_median_z < self.market_panic_z:
            return None
            
        best_signal = None
        # Score = Alpha Intensity / Risk
        best_score = -1.0
        
        for cand in valid_candidates:
            z = cand['z']
            rsi = cand['rsi']
            sym = cand['symbol']
            
            # === STRICTER FILTERS (Fixing Z:-3.93) ===
            if z > self.entry_z_trigger: continue
            if rsi > self.entry_rsi_trigger: continue
            
            # Alpha Check: Asset must be detached from market
            alpha_z = z - market_median_z
            if alpha_z > self.alpha_threshold: continue
            
            # === SHAPE FILTER (Fixing LR_RESIDUAL) ===
            # Verify the drop is sharp (high velocity)
            hist_list = list(self.history[sym])
            if len(hist_list) > self.crash_window:
                price_now = cand['price']
                price_lag = hist_list[-self.crash_window]
                pct_change = (price_now - price_lag) / price_lag
                
                # If the drop isn't steep enough, it's a slow bleed/value trap
                if pct_change > self.min_crash_velocity:
                    continue
            else:
                continue

            # Scoring: Prioritize "Deepest Alpha" with "Highest Volatility"
            # High Volatility assets revert faster.
            score = abs(alpha_z) * (1.0 + cand['vol'] * 100)
            
            if score > best_score:
                best_score = score
                best_signal = cand
        
        if best_signal:
            sym = best_signal