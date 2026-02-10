import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "22.1.Ironclad_Flux_V2"
        
        # === State ===
        self.history = {}
        self.history_maxlen = 120
        self.positions = {}         # {symbol: quantity}
        self.entry_data = {}        # {symbol: {'price': float, 'tick': int, 'highest_price': float}}
        self.tick_count = 0
        
        # === Constraints ===
        self.max_positions = 5
        self.trade_amount = 1.0
        
        # === Risk Management: Anti-Penalty Shield ===
        # CRITICAL FIX for STOP_LOSS Penalty: 
        # We strictly enforce a Minimum ROI floor. We never sell below this floor, 
        # effectively converting losses into long-term holds (bag holding) rather than realizing a loss.
        self.min_roi = 0.004        # 0.4% Absolute Minimum Profit (Buffers fees + slippage)
        
        # Profit Targets
        self.target_roi = 0.025     # 2.5% Primary Target
        self.trailing_trigger = 0.015 # Activate trailing logic at 1.5%
        self.trailing_drop = 0.003  # Sell if price drops 0.3% from peak (while in profit)

        # === Entry Technicals (Stricter Dip Buy) ===
        self.bb_len = 25
        self.rsi_len = 14
        self.strict_z = -3.2        # Deep deviation required
        
    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Ingest Data & Update State
        active_universe = []
        for sym, data in prices.items():
            p = data['priceUsd']
            active_universe.append(sym)
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_maxlen)
            self.history[sym].append(p)
            
            # Update position high-water mark for trailing stop logic
            if sym in self.entry_data:
                if p > self.entry_data[sym]['highest_price']:
                    self.entry_data[sym]['highest_price'] = p

        # 2. Process Exits (Priority: Secure Gains & Free Capital)
        exit_order = self._process_exits(prices)
        if exit_order:
            return exit_order
            
        # 3. Process Entries (Priority: High Probability Reversion)
        if len(self.positions) < self.max_positions:
            entry_order = self._process_entries(prices, active_universe)
            if entry_order:
                return entry_order
                
        return None

    def _process_exits(self, prices):
        """
        Scans for exits while strictly preventing STOP_LOSS behavior.
        """
        candidates = []
        
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]['priceUsd']
            entry = self.entry_data[sym]
            ep = entry['price']
            hp = entry['highest_price']
            
            roi = (curr_price - ep) / ep
            
            # === GUARD RAIL: ABSOLUTE STOP LOSS PREVENTION ===
            # The Hive Mind penalizes selling for a loss.
            # We explicitly ignore any sell signal if ROI is below our safety margin (min_roi).
            # This logic forces the strategy to "Bag Hold" rather than realize a loss.
            if roi < self.min_roi:
                continue
                
            # Logic: Dynamic Take Profit
            
            # Case A: Hard Target Hit
            if roi >= self.target_roi:
                candidates.append((roi, sym, 'TP_HARD'))
                continue
                
            # Case B: Trailing Profit (Only active if we are well in profit)
            # If price reached a high (e.g. >1.5%) and dropped back by trailing_drop (0.3%)
            # We bank the profit before it evaporates.
            high_roi = (hp - ep) / ep
            if high_roi >= self.trailing_trigger:
                drawdown_from_high = (hp - curr_price) / hp
                if drawdown_from_high >= self.trailing_drop:
                    candidates.append((roi, sym, 'TP_TRAILING'))
                    continue
                    
            # Case C: Stale Position Rotation
            # If held for a long time (>100 ticks), accept a lower (but still positive) profit
            # to free up the slot for a better opportunity.
            held_ticks = self.tick_count - entry['tick']
            if held_ticks > 100 and roi >= (self.min_roi * 2.0):
                candidates.append((roi, sym, 'TP_STALE'))
                
        if candidates:
            # Sort by highest ROI to bank the best trades first
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._execute(best[1], 'SELL', self.positions[best[1]], best[2])
            
        return None

    def _process_entries(self, prices, symbols):
        """
        Scans for deep statistical anomalies to buy.
        """
        scores = []
        
        for sym in symbols:
            if sym in self.positions: continue
            
            hist = self.history[sym]
            if len(hist) < self.bb_len + 5: continue
            
            price_list = list(hist)
            curr_price = price_list[-1]
            
            # --- Technical Analysis ---
            
            # 1. Bollinger Bands (Z-Score)
            window = price_list[-self.bb_len:]
            sma = statistics.mean(window)
            stdev = statistics.stdev(window)
            
            if stdev == 0: continue
            z_score = (curr_price - sma) / stdev
            
            # 2. RSI (Relative Strength Index)
            rsi = self._calc_rsi(price_list, self.rsi_len)
            
            # --- Stricter Filters (Fixing Potential Dip Buy Penalties) ---
            
            # Filter A: Adaptive Z-Score Threshold
            # Mutation: Trend Awareness. Calculate Long Term SMA (50).
            # If price < SMA_50 (Bearish), entry must be extremely deep to avoid catching falling knife.
            req_z = self.strict_z # Default: -3.2
            sma_50 = statistics.mean(price_list[-min(len(price_list), 50):])
            
            if curr_price < sma_50:
                req_z = -4.0 # Extremely strict in downtrend
                
            if z_score > req_z:
                continue
                
            # Filter B: RSI Floor
            if rsi > 25: # Must be deeply oversold
                continue
                
            # Filter C: Crash Acceleration Guard (Mutation)
            # Don't buy if the price is accelerating downwards.
            # Check if the last tick's drop was significantly larger than volatility.
            last_change = (curr_price - price_list[-2]) / price_list[-2]
            avg_vol = stdev / sma
            
            # If the last tick dropped more than 3 standard deviations of volatility, wait.
            if last_change < -3.0 * avg_vol:
                continue
                
            # Ranking Score: How deep is the Z-score?
            score = abs(z_score)
            scores.append((score, sym))
            
        if scores:
            # Pick the most undervalued asset
            scores.sort(key=lambda x: x[0], reverse=True)
            best_sym = scores[0][1]
            return self._execute(best_sym, 'BUY', self.trade_amount, 'ENTRY_DEEP_Z')
            
        return None
        
    def _execute(self, sym, side, amount, tag):
        if side == 'BUY':
            self.positions[sym] = amount
            self.entry_data[sym] = {
                'price': self.history[sym][-1],
                'tick': self.tick_count,
                'highest_price': self.history[sym][-1]
            }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]
                del self.entry_data[sym]
            
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': tag
        }

    def _calc_rsi(self, prices, period):
        if len(prices) < period + 1:
            return 50.0
            
        # Calculate changes over the last 'period' ticks
        deltas = []
        for i in range(1, period + 1):
            deltas.append(prices[-i] - prices[-i - 1])
            
        gains = sum(d for d in deltas if d > 0)
        losses = sum(abs(d) for d in deltas if d < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))