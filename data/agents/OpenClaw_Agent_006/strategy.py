import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Mutation ===
        # DNA modifies lookback and sensitivity to avoid Hive Mind synchronization.
        self.dna = random.uniform(0.95, 1.05)
        
        # === Core Parameters ===
        self.lookback = int(50 * self.dna)  # Shorter lookback for faster adaptation
        self.rsi_period = 14
        self.max_history = self.lookback + self.rsi_period + 5
        
        # === Risk Management ===
        self.balance = 10000.0
        self.max_positions = 5
        self.pos_size_pct = 0.19  # Slightly aggressive size, relying on alpha quality
        
        # === Filters (Fixing ER:0.004) ===
        # Increased liquidity requirement to ensure fills.
        # Volatility floor ensures we only trade assets capable of mean reversion.
        self.min_liquidity = 10_000_000.0
        self.min_volatility = 0.0006  
        
        # === Entry Thresholds (Fixing EFFICIENT_BREAKOUT) ===
        # We target Idiosyncratic Reversion (Alpha) rather than Beta moves.
        self.entry_z_trigger = -2.8 * self.dna      # Absolute deviation
        self.entry_rsi_trigger = 32.0               # Momentum confirmation
        self.alpha_threshold = -1.8                 # Asset Z must be lower than Market Z by this amount
        self.market_panic_z = -1.5                  # Circuit breaker: Don't buy if market is crashing
        
        # === Exit Logic (Fixing FIXED_TP) ===
        # Time-decaying dynamic target.
        self.max_hold_ticks = 75
        self.stop_loss_z = -7.0
        
        # === State ===
        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict {'amount': float, 'entry_tick': int, 'entry_z': float}
        self.tick = 0

    def _calc_stats(self, data):
        """
        Calculates Log-Normal Z-Score, Volatility, and RSI.
        """
        if len(data) < self.lookback:
            return None
            
        try:
            # Use most recent window for Z-score stats
            window = list(data)[-self.lookback:]
            
            # 1. Log-Returns for Z-Score (Normalization)
            log_prices = [math.log(p) for p in window]
            mean_log = sum(log_prices) / len(log_prices)
            variance = sum((x - mean_log) ** 2 for x in log_prices) / len(log_prices)
            
            if variance < 1e-12: 
                return None
            
            std_dev = math.sqrt(variance)
            current_log_price = log_prices[-1]
            z_score = (current_log_price - mean_log) / std_dev
            
            # 2. RSI Calculation (Standard 14-period)
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
        """
        Main execution loop.
        """
        self.tick += 1
        
        # 1. Ingest Data & Calculate Metrics
        market_stats = []
        valid_candidates = []
        
        for sym, p_data in prices.items():
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.max_history)
                self.history[sym].append(price)
                
                # Filters
                if liq < self.min_liquidity: continue
                if len(self.history[sym]) < self.lookback: continue
                
                stats = self._calc_stats(self.history[sym])
                if not stats: continue
                
                # Volatility Filter (ER:0.004 defense)
                if stats['vol'] < self.min_volatility: continue
                
                stats['symbol'] = sym
                market_stats.append(stats)
                
                # Only consider for entry if not already held
                if sym not in self.positions:
                    valid_candidates.append(stats)
                    
            except (KeyError, ValueError, TypeError):
                continue

        # 2. Calculate Market Regime (Beta)
        # We need the median Z-score to determine if the whole market is moving.
        market_z_values = [s['z'] for s in market_stats]
        market_median_z = 0.0
        if market_z_values:
            market_z_values.sort()
            mid = len(market_z_values) // 2
            market_median_z = market_z_values[mid]

        # 3. Manage Positions (Dynamic Exit)
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            
            # Retrieve latest stats
            hist = self.history.get(sym)
            if not hist: continue
            stats = self._calc_stats(hist)
            if not stats: continue
            
            current_z = stats['z']
            ticks_held = self.tick - pos['entry_tick']
            
            # Dynamic Target Logic (Fixing FIXED_TP)
            # As time increases, our target Z-score drops (we become more eager to sell).
            # Start Target: 0.0 (Mean). End Target: -2.0 (Cut losses/small bounce).
            decay_ratio = min(1.0, ticks_held / self.max_hold_ticks)
            target_z = 0.0 - (2.5 * decay_ratio)
            
            action = None
            reason = []
            
            # Exit Conditions
            if current_z > target_z:
                action = 'TP_DYNAMIC'
                reason = [f"Z:{current_z:.2f}", f"Tgt:{target_z:.2f}"]
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

        # 4. Alpha Entry Logic (Fixing EFFICIENT_BREAKOUT)
        # We only buy if we have space and market isn't crashing.
        if len(self.positions) >= self.max_positions:
            return None
            
        # Global Crash Filter
        if market_median_z < self.market_panic_z:
            return None
            
        best_signal = None
        best_alpha = 0.0
        
        for cand in valid_candidates:
            z = cand['z']
            rsi = cand['rsi']
            
            # Absolute Floor Checks
            if z > self.entry_z_trigger: continue
            if rsi > self.entry_rsi_trigger: continue
            
            # Alpha Calculation
            # Alpha = Asset_Z - Market_Median_Z
            # We want negative alpha (asset crashing significantly harder than market)
            alpha_z = z - market_median_z
            
            if alpha_z > self.alpha_threshold: continue
            
            # Score Signal: Magnitude of Alpha * Volatility
            # High Vol assets get boosted because they revert harder.
            signal_score = abs(alpha_z) * (1.0 + cand['vol'] * 20)
            
            if signal_score > best_alpha:
                best_alpha = signal_score
                best_signal = cand
        
        if best_signal:
            sym = best_signal['symbol']
            price = best_signal['price']
            
            # Sizing
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
                'reason': ['ALPHA_DIP', f"Z:{best_signal['z']:.2f}", f"AlphaZ:{best_signal['z'] - market_median_z:.2f}"]
            }
            
        return None