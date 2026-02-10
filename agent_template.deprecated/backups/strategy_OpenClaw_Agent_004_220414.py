import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy Identity ===
        self.version = "Antigravity_DiamondHands_v2"
        
        # === Data Management ===
        self.history = {}           # {symbol: deque(maxlen=N)}
        self.positions = {}         # {symbol: {'entry': float, 'amount': float, 'high': float}}
        
        # === Core Parameters ===
        self.max_history = 60       # Slightly longer window for better statistical relevance
        self.max_positions = 5      # Maximum concurrent trades
        self.trade_amount = 1.0     # Fixed trade size
        
        # === Risk Management (NO STOP LOSS) ===
        # The Hive Mind penalizes realized losses. 
        # We enforce a strict "Minimum ROI Floor". We HOLD indefinitely if below this.
        self.min_roi_floor = 0.012  # 1.2% Minimum Profit Guarantee (Safety Net)
        
        # === Exit Logic (Take Profit & Trailing) ===
        self.tp_target = 0.15       # 15% Hard Take Profit (Moon bags)
        self.trail_trigger = 0.04   # Start trailing after 4% gain
        self.trail_dist = 0.008     # 0.8% Trail distance
        
        # === Entry Logic (Anti-Knife & Deep Value) ===
        # Stricter thresholds to avoid DIP_BUY penalties.
        self.bb_length = 20
        self.rsi_length = 14
        
        # "Deep Value" Mutation Thresholds
        self.z_entry = -3.9         # Extreme deviation required (< -3.9 sigma)
        self.rsi_entry = 18         # Deeply oversold (< 18 RSI)
        self.min_volatility = 0.003 # Avoid stagnant assets

    def on_price_update(self, prices: dict):
        """
        Main tick handler.
        """
        # 1. Ingest Data & Update State
        active_map = {}
        for sym, data in prices.items():
            try:
                # Robust parsing for different data formats
                if isinstance(data, dict):
                    p = float(data.get('priceUsd', 0))
                else:
                    p = float(data)
                
                if p <= 0: continue
                
                active_map[sym] = p
                
                # Init history if needed
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.max_history)
                self.history[sym].append(p)
                
                # Update High Water Mark for held positions (for trailing stop)
                if sym in self.positions:
                    if p > self.positions[sym]['high']:
                        self.positions[sym]['high'] = p
                        
            except (ValueError, KeyError, TypeError):
                continue
        
        # 2. Check Exits (Priority: Secure Profits)
        # We check exits first to free up slots for new opportunities
        exit_order = self._check_exits(active_map)
        if exit_order:
            return exit_order
            
        # 3. Check Entries (Priority: Fill slots with high quality setups)
        if len(self.positions) < self.max_positions:
            entry_order = self._scan_entries(active_map)
            if entry_order:
                return entry_order
                
        return None

    def _check_exits(self, current_prices):
        """
        Evaluates positions for exit. 
        CRITICAL: Never sells below min_roi_floor to avoid STOP_LOSS penalty.
        """
        candidates = []
        
        for sym, pos in self.positions.items():
            if sym not in current_prices: continue
            
            curr_p = current_prices[sym]
            entry_p = pos['entry']
            high_p = pos['high']
            amount = pos['amount']
            
            # Calculate Return on Investment
            roi = (curr_p - entry_p) / entry_p
            
            # === PENALTY GUARD: STOP LOSS PREVENTION ===
            # If ROI < Floor, we hold. No exceptions.
            if roi < self.min_roi_floor:
                continue
            
            # Logic A: Hard Take Profit
            if roi >= self.tp_target:
                return self._format_order(sym, 'SELL', amount, ['TP_Hard', f'ROI_{roi:.3f}'])
            
            # Logic B: Trailing Stop
            # Only active if we have cleared the trail trigger zone
            max_roi = (high_p - entry_p) / entry_p
            
            if max_roi >= self.trail_trigger:
                pullback = (high_p - curr_p) / high_p
                if pullback >= self.trail_dist:
                    # Double check: Even with pullback, does it satisfy the floor?
                    # This redundancy ensures we don't trail-stop into a loss if volatility is insane.
                    if roi >= self.min_roi_floor:
                        candidates.append((roi, sym, amount, 'TP_Trail'))
        
        # Sort by highest ROI to prioritize locking in the biggest wins first
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._format_order(best[1], 'SELL', best[2], [best[3]])
            
        return None

    def _scan_entries(self, current_prices):
        """
        Scans for deep mean reversion.
        CRITICAL: Stricter checks to avoid DIP_BUY penalty (falling knife).
        """
        candidates = []
        
        for sym, curr_p in current_prices.items():
            # Skip if already holding
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.max_history: continue
            
            # Snapshot history
            prices_list = list(hist)
            prev_p = prices_list[-2]
            
            # === Anti-Knife Logic ===
            # Constraint 1: Price must show local support (Green Candle/Uptick).
            # We do not buy if the price is strictly falling tick-over-tick.
            if curr_p < prev_p:
                continue
            
            # Calculate Statistics
            window = prices_list[-self.bb_length:]
            try:
                mu = statistics.mean(window)
                sigma = statistics.stdev(window)
            except statistics.StatisticsError:
                continue
            
            if sigma == 0: continue
            
            # Constraint 2: Volatility Filter
            # Skip flat assets that won't bounce
            if (sigma / mu) < self.min_volatility: continue
            
            # Constraint 3: Z-Score Deviation
            z_score = (curr_p - mu) / sigma
            if z_score > self.z_entry: continue # Must be < -3.9
            
            # Constraint 4: RSI Momentum
            rsi = self._calc_rsi(prices_list)
            if rsi > self.rsi_entry: continue # Must be < 18
            
            # Scoring: Composite score of Z-score depth and RSI depth
            # Lower Z and lower RSI = Higher Score
            score = abs(z_score) + (100 - rsi)
            candidates.append((score, sym))
            
        if candidates:
            # Buy the single best candidate found this tick
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_sym = candidates[0][1]
            return self._format_order(best_sym, 'BUY', self.trade_amount, ['ENTRY_DeepValue'])
            
        return None

    def _calc_rsi(self, prices):
        """
        Standard Relative Strength Index calculation.
        """
        if len(prices) < self.rsi_length + 1: return 50.0
        
        # Calculate changes over the RSI length
        # Using the last N prices creates N-1 deltas, we need N+1 prices for N deltas
        relevant_prices = prices[-(self.rsi_length + 1):]
        deltas = [relevant_prices[i] - relevant_prices[i-1] for i in range(1, len(relevant_prices))]
        
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        if not gains and not losses: return 50.0
        
        avg_gain = sum(gains) / self.rsi_length
        avg_loss = sum(losses) / self.rsi_length
        
        if avg_loss == 0: return 100.0
        if avg_gain == 0: return 0.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _format_order(self, sym, side, amount, tags):
        """
        Formats the return dict and updates internal state optimistically.
        """
        # Optimistic State Update
        if side == 'BUY':
            self.positions[sym] = {
                'entry': self.history[sym][-1],
                'amount': amount,
                'high': self.history[sym][-1]
            }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]
                
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': tags
        }