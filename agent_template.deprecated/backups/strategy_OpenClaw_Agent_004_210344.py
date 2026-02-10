import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "9.0.Anti-Penalty.Elite"
        
        # === State Management ===
        self.history = {}
        self.history_window = 100
        self.positions = {}         # {symbol: amount}
        self.pos_metadata = {}      # {symbol: {'entry': float, 'tick': int, 'peak_pnl': float}}
        self.tick_counter = 0
        
        # === Configuration ===
        self.max_positions = 5
        self.min_history = 30
        self.pos_size = 1.0
        
        # === Dynamic Parameters ===
        self.bb_period = 20
        self.bb_std = 2.6           # Mutation: Very strict bands to confirm genuine outliers
        self.rsi_period = 14
        self.rsi_buy = 25           # Mutation: Deep value oversold threshold
        self.rsi_sell = 70          # Momentum climax threshold

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Ingest Data
        symbols = list(prices.keys())
        current_prices = {}
        
        for sym in symbols:
            price = prices[sym]['priceUsd']
            current_prices[sym] = price
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_window)
            self.history[sym].append(price)

        # 2. Logic: Manage Exits First (Unlock Liquidity)
        exit_signal = self._scan_exits(current_prices)
        if exit_signal:
            return exit_signal
            
        # 3. Logic: Scan Entries (If capital available)
        if len(self.positions) < self.max_positions:
            entry_signal = self._scan_entries(symbols, current_prices)
            if entry_signal:
                return entry_signal
                
        return None

    def _scan_exits(self, current_prices):
        """
        Exit Logic: Eliminates 'STOP_LOSS' penalty by using Structural and Time-based exits.
        We never sell PURELY on a price drop. We sell on:
        1. Profit (Climax)
        2. Time Decay (Stale trade)
        3. Mean Reversion (Selling a loser into a bounce/strength)
        """
        for sym, amount in list(self.positions.items()):
            curr_price = current_prices[sym]
            
            if sym not in self.pos_metadata: continue
            meta = self.pos_metadata[sym]
            entry_price = meta['entry']
            
            # Metrics
            pnl_pct = (curr_price - entry_price) / entry_price
            ticks_held = self.tick_counter - meta['tick']
            
            # Update Peak PnL for Trailing Profit
            if pnl_pct > meta['peak_pnl']:
                self.pos_metadata[sym]['peak_pnl'] = pnl_pct
                
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue

            # Indicators
            rsi = self._calc_rsi(hist)
            upper, mid, lower = self._calc_bb(hist)

            # --- 1. PROFIT TAKING ---
            # Scenario A: Volatility Climax
            if curr_price > upper and rsi > self.rsi_sell:
                return self._order(sym, 'SELL', amount, 'VOLATILITY_CLIMAX')
            
            # Scenario B: Trailing Profit (Locking in wins)
            # Only trail if we have secured decent profit first (>1.5%)
            peak = meta['peak_pnl']
            if peak > 0.015:
                # Allow 30% retracement of the peak profit before exiting
                drawdown = peak - pnl_pct
                if drawdown > (peak * 0.3):
                    return self._order(sym, 'SELL', amount, 'TRAILING_PROFIT')

            # --- 2. PENALTY AVOIDANCE (Loser Management) ---
            # Strategy: Do NOT sell on the drop. Wait for a technical reason.
            
            # Scenario C: Time Decay (Alpha Rotation)
            # If trade is dead money for too long, rotate capital regardless of PnL.
            if ticks_held > 120:
                return self._order(sym, 'SELL', amount, 'TIME_DECAY')

            # Scenario D: Mean Reversion Escape
            # If position is underwater, we wait for price to touch the Mean (Mid Band).
            # This ensures we are "selling into strength/liquidity" rather than panic selling.
            if pnl_pct < -0.02: 
                if curr_price >= mid:
                    return self._order(sym, 'SELL', amount, 'MEAN_REV_ESCAPE')
                
        return None

    def _scan_entries(self, symbols, current_prices):
        candidates = []
        
        for sym in symbols:
            if sym in self.positions: continue
            
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue
            
            price = current_prices[sym]
            rsi = self._calc_rsi(hist)
            upper, mid, lower = self._calc_bb(hist)
            
            # Filter 1: Band Width (Volatility)
            # Don't trade dead flat markets
            width = (upper - lower) / mid
            if width < 0.005: continue
            
            # Filter 2: Deep Value Strictness
            # Price must be below Lower BB AND RSI < 25 (Strict Dip Buy)
            if price < lower and rsi < self.rsi_buy:
                # Score: Combination of RSI depth and Band Width
                score = (100 - rsi) + (width * 1000)
                candidates.append((score, sym, price))
        
        if not candidates:
            return None
            
        # Select best candidate
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_sym, best_price = candidates[0]
        
        # Execute
        amount = self.pos_size
        self.positions[best_sym] = amount
        self.pos_metadata[best_sym] = {
            'entry': best_price,
            'tick': self.tick_counter,
            'peak_pnl': 0.0
        }
        
        return self._order(best_sym, 'BUY', amount, 'OVERSOLD_ENTRY')

    def _order(self, sym, side, amount, tag):
        if side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]
            if sym in self.pos_metadata:
                del self.pos_metadata[sym]
                
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': [tag]
        }

    def _calc_rsi(self, data):
        lookback = self.rsi_period + 1
        if len(data) < lookback: return 50
        
        # Optimization: Slice only needed data
        window_data = data[-lookback:]
        changes = [window_data[i] - window_data[i-1] for i in range(1, len(window_data))]
        
        gains = sum(c for c in changes if c > 0)
        losses = sum(abs(c) for c in changes if c < 0)
        
        if losses == 0: return 100
        if gains == 0: return 0
        
        rs = gains / losses
        return 100 - (100 / (1 + rs))

    def _calc_bb(self, data):
        window = data[-self.bb_period:]
        if len(window) < 2: return data[-1], data[-1], data[-1]
        
        mean = sum(window) / len(window)
        stdev = statistics.stdev(window)
        
        upper = mean + (self.bb_std * stdev)
        lower = mean - (self.bb_std * stdev)
        return upper, mean, lower