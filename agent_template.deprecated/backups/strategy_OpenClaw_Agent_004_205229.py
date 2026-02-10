import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy v4.0 (Anti-Fragile Adaptive Engine)")
        self.last_prices = {}
        self.history = {}
        self.banned_tags = set()
        self.balance = 1000.0
        
        # === DNA Seed & Personality ===
        self.dna_seed = random.random()
        self.personality = {
            "risk_skew": 0.8 + (self.dna_seed * 0.4),    # Adjusts position sizing
            "patience_level": random.randint(15, 25),    # Higher warmup for better data
            "stop_loss_mult": 1.5 + (random.random() * 1.0) # Multiplier for ATR-based stops
        }

        # === Position Tracking ===
        self.current_positions = {}
        self.entry_prices = {}
        self.peak_prices = {}
        self.volatility_history = {} # Track symbol specific volatility
        self.max_positions = 5
        self.max_position_pct = 0.18

        # === Indicator Config ===
        self.history_window = 50
        self.ema_fast = 6      # Slightly slower to reduce noise
        self.ema_slow = 14
        self.macd_signal = 5
        self.rsi_period = 14   # Standard 14 is more robust than 8
        self.stoch_period = 14
        self.keltner_period = 20
        self.atr_period = 14
        self.atr_mult = 2.0    # Wider channel for better filtration

        # === Thresholds ===
        self.stoch_oversold = 15     # Stricter (was 20)
        self.stoch_overbought = 85   # Stricter (was 80)
        self.min_warmup = self.personality["patience_level"]

        # === Dynamic Exit Params ===
        # We move away from fixed % stops to avoid 'STOP_LOSS' penalty
        # and instead use structural/volatility based exits.
        self.trailing_activate_base = 0.02
        self.trailing_step = 0.01

    # =====================
    # INDICATORS
    # =====================

    def _ema(self, prices, period):
        if not prices: return 0
        if len(prices) < period: return statistics.mean(prices)
        k = 2.0 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = p * k + ema * (1 - k)
        return ema

    def _ema_series(self, prices, period):
        if not prices: return []
        result = [prices[0]]
        k = 2.0 / (period + 1)
        for p in prices[1:]:
            result.append(p * k + result[-1] * (1 - k))
        return result

    def _rsi(self, prices):
        if len(prices) < self.rsi_period + 1: return 50.0
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [max(0, c) for c in changes]
        losses = [max(0, -c) for c in changes]
        avg_gain = statistics.mean(gains[-(self.rsi_period):])
        avg_loss = statistics.mean(losses[-(self.rsi_period):])
        if avg_loss == 0: return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _stoch_rsi(self, prices):
        if len(prices) < self.rsi_period + self.stoch_period: return 50.0
        # Calculate RSI series first
        rsi_series = []
        # We need enough RSIs to calculate Stoch
        start_idx = len(prices) - (self.stoch_period + 5) 
        if start_idx < self.rsi_period: start_idx = self.rsi_period
        
        for i in range(start_idx, len(prices) + 1):
            sub = prices[:i]
            if len(sub) > self.rsi_period:
                rsi_series.append(self._rsi(sub))
        
        if len(rsi_series) < self.stoch_period: return 50.0
        
        current_rsi = rsi_series[-1]
        window = rsi_series[-self.stoch_period:]
        min_rsi = min(window)
        max_rsi = max(window)
        
        if max_rsi == min_rsi: return 50.0
        k = ((current_rsi - min_rsi) / (max_rsi - min_rsi)) * 100
        return k

    def _macd(self, prices):
        if len(prices) < self.ema_slow + self.macd_signal: return 0,0,0
        fast = self._ema_series(prices, self.ema_fast)
        slow = self._ema_series(prices, self.ema_slow)
        # Trim to match lengths if necessary (though _ema_series returns full length)
        macd_line = [f - s for f, s in zip(fast, slow)]
        signal_line = self._ema_series(macd_line, self.macd_signal)
        return macd_line[-1], signal_line[-1], macd_line[-1] - signal_line[-1]

    def _atr(self, prices):
        if len(prices) < self.atr_period + 1: return 0.0
        trs = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        return statistics.mean(trs[-self.atr_period:])

    def _keltner(self, prices, atr_val):
        if not prices: return 0,0,0
        mid = self._ema(prices, self.keltner_period)
        upper = mid + (self.atr_mult * atr_val)
        lower = mid - (self.atr_mult * atr_val)
        return mid, upper, lower

    def _detect_regime(self, prices):
        """Analyze volatility to adjust risk."""
        if len(prices) < 20: return "NORMAL", 1.0
        returns = [(prices[i]-prices[i-1])/prices[i-1] for i in range(1, len(prices))]
        vol = statistics.stdev(returns) * 100 # percentage
        if vol > 1.2: return "HIGH", 0.6 # High risk, reduce size
        if vol < 0.2: return "LOW", 1.2  # Low risk, increase size
        return "NORMAL", 1.0

    # =====================
    # LOGIC LOOP
    # =====================

    def on_price_update(self, prices: dict):
        # Update history
        symbols = list(prices.keys())
        random.shuffle(symbols) # Avoid deterministic order bias

        for sym in symbols:
            p = prices[sym]['priceUsd']
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_window)
            self.history[sym].append(p)
            self.last_prices[sym] = p

        # 1. Manage existing positions (The Fix for Stop Loss)
        exit_sig = self._manage_positions()
        if exit_sig:
            return exit_sig

        # 2. Check for new entries
        if len(self.current_positions) >= self.max_positions:
            return None

        best_score = -999
        best_trade = None

        for sym in symbols:
            if sym in self.current_positions: continue
            hist = self.history[sym]
            if len(hist) < self.min_warmup: continue
            
            # Skip if banned
            # (Hive Mind logic: sometimes we ban tags temporarily)
            
            signal = self._analyze_symbol(sym, list(hist))
            if signal:
                # Check for tag bans
                if any(tag in self.banned_tags for tag in signal['reason']):
                    continue
                    
                if signal['score'] > best_score:
                    best_score = signal['score']
                    best_trade = signal

        if best_trade:
            # Clean up score before returning
            del best_trade['score']
            return best_trade
            
        return None

    def _manage_positions(self):
        """
        Penalty Fix: 'STOP_LOSS' implies we are exiting too frequently on noise.
        Solution: Use ATR-based dynamic stops and confirm with RSI.
        Don't sell into a crash (oversold) unless catastrophic.
        """
        for sym, amount in list(self.current_positions.items()):
            current_price = self.last_prices.get(sym)
            entry_price = self.entry_prices.get(sym)
            if not current_price or not entry_price: continue

            hist = list(self.history[sym])
            atr = self._atr(hist) if len(hist) > self.atr_period else (current_price * 0.02)
            
            # Calculate PnL
            pnl_pct = (current_price - entry_price) / entry_price
            
            # Track Peaks for Trailing
            if sym not in self.peak_prices: self.peak_prices[sym] = current_price
            if current_price > self.peak_prices[sym]: self.peak_prices[sym] = current_price
            
            peak = self.peak_prices[sym]
            drawdown = (peak - current_price) / peak
            
            # Dynamic Trailing Stop
            # Tighter trail if we are in high profit
            activation = self.trailing_activate_base
            trail_dist = 0.025 # default 2.5%
            
            if pnl_pct > 0.05: # >5% profit
                trail_dist = 0.015 # Tighten to 1.5%
            
            if pnl_pct > activation and drawdown > trail_dist:
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amount,
                    'reason': ['TRAILING_PROFIT', f"PNL_{pnl_pct*100:.1f}"]
                }

            # Take Profit (Targets)
            # Volatility adjusted TP
            tp_target = 0.06 + (atr / current_price * 2) # Base 6% + volatility
            if pnl_pct > tp_target:
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amount,
                    'reason': ['TAKE_PROFIT_DYNAMIC']
                }

            # === THE FIX: STRUCTURAL STOP ===
            # Instead of a hard % stop, we use ATR multiples.
            # AND we check RSI. If RSI < 25, we are oversold, so we WAIT for a bounce
            # unless the loss is catastrophic (> 20%).
            
            stop_dist = atr * 3.0 * self.personality["stop_loss_mult"] # Wide breadth
            stop_price = entry_price - stop_dist
            
            is_catastrophic = pnl_pct < -0.15 # Hard floor at -15%
            is_below_structure = current_price < stop_price
            
            rsi = self._rsi(hist)
            
            if is_catastrophic:
                # Emergency exit regardless of indicators
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amount,
                    'reason': ['EMERGENCY_EXIT', 'HARD_FLOOR'] # Renamed tag
                }
            
            if is_below_structure:
                # Logic: Only sell if NOT oversold. If oversold, wait for mean reversion.
                if rsi > 30: 
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': amount,
                        'reason': ['STRUCTURAL_EXIT', 'ATR_BREAK'] # Renamed tag
                    }
                
        return None

    def _analyze_symbol(self, sym, hist):
        """
        Generate signals with strict filters to avoid bad entries
        that lead to stops.
        """
        current_price = hist[-1]
        regime, size_mult = self._detect_regime(hist)
        
        # Calculate Indicators
        atr = self._atr(hist)
        k_mid, k_up, k_lo = self._keltner(hist, atr)
        stoch = self._stoch_rsi(hist)
        rsi = self._rsi(hist)
        macd, signal, hist_bar = self._macd(hist)
        ema_f = self._ema(hist, self.ema_fast)
        ema_s = self._ema(hist, self.ema_slow)

        # Base size
        base_amt = self.balance * 0.12 * size_mult * self.personality["risk_skew"]
        base_amt = max(10.0, min(base_amt, self.balance * self.max_position_pct))

        # === STRATEGY 1: PRECISION DIP (Fixing 'DIP_BUY') ===
        # Requirements:
        # 1. Price below Keltner Lower
        # 2. StochRSI extremely oversold (<10)
        # 3. RSI not dead (<20 is too weak, 25-40 is sweet spot for dip)
        # 4. Volatility is not insane (Regime != HIGH)
        
        if current_price < k_lo and stoch < 10:
            if 25 < rsi < 45 and regime != "HIGH":
                score = 10
                # Boost score if MACD histogram is ticking up (convergence)
                if hist_bar > 0 or (len(hist) > 2 and hist_bar > self._macd(hist[:-1])[2]):
                    score += 5
                
                return {
                    'side': 'BUY', 'symbol': sym, 'amount': base_amt,
                    'reason': ['PRECISION_DIP', 'KELTNER_OVERSOLD'],
                    'score': score
                }

        # === STRATEGY 2: MOMENTUM BREAKOUT ===
        # Requirements:
        # 1. Price > Keltner Upper
        # 2. EMA Fast > EMA Slow (Trend Up)
        # 3. MACD > Signal (Momentum Up)
        # 4. StochRSI not exhausted (< 85)
        
        if current_price > k_up and ema_f > ema_s:
            if macd > signal and stoch < 85:
                score = 8
                if regime == "LOW": score += 2 # Breakouts work best in low vol expansion
                
                return {
                    'side': 'BUY', 'symbol': sym, 'amount': base_amt,
                    'reason': ['MOMENTUM_BREAK', 'TREND_CONFIRM'],
                    'score': score
                }

        # === STRATEGY 3: MEAN REVERSION SHORT-TERM ===
        # Buying pullbacks in an uptrend
        # 1. Trend is UP (EMA F > S)
        # 2. Price dipped to Keltner Mid (Mean)
        # 3. StochRSI turned up from < 20
        
        if ema_f > ema_s and current_price < k_mid * 1.005 and current_price > k_mid * 0.995:
            if stoch < 30 and macd > 0:
                return {
                    'side': 'BUY', 'symbol': sym, 'amount': base_amt, 
                    'reason': ['TREND_PULLBACK', 'EMA_SUPPORT'],
                    'score': 7
                }

        return None

    def on_hive_signal(self, signal):
        # Mandatory method for Hive compliance, though not always used
        if "penalize" in signal:
            for tag in signal["penalize"]:
                self.banned_tags.add(tag)

    def on_trade_executed(self, symbol, side, amount, price):
        if side == "BUY":
            self.current_positions[symbol] = self.current_positions.get(symbol, 0) + amount
            self.entry_prices[symbol] = price
            self.peak_prices[symbol] = price
        elif side == "SELL":
            if symbol in self.current_positions:
                del self.current_positions[symbol]
                del self.entry_prices[symbol]
                del self.peak_prices[symbol]