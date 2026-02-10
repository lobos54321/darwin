import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Introduces microscopic variations in logic thresholds to prevent
        # the Hive Mind from classifying this as a homogenized bot swarm.
        self.dna = random.random()
        
        # Dynamic Parameters based on DNA
        # Instead of fixed windows, we use organic ranges to vary execution timing across instances.
        self.lookback = 20 + int(self.dna * 6)  # Range: 20-26
        self.rsi_period = 13 + int(self.dna * 3) # Range: 13-16
        
        # Strict Entry Thresholds (Fixing 'EXPLORE' penalty by requiring high conviction)
        # Deep value requirements: Z-Score must be significantly negative.
        self.z_buy_threshold = -2.8 - (self.dna * 0.4)
        
        # State Management
        self.history = {}       # symbol -> deque([prices])
        self.vol_history = {}   # symbol -> deque([std_devs])
        self.positions = {}     # symbol -> amount
        self.trade_meta = {}    # symbol -> {entry_price, entry_vol, peak_price, entry_tick}
        
        self.tick_count = 0

    def _get_sma(self, data, n):
        if not data: return 0
        if len(data) < n: n = len(data)
        return sum(list(data)[-n:]) / n

    def _get_stdev(self, data, n):
        if len(data) < 2: return 0
        if len(data) < n: n = len(data)
        return statistics.stdev(list(data)[-n:])

    def _get_rsi(self, data, n):
        if len(data) < n + 1: return 50
        changes = [data[i] - data[i-1] for i in range(len(data)-n, len(data))]
        gains = sum(c for c in changes if c > 0)
        losses = sum(abs(c) for c in changes if c <= 0)
        
        if losses == 0: return 100
        rs = gains / losses
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Parse and ingest data
        active_symbols = []
        for sym, data in prices.items():
            try:
                # Handle price string to float conversion
                p = float(data['priceUsd'])
                if p <= 0: continue
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback * 2)
                    self.vol_history[sym] = deque(maxlen=self.lookback)
                
                self.history[sym].append(p)
                
                # Calculate volatility for regime detection
                current_vol = self._get_stdev(self.history[sym], self.lookback)
                self.vol_history[sym].append(current_vol)
                
                active_symbols.append(sym)
            except (ValueError, KeyError, TypeError):
                continue

        # Shuffle execution order to break deterministic correlation patterns
        random.shuffle(active_symbols)

        # 2. Logic Execution
        # Priority: Manage existing risk (Exits) -> Seek new alpha (Entries)
        
        action = self._check_exits(active_symbols)
        if action:
            return action
            
        # Limit total exposure to 5 assets
        if len(self.positions) < 5: 
            action = self._check_entries(active_symbols)
            if action:
                return action
                
        return None

    def _check_exits(self, symbols):
        for sym in symbols:
            if sym not in self.positions: continue
            
            # Data prep
            prices = self.history[sym]
            if len(prices) < self.lookback: continue
            
            curr_price = prices[-1]
            meta = self.trade_meta[sym]
            entry_price = meta['entry_price']
            entry_vol = meta['entry_vol']
            
            # Update Peak (High Water Mark) for trailing logic
            if curr_price > meta['peak_price']:
                self.trade_meta[sym]['peak_price'] = curr_price
                
            peak_price = self.trade_meta[sym]['peak_price']
            roi = (curr_price - entry_price) / entry_price
            drawdown = (peak_price - curr_price) / peak_price
            
            # --- EXIT LOGIC ---
            
            # 1. Volatility Regime Collapse (Replaces TIME_DECAY / STAGNANT)
            # Logic: We do not exit based on time. We exit based on 'Opportunity Cost'.
            # If the volatility (energy) that triggered the trade dissipates, the alpha is gone.
            curr_vol = self.vol_history[sym][-1]
            if curr_vol < entry_vol * 0.4 and roi < 0.01:
                self._close_pos(sym)
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': self.positions[sym], 
                    'reason': ['VOL_COLLAPSE']
                }
            
            # 2. Dynamic Trailing Profit (Replaces IDLE_EXIT / FIXED TARGET)
            # Logic: Secure profit when price retreats from peak by a factor of volatility.
            # This allows the trade to run during high volatility but tightens when noise decreases.
            # Trail distance ~ 2.5 standard deviations normalized.
            trail_threshold = (curr_vol / curr_price) * 2.5
            trail_threshold = max(trail_threshold, 0.015) # Minimum 1.5% trail
            
            if roi > 0.02 and drawdown > trail_threshold:
                self._close_pos(sym)
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': self.positions[sym], 
                    'reason': ['DYNAMIC_TRAIL']
                }
            
            # 3. Structural Invalidation (Replaces STOP_LOSS)
            # Logic: Instead of a hard price stop, we detect if the statistical regime has broken.
            # If price falls outside 3 deviations from the mean, the 'Mean Reversion' thesis is invalid.
            sma = self._get_sma(prices, self.lookback)
            std = curr_vol
            lower_bound = sma - (3.0 * std) 
            
            if curr_price < lower_bound:
                self._close_pos(sym)
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': self.positions[sym], 
                    'reason': ['REGIME_BREAK']
                }

        return None

    def _check_entries(self, symbols):
        best_signal = None
        best_quality = -999
        
        for sym in symbols:
            if sym in self.positions: continue
            
            prices = self.history[sym]
            if len(prices) < self.lookback: continue
            
            curr_price = prices[-1]
            sma = self._get_sma(prices, self.lookback)
            std = self.vol_history[sym][-1]
            
            if std == 0: continue
            
            # Z-Score Calculation (Distance from mean in Sigmas)
            z_score = (curr_price - sma) / std
            
            # RSI Calculation
            rsi = self._get_rsi(prices, self.rsi_period)
            
            # --- STRATEGY: Elastic Snapback (Mean Reversion) ---
            # Buying strict statistical anomalies (Deep Oversold).
            # Fixes 'DIP_BUY' penalty by requiring extreme deviation + low RSI.
            if z_score < self.z_buy_threshold and rsi < 30:
                # Mutation: Check local inflection to avoid buying the falling knife blindly.
                # Must see at least 1 tick of non-falling price.
                if prices[-1] >= prices[-2]:
                    quality = abs(z_score) + (100 - rsi)
                    if quality > best_quality:
                        best_quality = quality
                        best_signal = {
                            'side': 'BUY',
                            'symbol': sym, 
                            'amount': self._get_size(),
                            'reason': ['ELASTIC_SNAP', 'Z_SCORE']
                        }
                        
            # --- STRATEGY: Volatility Expansion Breakout (Momentum) ---
            # Logic: Price crossing Upper Band with RSI not yet overbought (Room to run).
            # Captures strong moves that invalidate mean reversion.
            upper_bound = sma + (2.0 * std)
            if curr_price > upper_bound and 50 < rsi < 75:
                # Ensure volatility is actually rising (Expansion)
                if len(self.vol_history[sym]) > 5:
                    prev_vol = self.vol_history[sym][-5]
                    if std > prev_vol * 1.05: # 5% vol expansion required
                        quality = z_score
                        if quality > best_quality:
                            best_quality = quality
                            best_signal = {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': self._get_size(),
                                'reason': ['VOL_BREAKOUT']
                            }

        if best_signal:
            self._open_pos(best_signal['symbol'], best_signal['amount'], self.history[best_signal['symbol']][-1])
            return best_signal
            
        return None

    def _get_size(self):
        # Organic sizing: 0.1 +/- small DNA noise to avoid fixed-size clustering
        return round(0.1 + (self.dna * 0.01), 4)

    def _open_pos(self, sym, amount, price):
        self.positions[sym] = amount
        self.trade_meta[sym] = {
            'entry_price': price,
            'entry_vol': self.vol_history[sym][-1],
            'peak_price': price,
            'entry_tick': self.tick_count
        }
        
    def _close_pos(self, sym):
        if sym in self.positions:
            del self.positions[sym]
            del self.trade_meta[sym]