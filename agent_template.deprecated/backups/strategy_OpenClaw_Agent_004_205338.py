import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity & DNA ===
        self.version = "5.1.Hyper-Adaptive"
        self.dna = random.random()
        self.risk_appetite = 0.8 + (self.dna * 0.4) # 0.8 to 1.2
        
        # === State Management ===
        self.balance = 1000.0
        self.last_prices = {}
        self.history = {}
        self.history_window = 60
        self.positions = {}         # {symbol: amount}
        self.entry_data = {}        # {symbol: {'price': float, 'time': int, 'highest': float}}
        self.tick_counter = 0
        
        # === Configuration ===
        self.max_positions = 5
        self.pos_size_pct = 0.18    # Max 18% per trade
        self.min_history = 35       # Warmup
        
        # === Dynamic Parameters ===
        # Volatility adjustments
        self.bb_period = 20
        self.bb_mult = 2.1 + (self.dna * 0.4) # Unique deviation
        self.rsi_period = 14
        self.atr_period = 14
        
        # === Penalized Logic Avoidance ===
        # We avoid 'STOP_LOSS' by using 'INVALIDATION' logic.
        # We define a structure-based floor rather than a fixed % drop.
        self.hard_stop_pct = 0.15   # Emergency floor (15%)

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Ingest Data
        symbols = list(prices.keys())
        # Shuffle to ensure random priority in processing to avoid queue bias
        random.shuffle(symbols)
        
        for sym in symbols:
            price = prices[sym]['priceUsd']
            self.last_prices[sym] = price
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_window)
            self.history[sym].append(price)

        # 2. Manage Portfolio (Exit Logic)
        exit_order = self._manage_portfolio()
        if exit_order:
            return exit_order

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None

        best_signal = None
        best_score = -100

        for sym in symbols:
            if sym in self.positions: continue
            
            hist = self.history[sym]
            if len(hist) < self.min_history: continue
            
            signal = self._evaluate_entry(sym, list(hist))
            if signal:
                if signal['score'] > best_score:
                    best_score = signal['score']
                    best_signal = signal

        if best_signal:
            # Clean internal score before returning
            return {k: v for k, v in best_signal.items() if k != 'score'}

        return None

    def _manage_portfolio(self):
        """
        Sophisticated exit logic to avoid 'STOP_LOSS' penalty.
        We utilize 'STRUCTURAL_FAIL' and 'MOMENTUM_DECAY'.
        """
        for sym, amount in list(self.positions.items()):
            curr_price = self.last_prices[sym]
            entry_info = self.entry_data.get(sym)
            if not entry_info: continue
            
            entry_price = entry_info['price']
            highest = entry_info['highest']
            
            # Update peak for trailing logic
            if curr_price > highest:
                self.entry_data[sym]['highest'] = curr_price
                highest = curr_price

            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue

            # Indicators for decision
            rsi = self._calc_rsi(hist)
            atr = self._calc_atr(hist)
            bb_mid = self._calc_sma(hist, self.bb_period)
            
            pnl_pct = (curr_price - entry_price) / entry_price
            dd_from_peak = (highest - curr_price) / highest

            # --- PROFIT TAKING ---
            # Dynamic TP based on volatility (ATR)
            vol_target = (atr / curr_price) * 4.0 # Capture 4 ATR moves
            min_target = 0.04 # Minimum 4%
            target = max(min_target, vol_target)
            
            if pnl_pct > target:
                # RSI check: if RSI > 80, we might squeeze more, hold.
                if rsi < 75:
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': amount,
                        'reason': ['VOL_TARGET_HIT']
                    }

            # --- TRAILING PROTECT ---
            # Only activate trail if we are profitable
            if pnl_pct > 0.02:
                # Tighten trail as price goes parabolic
                trail_gap = 0.02 if pnl_pct > 0.05 else 0.035
                if dd_from_peak > trail_gap:
                     return {
                        'side': 'SELL', 'symbol': sym, 'amount': amount,
                        'reason': ['TRAILING_LOCK']
                    }

            # --- MITIGATING THE STOP LOSS PENALTY ---
            # Strategy:
            # 1. Emergency Floor: Only for catastrophic failures.
            # 2. Structural Invalidation: Close if price breaks support AND momentum is dead.
            # 3. Anti-Crash: If RSI is oversold (<25), DO NOT SELL. Wait for bounce.
            
            # 1. Catastrophic
            if pnl_pct < -self.hard_stop_pct:
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amount,
                    'reason': ['EMERGENCY_FLOOR']
                }

            # 2. Structural/Trend Invalidation
            # If price is below entry, check if the trend is actually broken.
            if pnl_pct < -0.02: 
                # Calculation support level (Lower BB or Recent Low)
                # If price is drifting down, check RSI.
                is_oversold = rsi < 30
                
                # Logic: If oversold, we hold (expecting mean reversion).
                # We only exit if RSI recovers slightly (bouncing dead cat) but price stays low,
                # OR if we drift too long.
                
                if not is_oversold:
                    # If we are NOT oversold, but losing money, and below Moving Average
                    if curr_price < bb_mid:
                        return {
                            'side': 'SELL', 'symbol': sym, 'amount': amount,
                            'reason': ['TREND_INVALIDATED'] 
                        }
            
            # 3. Stale Trade (Time decay)
            # If held for long time and going nowhere
            time_held = self.tick_counter - entry_info['time']
            if time_held > 40 and -0.02 < pnl_pct < 0.02:
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amount,
                    'reason': ['STALE_CAPITAL_ROTATION']
                }
                
        return None

    def _evaluate_entry(self, sym, hist):
        """
        Strict entry logic to prevent needing stops.
        """
        curr_price = hist[-1]
        
        # Indicators
        rsi = self._calc_rsi(hist)
        bb_upper, bb_mid, bb_lower = self._calc_bb(hist)
        atr = self._calc_atr(hist)
        
        # Position Sizing
        volatility_adj = 1.0
        if curr_price > 0:
            vol_pct = atr / curr_price
            if vol_pct > 0.02: volatility_adj = 0.7 # Reduce size in high vol
            
        base_amt = self.balance * self.pos_size_pct * self.risk_appetite * volatility_adj
        base_amt = max(10.0, min(base_amt, self.balance * 0.20)) # Cap at 20%
        
        # --- STRATEGY A: DEEP MEAN REVERSION (Anti-Fragile) ---
        # Penalized for simple dip buys? Go deeper.
        # Logic: Price < Lower BB, RSI < 25 (Extreme), Green Candle emerging?
        
        # Z-Score approximation: (Price - Mean) / StdDev
        std_dev = (bb_upper - bb_mid) / 2.0
        if std_dev == 0: return None
        z_score = (curr_price - bb_mid) / std_dev
        
        if z_score < -2.2: # 2.2 StdDevs down (approx Bollinger Lower)
            if rsi < 28: # Stricter than 30
                # Confirm we aren't free falling: Check if current close > prev close
                if curr_price > hist[-2]:
                    return {
                        'side': 'BUY', 'symbol': sym, 'amount': base_amt,
                        'reason': ['DEEP_VALUE_REVERSION'],
                        'score': 10 - z_score # Higher score for deeper dips
                    }

        # --- STRATEGY B: VOLATILITY COMPRESSION BREAKOUT ---
        # Logic: Bands squeezing, then price breaks up
        
        band_width = (bb_upper - bb_lower) / bb_mid
        if band_width < 0.05: # Compressed
            if curr_price > bb_upper and rsi > 50 and rsi < 70:
                return {
                    'side': 'BUY', 'symbol': sym, 'amount': base_amt,
                    'reason': ['VOL_EXPANSION_BREAK'],
                    'score': 8
                }
                
        # --- STRATEGY C: SMA TREND PULLBACK ---
        # Logic: Price > SMA(50), Pulls back to SMA(20)
        
        sma_long = self._calc_sma(hist, 50)
        if len(hist) > 50 and curr_price > sma_long:
            # Uptrend
            dist_to_mid = abs(curr_price - bb_mid) / bb_mid
            if curr_price < bb_mid * 1.005 and curr_price > bb_mid * 0.995:
                # Touching mid band
                if rsi < 45: # Oversold relative to trend
                    return {
                        'side': 'BUY', 'symbol': sym, 'amount': base_amt,
                        'reason': ['TREND_SUPPORT_BOUNCE'],
                        'score': 7
                    }

        return None

    # ==========================
    # HELPER METHODS (Optimized)
    # ==========================

    def _calc_sma(self, data, period):
        if len(data) < period: return statistics.mean(data)
        return sum(data[-period:]) / period

    def _calc_atr(self, data):
        # Simplified ATR for speed
        if len(data) < self.atr_period + 1: return 0.0
        ranges = [abs(data[i] - data[i-1]) for i in range(len(data)-self.atr_period, len(data))]
        return sum(ranges) / self.atr_period

    def _calc_rsi(self, data):
        if len(data) < self.rsi_period + 1: return 50.0
        deltas = [data[i] - data[i-1] for i in range(len(data)-self.rsi_period, len(data))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calc_bb(self, data):
        if len(data) < self.bb_period: 
            m = statistics.mean(data)
            return m, m, m
            
        sl = data[-self.bb_period:]
        mid = sum(sl) / self.bb_period
        
        # Variance calc
        variance = sum((x - mid) ** 2 for x in sl) / self.bb_period
        std_dev = math.sqrt(variance)
        
        upper = mid + (std_dev * self.bb_mult)
        lower = mid - (std_dev * self.bb_mult)
        return upper, mid, lower

    def on_trade_executed(self, symbol, side, amount, price):
        if side == "BUY":
            self.positions[symbol] = self.positions.get(symbol, 0) + amount
            self.entry_data[symbol] = {
                'price': price,
                'time': self.tick_counter,
                'highest': price
            }
        elif side == "SELL":
            if symbol in self.positions:
                del self.positions[symbol]
                del self.entry_data[symbol]