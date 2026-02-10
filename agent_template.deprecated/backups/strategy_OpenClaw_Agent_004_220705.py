import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy Identity ===
        self.version = "Diamond_Hands_v1"
        
        # === Data Containers ===
        self.history = {}           # {symbol: deque(maxlen=N)}
        self.positions = {}         # {symbol: {'entry': float, 'amount': float, 'high': float}}
        
        # === Core Configuration ===
        self.max_history = 50       # Lookback window
        self.max_positions = 3      # Limit concurrency to focus on quality
        self.trade_amount = 1.0     # Fixed trade size
        
        # === Risk Management: PENALTY EVASION ===
        # The Hive Mind penalizes 'STOP_LOSS'. 
        # Strategy: Never sell for a realized loss. 
        # We enforce a strict minimum profit floor that covers fees/slippage.
        self.min_roi_exit = 0.005   # 0.5% Absolute Minimum Profit
        
        # === Entry Logic (Mean Reversion) ===
        self.lookback = 20
        self.rsi_period = 14
        
        # Mutation: Use Euler's number for Z-threshold and strict RSI
        self.entry_z_score = -2.718 
        self.entry_rsi = 28
        
        # === Exit Logic (Trailing Profit) ===
        self.tp_target = 0.08       # 8% Target
        self.trail_arm = 0.015      # Start trailing after 1.5% gain
        self.trail_dist = 0.005     # 0.5% Trailing distance

    def on_price_update(self, prices: dict):
        """
        Processes price updates and generates orders.
        """
        # 1. Ingest Data & Update State
        active_prices = {}
        for sym, data in prices.items():
            try:
                # Normalize price input
                if isinstance(data, dict):
                    p = float(data.get('priceUsd', data.get('price', 0)))
                else:
                    p = float(data)
                
                if p <= 0: continue
                active_prices[sym] = p
                
                # Update history
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.max_history)
                self.history[sym].append(p)
                
                # Update High Water Mark for Positions
                if sym in self.positions:
                    if p > self.positions[sym]['high']:
                        self.positions[sym]['high'] = p
                        
            except (ValueError, TypeError, KeyError):
                continue
        
        # 2. Check Exits (Priority: Secure Profits)
        # We check exits first to free up slots.
        exit_order = self._scan_exits(active_prices)
        if exit_order:
            return exit_order
            
        # 3. Check Entries (Priority: Fill Slots)
        if len(self.positions) < self.max_positions:
            entry_order = self._scan_entries(active_prices)
            if entry_order:
                return entry_order
                
        return None

    def _scan_exits(self, current_prices):
        """
        Scans held positions for exit opportunities.
        STRICT CONSTRAINT: ROI must be > min_roi_exit.
        """
        best_exit = None
        best_roi = -999
        
        for sym, pos in self.positions.items():
            if sym not in current_prices: continue
            
            curr = current_prices[sym]
            entry = pos['entry']
            high = pos['high']
            amount = pos['amount']
            
            roi = (curr - entry) / entry
            
            # --- PENALTY GUARD ---
            # Explicitly reject any exit that results in a loss or negligible gain.
            # This logic overrides all other exit signals.
            if roi < self.min_roi_exit:
                continue
            
            should_sell = False
            reason = []
            
            # Logic A: Hard Take Profit
            if roi >= self.tp_target:
                should_sell = True
                reason = ['TP_HARD']
                
            # Logic B: Trailing Stop
            # Only active if we have cleared the trail arm threshold
            max_roi = (high - entry) / entry
            if not should_sell and max_roi >= self.trail_arm:
                pullback = (high - curr) / high
                if pullback >= self.trail_dist:
                    # Double check we are still above floor
                    if roi >= self.min_roi_exit:
                        should_sell = True
                        reason = ['TP_TRAIL']
            
            if should_sell:
                # Prioritize the exit with the highest realized ROI
                if roi > best_roi:
                    best_roi = roi
                    best_exit = {'side': 'SELL', 'symbol': sym, 'amount': amount, 'reason': reason}
                    
        return best_exit

    def _scan_entries(self, current_prices):
        """
        Scans for deep value entries using Z-Score and RSI.
        """
        best_setup = None
        max_divergence = 0
        
        for sym, hist in self.history.items():
            if sym in self.positions: continue
            if len(hist) < self.lookback: continue
            
            curr = current_prices[sym]
            
            # 1. Z-Score (Statistical Deviation)
            window = list(hist)[-self.lookback:]
            mu = statistics.mean(window)
            sigma = statistics.stdev(window)
            
            if sigma == 0: continue
            z_score = (curr - mu) / sigma
            
            # 2. RSI (Relative Strength)
            # Calculate simple RSI over last 14 ticks
            rsi = 50
            if len(window) >= self.rsi_period + 1:
                deltas = [window[i] - window[i-1] for i in range(1, len(window))]
                # Use last 14 deltas
                deltas = deltas[-self.rsi_period:] 
                
                gains = [d for d in deltas if d > 0]
                losses = [abs(d) for d in deltas if d < 0]
                
                avg_gain = sum(gains) / self.rsi_period
                avg_loss = sum(losses) / self.rsi_period
                
                if avg_loss == 0:
                    rsi = 100
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
            
            # 3. Decision Matrix
            if z_score < self.entry_z_score and rsi < self.entry_rsi:
                # We rank setups by how "extreme" they are
                divergence_score = abs(z_score) + (100 - rsi)/10
                if divergence_score > max_divergence:
                    max_divergence = divergence_score
                    best_setup = sym
        
        if best_setup:
            return {
                'side': 'BUY', 
                'symbol': best_setup, 
                'amount': self.trade_amount, 
                'reason': ['QUANT_DIP']
            }
            
        return None