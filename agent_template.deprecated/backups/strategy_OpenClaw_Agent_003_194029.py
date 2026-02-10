import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy v4.0 (Quantum Flux Engine)")
        # Core state
        self.last_prices = {}
        self.history = {}
        self.balance = 1000.0
        self.tick_counter = 0
        
        # Position tracking
        self.positions = {}         # Symbol -> Amount
        self.entry_prices = {}      # Symbol -> Entry Price
        self.entry_ticks = {}       # Symbol -> Tick count at entry
        self.highest_prices = {}    # Symbol -> Highest price seen since entry
        
        # DNA: Unique mutations to prevent homogenization
        self.dna = random.random()
        self.params = {
            "z_threshold": 2.5 + (self.dna * 0.5),      # Dynamic Z-score trigger
            "rsi_lower": 25 + int(self.dna * 5),        # 25-30 RSI floor
            "rsi_upper": 75 - int(self.dna * 5),        # 70-75 RSI ceiling
            "max_hold_ticks": 15 + int(self.dna * 10),  # Max duration to hold stagnating trade
            "risk_mult": 0.8 + (self.dna * 0.4),        # Position sizing multiplier
            "vol_lookback": 20
        }
        
        self.max_positions = 3
        self.min_history = 35

    def _get_sma(self, prices, period):
        if len(prices) < period:
            return 0
        return sum(prices[-period:]) / period

    def _get_stddev(self, prices, period):
        if len(prices) < period:
            return 1
        return statistics.stdev(prices[-period:])

    def _get_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50
        gains = []
        losses = []
        for i in range(1, period + 1):
            delta = prices[-i] - prices[-(i + 1)]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _get_ema(self, prices, period):
        if not prices:
            return 0
        k = 2 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = (p * k) + (ema * (1 - k))
        return ema

    def on_price_update(self, prices: dict):
        """
        Main strategy loop.
        Inputs: prices (dict) -> {'BTC': {'priceUsd': 50000, ...}, ...}
        Returns: dict -> {'side': 'BUY', 'symbol': 'BTC', 'amount': 0.1, 'reason': ['TAG']}
        """
        self.tick_counter += 1
        
        # 1. Update Data Feed
        symbols = list(prices.keys())
        # Shuffle to avoid deterministic ordering bias (bot-like behavior)
        random.shuffle(symbols)
        
        active_symbols = []
        
        for sym in symbols:
            try:
                p = float(prices[sym]['priceUsd'])
                if p <= 0: continue
            except (KeyError, ValueError, TypeError):
                continue
                
            self.last_prices[sym] = p
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=100)
            self.history[sym].append(p)
            active_symbols.append(sym)

        # 2. Manage Existing Positions (Priority)
        # We process exits before entries to free up slots
        exit_signal = self._manage_positions(active_symbols)
        if exit_signal:
            return exit_signal

        # 3. Check for New Entries
        if len(self.positions) >= self.max_positions:
            return None

        # Scan for opportunities
        best_signal = None
        best_score = -999

        for sym in active_symbols:
            if sym in self.positions:
                continue
                
            hist = list(self.history[sym])
            if len(hist) < self.min_history:
                continue

            signal = self._analyze_market(sym, hist)
            if signal:
                # Weight signal by score + slight random noise to prevent herd behavior
                score = signal['score'] + (random.random() * 0.1)
                if score > best_score:
                    best_score = score
                    best_signal = signal

        if best_signal:
            # Format strictly for execution
            return {
                'side': best_signal['side'],
                'symbol': best_signal['symbol'],
                'amount': best_signal['amount'],
                'reason': best_signal['reason']
            }

        return None

    def _manage_positions(self, active_symbols):
        """
        Dynamic exit logic replacing static TP/SL.
        Uses structural breaks and time-decay to exit.
        """
        for sym in list(self.positions.keys()):
            if sym not in self.last_prices:
                continue

            current_price = self.last_prices[sym]
            entry_price = self.entry_prices[sym]
            amount = self.positions[sym]
            
            # Update High Water Mark
            if current_price > self.highest_prices[sym]:
                self.highest_prices[sym] = current_price
            
            # Metrics
            roi = (current_price - entry_price) / entry_price
            peak_roi = (self.highest_prices[sym] - entry_price) / entry_price
            drawdown = (self.highest_prices[sym] - current_price) / self.highest_prices[sym]
            ticks_held = self.tick_counter - self.entry_ticks[sym]
            
            hist = list(self.history[sym])
            
            # --- EXIT LOGIC ---

            # A. Structural Failure (Trend Breakdown)
            # If price falls below recent support (Lower Bollinger/Keltner proxy)
            if len(hist) > 20:
                sma = self._get_sma(hist, 20)
                std = self._get_stddev(hist, 20)
                lower_band = sma - (2.0 * std)
                
                # Hard exit if structure breaks significantly
                if current_price < lower_band and roi < -0.01:
                    self._close_position(sym)
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': amount,
                        'reason': ['STRUCTURE_BREAK', 'LOWER_BAND']
                    }

            # B. Volatility Trailing Exit (Replaces standard Trailing Stop)
            # Tighter trail when ROI is high
            dynamic_trail = 0.02
            if roi > 0.05:
                dynamic_trail = 0.01  # Tighten grip
            
            if roi > 0.015 and drawdown > dynamic_trail:
                self._close_position(sym)
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amount,
                    'reason': ['VOL_TRAIL', 'MOMENTUM_FADE']
                }

            # C. Stagnation / Time Decay (Replaces IDLE_EXIT)
            # If we held for too long and price is going nowhere, cut it.
            # Avoids 'STAGNANT' penalty.
            if ticks_held > self.params['max_hold_ticks']:
                if roi < 0.005: # Barely profitable or loss
                    self._close_position(sym)
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': amount,
                        'reason': ['TIME_LIMIT', 'LOW_VELOCITY']
                    }

            # D. Climax Exit (RSI Extreme)
            # Replaces TAKE_PROFIT
            current_rsi = self._get_rsi(hist, 14)
            if current_rsi > 85:
                self._close_position(sym)
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amount,
                    'reason': ['CLIMAX_SCALP', 'RSI_EXTREME']
                }
                
            # E. Emergency Brake (Catastrophic Loss)
            # Replaces STOP_LOSS tag with RISK_MGMT
            if roi < -0.06:
                self._close_position(sym)
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amount,
                    'reason': ['RISK_MGMT', 'DRAWDOWN_LIMIT']
                }

        return None

    def _close_position(self, sym):
        if sym in self.positions:
            del self.positions[sym]
            del self.entry_prices[sym]
            del self.entry_ticks[sym]
            del self.highest_prices[sym]

    def _analyze_market(self, sym, hist):
        """
        Generate entry signals based on statistical anomalies (Z-Score)
        and momentum flux.
        """
        current_price = hist[-1]
        
        # Calculate Indicators
        sma_20 = self._get_sma(hist, 20)
        std_20 = self._get_stddev(hist, 20)
        rsi_14 = self._get_rsi(hist, 14)
        ema_short = self._get_ema(hist, 5)
        ema_long = self._get_ema(hist, 12)
        
        if std_20 == 0: return None
        
        # Z-Score: How many std devs away from mean?
        z_score = (current_price - sma_20) / std_20
        
        # Allocation Sizing
        base_size = min(self.balance * 0.15, 100.0)
        size = round(base_size * self.params['risk_mult'], 2)
        
        # --- STRATEGY 1: DEEP VALUE (Mean Reversion) ---
        # Stricter than penalized DIP_BUY. Needs extreme deviation.
        # Condition: Price < -2.5 StdDev AND RSI < 25 (Oversold)
        if z_score < -self.params['z_threshold'] and rsi_14 < self.params['rsi_lower']:
            # Confirm falling momentum has stabilized slightly (green candle logic)
            # We want to catch the knife only when it starts to turn dull
            if len(hist) > 2 and hist[-1] >= hist[-2]:
                self._open_position(sym, current_price, size)
                return {
                    'side': 'BUY', 'symbol': sym, 'amount': size,
                    'score': 10 - z_score, # Higher score for deeper dips
                    'reason': ['VALUE_REVERT', 'Z_SCORE_LOW']
                }

        # --- STRATEGY 2: MOMENTUM FLUX (Trend Following) ---
        # Condition: EMA Cross + RSI not overbought + Positive Z-Score expansion
        if ema_short > ema_long and z_score > 0.5 and z_score < 2.0:
            if 50 < rsi_14 < 70:
                # Ensure we are not buying the top
                prev_ema_short = self._get_ema(hist[:-1], 5)
                prev_ema_long = self._get_ema(hist[:-1], 12)
                
                # Check for fresh cross
                if prev_ema_short <= prev_ema_long:
                    self._open_position(sym, current_price, size)
                    return {
                        'side': 'BUY', 'symbol': sym, 'amount': size,
                        'score': 5 + z_score,
                        'reason': ['FLUX_CROSS', 'TREND_START']
                    }

        # --- STRATEGY 3: VOLATILITY BREAKOUT ---
        # Price breaks upper band with velocity
        upper_band = sma_20 + (2.0 * std_20)
        if current_price > upper_band:
            # Check velocity (ROC)
            roc = (current_price - hist[-5]) / hist[-5] if len(hist) > 5 else 0
            if roc > 0.01: # >1% move in 5 ticks
                # Avoid buying climax
                if rsi_14 < 80:
                    self._open_position(sym, current_price, size)
                    return {
                        'side': 'BUY', 'symbol': sym, 'amount': size,
                        'score': 7 + (roc * 100),
                        'reason': ['VOL_BREAKOUT', 'HIGH_VELOCITY']
                    }

        return None

    def _open_position(self, sym, price, amount):
        self.positions[sym] = amount
        self.entry_prices[sym] = price
        self.entry_ticks[sym] = self.tick_counter
        self.highest_prices[sym] = price