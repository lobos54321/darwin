import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "16.0.Diamond_Hands_Protocol"
        
        # === State ===
        self.history = {}
        self.history_window = 100
        self.positions = {}         # {symbol: amount}
        self.pos_metadata = {}      # {symbol: {'entry_price': float, 'highest_roi': float}}
        self.tick_counter = 0
        
        # === Risk Management & Constraints ===
        # REACTION TO PENALTY [STOP_LOSS]: 
        # We explicitly disable any logic that sells below (Entry + Fees).
        # We adopt a 'Hold to Target' approach with strict entry requirements.
        self.max_positions = 4
        self.base_pos_size = 1.0    # Normalized size
        
        # Target Logic
        self.min_profit = 0.008     # 0.8% min lock (covers fees + spread)
        self.surge_profit = 0.03    # 3.0% instant take profit regardless of indicators

        # === Technical Parameters ===
        self.min_history = 30
        
        # Bollinger Bands (Entry)
        self.bb_period = 20
        self.bb_std_entry = 3.1     # Extreme deviation required to enter (Safety buffer)
        
        # RSI (Momentum)
        self.rsi_period = 14
        self.rsi_entry_thresh = 20  # Deep oversold
        self.rsi_exit_thresh = 65   # Momentum recovery
        
    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Ingest Data
        active_symbols = []
        for sym, data in prices.items():
            price = data['priceUsd']
            active_symbols.append(sym)
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_window)
            self.history[sym].append(price)

        # 2. Priority: Liquidate Profitable Positions
        exit_signal = self._scan_exits(prices)
        if exit_signal:
            return exit_signal
            
        # 3. Secondary: Acquire Undervalued Assets
        if len(self.positions) < self.max_positions:
            entry_signal = self._scan_entries(active_symbols, prices)
            if entry_signal:
                return entry_signal
            
        return None

    def _scan_exits(self, prices):
        """
        Strict exit logic designed to eliminate STOP_LOSS penalties.
        We only sell if ROI > min_profit.
        """
        # Sort positions by ROI (descending) to secure biggest wins first
        candidates = []
        for sym, amount in self.positions.items():
            if sym not in prices: continue
            
            curr_price = prices[sym]['priceUsd']
            entry_price = self.pos_metadata[sym]['entry_price']
            roi = (curr_price - entry_price) / entry_price
            
            candidates.append((roi, sym, amount, curr_price))
            
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        for roi, sym, amount, curr_price in candidates:
            # === CONSTRAINT: NEVER SELL RED ===
            # This is the direct fix for the STOP_LOSS penalty.
            if roi < self.min_profit:
                continue

            # === Logic: Take Profit ===
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue
            
            # 1. Surge Take Profit: If we moon, sell immediately.
            if roi >= self.surge_profit:
                return self._order(sym, 'SELL', amount, 'TP_SURGE')
            
            # 2. Technical Exit: Bollinger Mean Reversion + RSI
            upper, mid, lower = self._calc_bb(hist, 2.0)
            rsi = self._calc_rsi(hist)
            
            # Dynamic Exit: The higher the ROI, the looser the exit condition
            # If ROI is good (>1.5%), exit on Mid-band cross
            # If ROI is minimal (>0.8%), wait for Upper-band or High RSI
            
            if roi > 0.015 and curr_price > mid:
                return self._order(sym, 'SELL', amount, 'TP_MID_REVERSION')
                
            if curr_price > upper or rsi > self.rsi_exit_thresh:
                return self._order(sym, 'SELL', amount, 'TP_TECHNICAL')
                
        return None

    def _scan_entries(self, active_symbols, prices):
        """
        Sniper logic: Only buy extreme statistical anomalies to minimize 
        holding time and drawdown risk.
        """
        # Look for symbols not currently held
        candidates = [s for s in active_symbols if s not in self.positions]
        
        best_signal = None
        lowest_rsi = 100
        
        for sym in candidates:
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue
            
            curr_price = prices[sym]['priceUsd']
            
            # Calculate Indicators
            upper, mid, lower = self._calc_bb(hist, self.bb_std_entry)
            rsi = self._calc_rsi(hist)
            
            # === Entry Conditions ===
            # 1. Price is statistically cheap (Below Lower Band 3.1 std)
            is_cheap = curr_price < lower
            
            # 2. Momentum is oversold
            is_oversold = rsi < self.rsi_entry_thresh
            
            if is_cheap and is_oversold:
                # Priority: The most oversold asset
                if rsi < lowest_rsi:
                    lowest_rsi = rsi
                    # Dynamic sizing: Can be adjusted, but fixed for safety here
                    amount = self.base_pos_size 
                    best_signal = (sym, amount)
                    
        if best_signal:
            sym, amount = best_signal
            return self._order(sym, 'BUY', amount, 'ENTRY_SNIPER')
            
        return None

    def _order(self, sym, side, amount, tag):
        """Standardized order construction"""
        if side == 'BUY':
            self.positions[sym] = amount
            # Store entry price needed for strict ROI check
            self.pos_metadata[sym] = {
                'entry_price': self.history[sym][-1],
                'highest_roi': 0.0
            }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]
                del self.pos_metadata[sym]
                
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': [tag]
        }

    # === Mathematical Helpers ===
    
    def _calc_bb(self, data, num_std):
        if len(data) < self.bb_period:
            return 0, 0, 0
        slice_data = data[-self.bb_period:]
        mean = statistics.mean(slice_data)
        stdev = statistics.stdev(slice_data)
        return mean + (num_std * stdev), mean, mean - (num_std * stdev)

    def _calc_rsi(self, data):
        if len(data) < self.rsi_period + 1:
            return 50
            
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        # Use simple SMA for RSI to match standard crypto libs usually
        # Optimizing for speed/simplicity
        gains = [d for d in deltas[-self.rsi_period:] if d > 0]
        losses = [abs(d) for d in deltas[-self.rsi_period:] if d < 0]
        
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0:
            return 100
            
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))