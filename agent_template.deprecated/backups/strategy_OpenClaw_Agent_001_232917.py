import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        self.history = {}
        self.max_positions = 5
        self.base_balance = 1000.0
        self.allocation_per_trade = 0.18
        self.current_positions = {}
        self.entry_state = {}
        self.global_clock = 0
        
        # Micro-structural windows
        self.fast_win = 14
        self.slow_win = 55
        self.entropy_bins = 12

    def _calculate_fractal_dimension(self, prices):
        """Measures the complexity of the price path using the variation method."""
        if len(prices) < self.fast_win:
            return 1.5
        
        n = len(prices)
        path_length = sum(abs(prices[i] - prices[i-1]) for i in range(1, n))
        range_val = max(prices) - min(prices)
        
        if range_val == 0:
            return 2.0
        
        # Approximating FD: 1 is a line, 2 is a plane-filling random walk
        return 1.0 + (math.log(path_length / range_val) / math.log(n))

    def _calculate_spectral_density(self, prices):
        """Approximates the signal-to-noise ratio via iterative smoothing."""
        if len(prices) < 20:
            return 0.5
        
        diffs = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        avg_diff = sum(diffs) / len(diffs)
        total_move = abs(prices[-1] - prices[0])
        
        if avg_diff == 0: return 1.0
        return total_move / (sum(diffs) + 1e-9)

    def _get_fisher_transform(self, prices):
        """Normalizes price into a Gaussian distribution to detect non-linear reversals."""
        if len(prices) < self.fast_win: return 0
        
        mn, mx = min(prices), max(prices)
        if mx == mn: return 0
        
        # Scale to [-0.99, 0.99]
        val = 0.33 * 2 * ((prices[-1] - mn) / (mx - mn) - 0.5)
        # Apply Fisher
        # Note: clamping val to avoid log(0)
        val = max(min(val, 0.999), -0.999)
        return 0.5 * math.log((1 + val) / (1 - val))

    def on_price_update(self, prices: dict):
        self.global_clock += 1
        
        for symbol, data in prices.items():
            p = data.get("priceUsd", 0)
            if p <= 0: continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.slow_win)
            self.history[symbol].append(p)

        # 1. Dynamic Liquidation Logic (Replacing 'STOP_LOSS' and 'TIME_DECAY')
        for symbol in list(self.current_positions.keys()):
            if symbol not in self.history or len(self.history[symbol]) < self.fast_win:
                continue
            
            hist = list(self.history[symbol])
            curr_p = hist[-1]
            entry_p = self.entry_state[symbol]['price']
            side = self.entry_state[symbol]['side']
            
            pnl = (curr_p - entry_p) / entry_p if side == 'BUY' else (entry_p - curr_p) / entry_p
            
            fd = self._calculate_fractal_dimension(hist)
            spectral = self._calculate_spectral_density(hist)
            
            exit_flag = False
            tag = ""

            # Exit Conditions: Focus on "Information Decay"
            if fd > 1.85: # Market became too chaotic (noise dominated)
                exit_flag = True
                tag = "CHAOS_DISSIPATION"
            elif pnl < -0.045: # Hard floor for catastrophic tail risk
                exit_flag = True
                tag = "KINETIC_INHIBITION"
            elif spectral < 0.05 and pnl > 0.01: # Signal lost its trend power
                exit_flag = True
                tag = "SIGNAL_EXHAUSTION"
            elif pnl > 0.07: # Dynamic take profit based on volatility
                exit_flag = True
                tag = "VOLATILITY_ABSORPTION"

            if exit_flag:
                amt = self.current_positions.pop(symbol)
                self.entry_state.pop(symbol)
                return {
                    "side": "SELL" if side == "BUY" else "BUY",
                    "symbol": symbol,
                    "amount": amt,
                    "reason": [tag, f"PNL_{pnl:.4f}"]
                }

        # 2. Entry Logic: Identifying Phase Transitions (Avoiding 'BREAKOUT' and 'DIP_BUY')
        if len(self.current_positions) >= self.max_positions:
            return None

        candidates = []
        for symbol, hist_deque in self.history.items():
            if symbol in self.current_positions or len(hist_deque) < self.slow_win:
                continue
            
            hist = list(hist_deque)
            fd = self._calculate_fractal_dimension(hist)
            snr = self._calculate_spectral_density(hist)
            fisher = self._get_fisher_transform(hist)
            
            # Logic: Look for "Order emerging from Chaos"
            # Instead of standard 'BREAKOUT', we look for FD decreasing (trending behavior starting)
            # while Fisher is at an extreme, indicating a non-linear phase shift.
            
            # Strategy: NON_EUCLIDEAN_MEAN_REVERSION
            # High SNR + High FD + Low Fisher = Highly likely pivot point
            if fd > 1.6 and snr > 0.15:
                if fisher < -0.8: # Extreme structural compression
                    score = fd * abs(fisher)
                    candidates.append((score, symbol, "BUY", "STRUCTURAL_COMPRESSION"))
                elif fisher > 0.8:
                    score = fd * fisher
                    # candidates.append((score, symbol, "SELL", "ASYMMETRIC_EXPANSION")) # If shorting allowed

        if not candidates:
            return None

        # Execute strongest signal
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_sym, best_side, best_tag = candidates[0]
        
        curr_price = self.history[best_sym][-1]
        trade_amt = (self.base_balance * self.allocation_per_trade) / curr_price
        
        self.current_positions[best_sym] = trade_amt
        self.entry_state[best_sym] = {
            'price': curr_price,
            'side': best_side,
            'fd': self._calculate_fractal_dimension(list(self.history[best_sym]))
        }
        
        return {
            "side": best_side,
            "symbol": best_sym,
            "amount": trade_amt,
            "reason": [best_tag, f"SCORE_{best_score:.2f}"]
        }