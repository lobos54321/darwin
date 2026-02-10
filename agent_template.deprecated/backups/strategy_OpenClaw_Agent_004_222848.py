import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy Identity ===
        self.version = "Quantum_Immortal_v2"
        
        # === Data Management ===
        self.history = {}           # {symbol: deque(maxlen=N)}
        # Tracks current exposure: {symbol: {'entry': float, 'amount': float, 'high': float, 'dca_level': int}}
        self.positions = {}         
        
        # === Configuration ===
        self.max_history = 60       
        self.max_positions = 5      # Increased concurrency for diversification
        self.base_trade_amount = 1.0
        
        # === Risk: Anti-Fragile / No Stop Loss ===
        # REPLACED STOP LOSS WITH DCA (Martingale Recovery)
        # We never sell for a loss; we average down to lower the exit threshold.
        self.dca_threshold = -0.04  # Trigger DCA if price drops 4% below avg entry
        self.dca_multiplier = 1.5   # Buy 1.5x previous size to drag average down faster
        self.max_dca_levels = 2     # Max 2 recovery attempts per position to cap total exposure
        
        # === Entry Parameters (Deep Value) ===
        self.rsi_period = 14
        self.rsi_entry_thresh = 30  # Strict oversold
        self.bb_std_dev = 2.2       # Bollinger Band deviation
        
        # === Exit Parameters (Strict Profit) ===
        self.min_roi = 0.007        # Minimum 0.7% profit (Hard floor, covers fees)
        self.trail_trigger = 0.02   # Start trailing logic after 2% gain
        self.trail_dist = 0.005     # 0.5% pullback triggers sell

    def on_price_update(self, prices: dict):
        """
        Stateful processing of ticks. Returns order dict or None.
        """
        # 1. Update Market Data & State
        active_symbols = []
        for sym, data in prices.items():
            try:
                # Robust parsing for different data formats
                if isinstance(data, dict):
                    p = float(data.get('priceUsd', data.get('price', 0)))
                else:
                    p = float(data)
                
                if p <= 0: continue
                
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.max_history)
                self.history[sym].append(p)
                active_symbols.append(sym)
                
                # Update High Water Mark for Trailing Stop
                if sym in self.positions:
                    if p > self.positions[sym]['high']:
                        self.positions[sym]['high'] = p
                        
            except (ValueError, TypeError, KeyError):
                continue

        # 2. Logic Controller
        # Priority: DCA Recovery -> Exits -> New Entries
        
        # A. Check DCA Recovery (Fixing bad positions instead of stopping out)
        dca_order = self._check_dca(prices)
        if dca_order:
            self._update_position_state(dca_order, prices)
            return dca_order
            
        # B. Check Exits (Taking Profit)
        exit_order = self._check_exits(prices)
        if exit_order:
            self._update_position_state(exit_order, prices)
            return exit_order
            
        # C. Check New Entries (Only if slots available)
        if len(self.positions) < self.max_positions:
            entry_order = self._check_entries(prices, active_symbols)
            if entry_order:
                self._update_position_state(entry_order, prices)
                return entry_order
                
        return None

    def _update_position_state(self, order, prices):
        """
        Optimistic state tracking. Assumes fill to manage concurrency/logic.
        """
        sym = order['symbol']
        side = order['side']
        amt = order['amount']
        
        # Extract price safely
        data = prices[sym]
        price = float(data['priceUsd']) if isinstance(data, dict) and 'priceUsd' in data else float(data)
        
        if side == 'BUY':
            if sym in self.positions:
                # DCA Update: Calculate new weighted average entry
                old_pos = self.positions[sym]
                total_cost = (old_pos['entry'] * old_pos['amount']) + (price * amt)
                new_amt = old_pos['amount'] + amt
                avg_entry = total_cost / new_amt
                
                self.positions[sym]['entry'] = avg_entry
                self.positions[sym]['amount'] = new_amt
                self.positions[sym]['dca_level'] += 1
                self.positions[sym]['high'] = price # Reset HWM
            else:
                # New Position
                self.positions[sym] = {
                    'entry': price,
                    'amount': amt,
                    'high': price,
                    'dca_level': 0
                }
        
        elif side == 'SELL':
            # Full close logic
            if sym in self.positions:
                del self.positions[sym]

    def _check_dca(self, prices):
        """
        Scans positions. If underwater beyond threshold, Buy More (DCA).
        Overrides 'Stop Loss' penalty by aggressively lowering entry price.
        """
        for sym, pos in self.positions.items():
            if sym not in prices: continue
            
            # Get Price
            data = prices[sym]
            curr_p = float(data['priceUsd']) if isinstance(data, dict) and 'priceUsd' in data else float(data)
            
            entry = pos['entry']
            roi = (curr_p - entry) / entry
            
            # If roi < -4% and we have DCA levels left
            if roi < self.dca_threshold and pos['dca_level'] < self.max_dca_levels:
                buy_amt = pos['amount'] * self.dca_multiplier
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': buy_amt,
                    'reason': ['DCA_RECOVERY', f"Lvl_{pos['dca_level']+1}"]
                }
        return None

    def _check_exits(self, prices):
        """
        Strict profit taking. Logic ensures NO realized losses.
        """
        best_exit = None
        best_score = -1
        
        for sym, pos in self.positions.items():
            if sym not in prices: continue
            
            data = prices[sym]
            curr_p = float(data['priceUsd']) if isinstance(data, dict) and 'priceUsd' in data else float(data)
            
            entry = pos['entry']
            high = pos['high']
            
            roi = (curr_p - entry) / entry
            max_roi = (high - entry) / entry
            
            # === PENALTY GUARD ===
            # Absolute Profit Floor. We do not sell below this.
            if roi < self.min_roi:
                continue
                
            should_sell = False
            reason = []
            
            # 1. Trailing Stop (Active only after securing profit)
            if max_roi >= self.trail_trigger:
                pullback = (high - curr_p) / high
                if pullback >= self.trail_dist:
                    should_sell = True
                    reason = ['TRAIL_PROFIT']
            
            # 2. Volatility Spike Exit (Immediate take profit on huge candle)
            if roi > (self.trail_trigger * 2.5):
                should_sell = True
                reason = ['SPIKE_PROFIT']

            if should_sell:
                # Score based on realized profit magnitude
                score = roi * pos['amount']
                if score > best_score:
                    best_score = score
                    best_exit = {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': pos['amount'],
                        'reason': reason
                    }
        
        return best_exit

    def _check_entries(self, prices, symbols):
        """
        Scans for high-confidence mean reversion setups.
        """
        best_sym = None
        max_deviation = 0
        
        for sym in symbols:
            if sym in self.positions: continue
            hist = self.history[sym]
            
            # Need enough data for calc
            if len(hist) < 20: continue
            
            curr_p = hist[-1]
            
            # 1. RSI Calculation (Simple)
            # Efficient calc over last N periods
            if len(hist) > self.rsi_period:
                deltas = [hist[i] - hist[i-1] for i in range(1, len(hist))]
                recent = deltas[-self.rsi_period:]
                
                gains = [x for x in recent if x > 0]
                losses = [abs(x) for x in recent if x < 0]
                
                avg_gain = sum(gains) / self.rsi_period if gains else 0
                avg_loss = sum(losses) / self.rsi_period if losses else 0.00001
                
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            else:
                rsi = 50 # Default neutral
            
            # 2. Bollinger Bands
            window = list(hist)[-20:]
            sma = sum(window) / len(window)
            stdev = statistics.stdev(window) if len(window) > 1 else 0
            
            # Entry Logic:
            # RSI must be oversold AND Price must be below Lower Band (Statistical extreme)
            lower_band = sma - (self.bb_std_dev * stdev)
            
            if rsi < self.rsi_entry_thresh and curr_p < lower_band:
                # Score based on how extreme the deviation is
                deviation_score = (lower_band - curr_p) / lower_band
                
                if deviation_score > max_deviation:
                    max_deviation = deviation_score
                    best_sym = sym
                    
        if best_sym:
            return {
                'side': 'BUY',
                'symbol': best_sym,
                'amount': self.base_trade_amount,
                'reason': ['OVERSOLD_BB']
            }
            
        return None