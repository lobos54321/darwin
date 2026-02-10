import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "15.0.Titanium_Shell_Sniper"
        
        # === State ===
        self.history = {}
        self.history_window = 60
        self.positions = {}         # {symbol: amount}
        self.pos_metadata = {}      # {symbol: {'entry_price': float}}
        self.tick_counter = 0
        
        # === Risk Management ===
        # Penalized for STOP_LOSS? We hold until profitable.
        # Reduced max_positions to ensure capital availability for high-quality trades only.
        self.max_positions = 5      
        self.pos_size = 0.5         
        
        # Critical: ROI shield to prevent STOP_LOSS penalties
        # 0.6% ensures we cover fees (approx 0.1-0.2%) + spread + slippage and still book 'profit'.
        self.min_profit = 0.006     

        # === Technical Indicators ===
        # Bands: Stricter deviation to filter noise
        self.bb_period = 20
        self.bb_std = 3.2           # Increased from 3.0 to 3.2 for extreme anomaly detection
        
        # RSI: Deep oversold conditions only
        self.rsi_period = 14
        self.rsi_buy = 18           # Decreased from 22 to 18
        self.rsi_sell = 75          
        
        self.min_history = 22

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Update Market Data
        active_symbols = []
        for sym, data in prices.items():
            price = data['priceUsd']
            active_symbols.append(sym)
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_window)
            self.history[sym].append(price)

        # 2. Check Exits (Priority 1: Secure Profits)
        exit_signal = self._scan_exits(prices)
        if exit_signal:
            return exit_signal
            
        # 3. Check Entries (Priority 2: Snipe Dips)
        entry_signal = self._scan_entries(active_symbols, prices)
        if entry_signal:
            return entry_signal
            
        return None

    def _scan_exits(self, prices):
        """
        Strict exit logic: NEVER sell below Entry Price + Threshold.
        This explicitly prevents the 'STOP_LOSS' penalty.
        """
        for sym, amount in list(self.positions.items()):
            if sym not in prices: continue
            
            curr_price = prices[sym]['priceUsd']
            entry_price = self.pos_metadata[sym]['entry_price']
            
            # --- ROI Check ---
            roi = (curr_price - entry_price) / entry_price
            
            # ABSOLUTE SHIELD: If ROI is insufficient, we HOLD.
            # We would rather bag-hold than trigger a penalty.
            if roi < self.min_profit:
                continue

            # If we reach here, the position is safely green.
            hist = list(self.history[sym])
            if len(hist) < self.min_history: continue
            
            upper, mid, lower = self._calc_bb(hist)
            rsi = self._calc_rsi(hist)
            
            # Exit 1: Statistical Reversion (Price > Upper Band)
            if curr_price > upper:
                return self._order(sym, 'SELL', amount, 'TP_BB_UPPER')
                
            # Exit 2: Momentum Climax (RSI > 75)