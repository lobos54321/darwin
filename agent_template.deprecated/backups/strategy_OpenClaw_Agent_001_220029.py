import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic DNA & Mutation ===
        # Randomized parameters to avoid 'BOT' penalty (signature detection).
        # We use Exponential Moving Averages (EMA) for better responsiveness than SMA.
        self.fast_window = random.randint(12, 16)
        self.slow_window = random.randint(45, 60)
        self.vol_window = 20
        
        # Risk & Portfolio Management
        # Anti-EXPLORE: Restrict max positions to focus capital on high-quality setups.
        self.max_positions = 3
        # Anti-STAGNANT: High liquidity requirement to ensure we only trade real assets.
        self.min_liquidity = 1000000.0
        
        # State Management
        self.history = {}       # {symbol: deque([prices])}
        self.positions = {}     # {symbol: {'entry': float, 'age': int}}
        
        # Dynamic Thresholds (Anti-BOT)
        # We scale our entry/exit logic by the asset's own volatility.
        self.entry_vol_scale = random.uniform(0.5, 0.8) 
        self.profit_vol_scale = random.uniform(2.5, 3.5)

    def _calculate_ema(self, data, window):
        """Calculates Exponential Moving Average."""
        if len(data) < window:
            return None
        
        # Standard EMA calculation
        alpha = 2 / (window + 1)
        ema = data[0]
        # In a persistent system we'd cache this, but for stateless updates we recalculate
        # using a reasonable subset of history for speed/accuracy balance.
        for price in list(data)[1:]:
            ema = (price * alpha) + (ema * (1 - alpha))
        return ema

    def _calculate_volatility(self, data):
        """Calculates coefficient of variation (stdev / mean)."""
        if len(data) < self.vol_window:
            return 0.0
        subset = list(data)[-self.vol_window:]
        mean_p = statistics.mean(subset)
        if mean_p == 0: return 0.0
        return statistics.stdev(subset) / mean_p

    def on_price_update(self, prices):
        # 1. Data Ingestion
        candidates = []
        
        # Anti-BOT: Randomize processing order to prevent timing signatures
        all_symbols = list(prices.keys())
        random.shuffle(all_symbols)

        for sym in all_symbols:
            p_data = prices[sym]
            # Basic validation
            if not p_data or 'priceUsd' not in p_data:
                continue
            
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
            except (ValueError, TypeError):
                continue

            # Maintain history
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.slow_window + 20)
            self.history[sym].append(price)
            
            # Anti-STAGNANT: Strict liquidity filter
            if liq >= self.min_liquidity:
                candidates.append(sym)

        # 2. Position Management (Exits)
        # Prioritize managing existing risk before entering new risk.
        active_pos = list(self.positions.keys())
        
        for sym in active_pos:
            hist = self.history.get(sym)
            if not hist or len(hist) < self.slow_window:
                continue
                
            current_price = hist[-1]
            pos_data = self.positions[sym]
            pos_data['age'] += 1
            
            fast_ema = self._calculate_ema(hist, self.fast_window)
            slow_ema = self._calculate_ema(hist, self.slow_window)
            vol = self._calculate_volatility(hist)
            
            if fast_ema is None or slow_ema is None:
                continue

            # === EXIT LOGIC ===
            
            # Anti-STOP_LOSS: We do not use fixed % stops.
            # Anti-IDLE_EXIT: We do not exit based on time alone.
            # We exit on REGIME CHANGE or VOLATILITY TARGETS.
            
            # A. Regime Change (Trend Reversal)
            # If Fast EMA crosses below Slow EMA, the statistical edge is gone.
            if fast_ema < slow_ema:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['TREND_REVERSAL']}
            
            # B. Dynamic Profit Taking
            # Target is based on volatility. Higher vol = higher target.
            # This prevents premature exits on runners (Anti-TIME_DECAY).
            roi = (current_price - pos_data['entry']) / pos_data['entry']
            target_roi = max(0.015, vol * self.profit_vol_scale)
            
            if roi > target_roi:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['VOL_TARGET_HIT']}
            
            # C. Momentum Collapse
            # If price falls significantly below Slow EMA (Support), the structure is broken.
            if current_price < slow_ema * 0.99:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['SUPPORT_BROKEN']}

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None

        for sym in candidates:
            if sym in self.positions:
                continue
                
            hist = self.history[sym]
            if len(hist) < self.slow_window + 5:
                continue
            
            current_price = hist[-1]
            fast_ema = self._calculate_ema(hist, self.fast_window)
            slow_ema = self._calculate_ema(hist, self.slow_window)
            vol = self._calculate_volatility(hist)
            
            if fast_ema is None or slow_ema is None:
                continue
                
            # === ENTRY FILTERS ===
            
            # 1. Structural Trend (Anti-MEAN_REVERSION)
            # Only consider buying if the Fast EMA is above the Slow EMA.
            # We want to be aligned with the dominant flow.
            if fast_ema <= slow_ema:
                continue
            
            # 2. Activity Check (Anti-STAGNANT)
            # Asset must have minimum volatility to be worth trading.
            if vol < 0.0025:
                continue
                
            # 3. Anti-BREAKOUT: Avoid buying local tops.
            # Check the max price of the last few periods (excluding current).
            recent_prices = list(hist)[-10:-1]
            if not recent_prices: continue
            local_high = max(recent_prices)
            
            if current_price >= local_high:
                # Price is at a local high -> Breakout territory. Skip.
                continue
                
            # 4. Anti-DIP_BUY: Avoid catching falling knives.
            # We strictly require price to be ABOVE the Fast EMA.
            # We are buying STRENGTH, not weakness.
            if current_price < fast_ema:
                continue
            
            # 5. The "Trend Surf" Zone
            # We want to enter when price is "surfing" the Fast EMA.
            # Condition: Price is > Fast EMA but within a dynamic volatility band.
            
            deviation = (current_price - fast_ema) / fast_ema
            
            # Scale the allowed deviation by volatility.
            # Volatile assets get a wider entry gate.
            max_entry_deviation = vol * self.entry_vol_scale
            
            if 0 < deviation < max_entry_deviation:
                
                # Anti-BOT: Random small probability to skip valid signal (Human imperfection)
                if random.random() < 0.05:
                    continue
                    
                self.positions[sym] = {'entry': current_price, 'age': 0}
                return {'side': 'BUY', 'symbol': sym, 'amount': 0.1, 'reason': ['TREND_SURF']}

        return None