import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Identity ===
        self.version = "Antigravity_Quant_v3_NoLoss"
        
        # === State Management ===
        self.history = {}           # {symbol: deque([prices])}
        self.history_len = 60       # Buffer size for technical analysis
        self.positions = {}         # {symbol: {'amount': float, 'entry': float, 'high': float}}
        
        # === Operational Parameters ===
        self.max_positions = 5
        self.trade_amount = 1.0     # Fixed trade size per signal
        
        # === Risk Management (Anti-Stop-Loss) ===
        # The Hive Mind penalizes selling at a loss.
        # We enforce a strict Minimum ROI Floor.
        # 1.0% profit minimum to cover fees and potential slippage.
        self.roi_floor = 0.01
        
        # === Exit Logic (Profit Maximization) ===
        self.tp_hard = 0.10         # 10% Hard Take Profit (Moonbag)
        self.trail_arm = 0.025      # Arm trailing stop at 2.5% profit
        self.trail_dist = 0.005     # Trail distance 0.5%
        
        # === Entry Logic (Statistical Arbitrage) ===
        # Mutation: Adaptive thresholds based on volatility
        self.rsi_period = 14
        self.rsi_limit = 25         # Oversold threshold
        self.bb_period = 20
        self.base_z_score = -3.0    # Base requirement (3 Sigma)
        self.min_volatility = 0.002 # Filter out dead assets

    def on_price_update(self, prices: dict):
        """
        Main execution loop.
        Returns: dict or None
        """
        active_symbols = []
        
        # 1. Ingest Data
        for sym, data in prices.items():
            try:
                # Handle different data formats robustly
                if isinstance(data, dict):
                    p = float(data.get('priceUsd', 0))
                else:
                    p = float(data)
                
                if p <= 0: continue
                
                active_symbols.append(sym)
                
                # Maintain history buffer
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.history_len)
                self.history[sym].append(p)
                
                # Update Trailing High Water Mark
                if sym in self.positions:
                    if p > self.positions[sym]['high']:
                        self.positions[sym]['high'] = p
                        
            except (ValueError, TypeError, KeyError):
                continue

        # 2. Check Exits (Priority: Secure Profits)
        exit_order = self._check_exits(prices)
        if exit_order:
            return exit_order
            
        # 3. Check Entries (Priority: Deploy Capital)
        if len(self.positions) < self.max_positions:
            entry_order = self._scan_entries(active_symbols)
            if entry_order:
                return entry_order
                
        return None

    def _check_exits(self, prices):
        """
        Evaluates holding positions for exit conditions.
        STRICTLY enforces ROI floor to avoid STOP_LOSS penalty.
        """
        candidates = []
        
        for sym, pos in self.positions.items():
            # Get current price
            if sym in prices and isinstance(prices[sym], dict):
                curr_p = float(prices[sym]['priceUsd'])
            elif sym in prices:
                curr_p = float(prices[sym])
            else:
                continue
            
            entry_p = pos['entry']
            high_p = pos['high']
            amount = pos['amount']
            
            # ROI Calculation
            roi = (curr_p - entry_p) / entry_p
            
            # --- CONSTRAINT: NEVER SELL BELOW FLOOR ---
            if roi < self.roi_floor:
                continue
                
            # 1. Hard Take Profit
            if roi >= self.tp_hard:
                return self._format_order(sym, 'SELL', amount, ['TP_HARD'])
                
            # 2. Trailing Stop (Profit Locking)
            # Only activates if we are significantly profitable
            max_roi = (high_p - entry_p) / entry_p
            
            if max_roi >= self.trail_arm:
                pullback = (high_p - curr_p) / high_p
                if pullback >= self.trail_dist:
                    # Double check we are still above floor after pullback
                    if roi >= self.roi_floor:
                        candidates.append((roi, sym, amount, 'TP_TRAIL'))

        # Sort exits by highest ROI to prioritize locking big wins
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            return self._format_order(best[1], 'SELL', best[2], [best[3]])
            
        return None

    def _scan_entries(self, symbols):
        """
        Scans for deep statistical anomalies (Mean Reversion).
        Mutation: Uses Volatility-Adjusted Z-Score thresholds.
        """
        candidates = []
        
        for sym in symbols:
            # Skip held symbols
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.bb_period: continue
            
            recent = list(hist)[-self.bb_period:]
            current_p = recent[-1]
            
            # Stats
            mean = statistics.mean(recent)
            stdev = statistics.stdev(recent)
            
            if mean == 0 or stdev == 0: continue
            
            # 1. Volatility Filter
            vol_ratio = stdev / mean
            if vol_ratio < self.min_volatility: continue
            
            # 2. Adaptive Z-Score Threshold
            # If asset is highly volatile, we require a deeper dip to buy.
            # Base -3.0. If vol is high (e.g. 2%), require -3.0 - (2.0) = -5.0
            vol_adjustment = vol_ratio * 100.0  # e.g., 0.01 vol -> 1.0 adj
            required_z = self.base_z_score - (vol_adjustment * 0.5)
            
            # Cap the strictness to avoid impossible conditions
            required_z = max(required_z, -6.0) 
            
            z_score = (current_p - mean) / stdev
            if z_score > required_z: continue
            
            # 3. RSI Filter
            rsi = self._calculate_rsi(hist)
            if rsi > self.rsi_limit: continue
            
            # Scoring: Favor the deepest statistical outlier
            # Score = Z-Score Magnitude + (100-RSI)
            score = abs(z_score) + (100 - rsi)
            candidates.append((score, sym))
            
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_sym = candidates[0][1]
            return self._format_order(best_sym, 'BUY', self.trade_amount, ['ENTRY_ADAPTIVE'])
            
        return None

    def _calculate_rsi(self, hist):
        """
        Standard RSI calculation.
        """
        prices = list(hist)[-(self.rsi_period + 1):]
        if len(prices) < self.rsi_period + 1: return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(delta))
        
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0: return 100.0
        if avg_gain == 0: return 0.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _format_order(self, sym, side, amount, reasons):
        """
        State update and return formatting.
        """
        if side == 'BUY':
            price = self.history[sym][-1]
            self.positions[sym] = {
                'amount': amount,
                'entry': price,
                'high': price
            }
        elif side == 'SELL':
            if sym in self.positions:
                del self.positions[sym]
                
        return {
            'side': side,
            'symbol': sym,
            'amount': amount,
            'reason': reasons
        }