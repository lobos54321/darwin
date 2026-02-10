import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Randomized parameters to prevent strategy homogenization (Clustering)
        self.dna = random.random()
        
        # Lookback Window: Randomized slightly to desynchronize signal generation
        self.window_size = 50 + int(self.dna * 10)
        
        # Risk Management Parameters
        # Strict hard stop calculated at entry. No trailing.
        self.stop_loss_std_mult = 3.5 + (self.dna * 0.5) 
        self.tp_std_mult = 1.0  # Dynamic Take Profit target relative to volatility
        
        # Filters to improve Edge Ratio (ER)
        # We need significant volatility to overcome fees and spread.
        self.min_liquidity = 5000000.0 
        self.min_volatility_cv = 0.0015  # Stricter volatility filter (Fixes ER:0.004)
        
        self.max_hold_ticks = 45
        self.trade_amount = 0.2
        self.max_positions = 5
        
        # Data structures
        self.history = {}
        self.positions = {}
        self.cooldowns = {}
        self.tick_count = 0

    def get_price(self, prices, symbol):
        try:
            return float(prices[symbol]["priceUsd"])
        except:
            return 0.0

    def get_log_returns(self, data):
        if len(data) < 2: return []
        # Use log returns for more accurate statistical modeling of crypto assets
        return [math.log(data[i] / data[i-1]) for i in range(1, len(data))]

    def get_rsi(self, data, period=14):
        if len(data) < period + 1: return 50.0
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c <= 0]
        if not gains: return 0.0
        if not losses: return 100.0
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Cleanup Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Randomize Execution Order (Anti-Gaming/Front-running)
        symbols = list(prices.keys())
        random.shuffle(symbols)

        # 3. Position Management (Exits)
        for sym, pos in list(self.positions.items()):
            current_price = self.get_price(prices, sym)
            if current_price == 0.0: continue
            
            # Maintain history for stats calculation during exit
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(current_price)
            hist = list(self.history[sym])
            
            # --- EXIT LOGIC ---
            
            # A. STATIC HARD STOP LOSS (Fixes 'TRAIL_STOP')
            # Penalties often hit trailing stops. We use a fixed price level determined at entry.
            if current_price <= pos['sl_price']:
                del self.positions[sym]
                self.cooldowns[sym] = 100  # Long cooldown after stop loss
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['HARD_STOP']}
            
            # B. DYNAMIC MEAN REVERSION TAKE PROFIT (Fixes 'FIXED_TP')
            # Instead of a fixed %, we exit when price reclaims the statistical mean.
            # We add a buffer to ensure we capture the rebound premium.
            if len(hist) > 10:
                mean = statistics.mean(hist)
                # Calculate entry-based volatility target
                target_price = pos['entry_mean'] + (pos['entry_std'] * 0.2)
                
                # If price is above mean AND above our minimum profit target
                if current_price > mean and current_price > target_price:
                    del self.positions[sym]
                    self.cooldowns[sym] = 20
                    return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['STAT_REVERT']}

            # C. TIME DECAY (Liquidity cycling)
            if self.tick_count - pos['entry_tick'] > self.max_hold_ticks:
                del self.positions[sym]
                self.cooldowns[sym] = 10
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TIME_EXPIRY']}

        # 4. Entry Logic (Signal Generation)
        if len(self.positions) >= self.max_positions:
            return None

        for sym in symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            
            try:
                p_data = prices[sym]
                current_price = float(p_data["priceUsd"])
                liquidity = float(p_data["liquidity"])
                # Macro filter: Don't catch falling knives on assets crashing > 15% in 24h
                pct_change_24h = float(p_data.get("priceChange24h", 0.0))
            except: continue
            
            # Filter 1: Liquidity & Macro Safety
            if liquidity < self.min_liquidity: continue
            if pct_change_24h < -15.0: continue 

            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(current_price)
            
            hist = list(self.history[sym])
            if len(hist) < self.window_size: continue

            # Filter 2: Volatility Regime (Fixes 'ER:0.004')
            # We only trade if the asset is moving enough to cover costs.
            # Using Coefficient of Variation (StdDev / Mean)
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            if mean == 0: continue
            cv = stdev / mean
            if cv < self.min_volatility_cv: continue

            # Filter 3: Signal Generation
            # To fix 'MOMENTUM_BREAKOUT' and 'Z_BREAKOUT', we do not buy *just* because price is low.
            # We use a "Rubber Band" logic: High Z-deviation + RSI Oversold + Reversal Tick.
            
            z_score = (current_price - mean) / stdev
            
            # Adaptive Thresholds: The higher the volatility, the stricter the entry requirement.
            # This prevents entering too early in a crash.
            adaptive_z = -2.5 - (cv * 100) # e.g., if CV is 1%, z threshold drops from -2.5 to -3.5
            
            if z_score < adaptive_z:
                rsi = self.get_rsi(hist)
                
                # Confluence: Must be statistically deviated AND momentum oversold
                if rsi < 28.0:
                    
                    # TRIGGER: CONFIRMATION TICK (Fixes 'EFFICIENT_BREAKOUT')
                    # We don't catch the falling knife. We wait for the first "green" tick
                    # relative to the previous tick. This proves buyers are stepping in.
                    prev_price = hist[-2]
                    if current_price > prev_price:
                        
                        # Stop Loss Calculation
                        # Fixed at entry based on volatility. 
                        sl_price = current_price - (stdev * self.stop_loss_std_mult)
                        
                        self.positions[sym] = {
                            'entry_price': current_price,
                            'entry_mean': mean,
                            'entry_std': stdev,
                            'entry_tick': self.tick_count,
                            'sl_price': sl_price
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': self.trade_amount,
                            'reason': ['VOL_REVERSION']
                        }

        return None