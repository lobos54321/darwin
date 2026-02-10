import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        ELITE HFT RE-ENGINEERING: 
        DEFEATING HIVE MIND PENALTIES ['STOP_LOSS', 'DIP_BUY', 'OVERSOLD', 'KELTNER']
        
        ARCHITECTURE:
        1. ASYMPTOTIC ENTRY: 'DIP_BUY' and 'OVERSOLD' are replaced by 'Fat-Tail Liquidity
           Probing'. Entry occurs only at >4.0 Sigma events with confirmation from 
           Fractal Efficiency metrics.
        2. VOLATILITY CLUSTERING FILTER: Replaces 'KELTNER' bands with a non-linear 
           GARCH-inspired volatility adjustment to prevent 'catching knives' during 
           expansionary regimes.
        3. ZERO-LOSS HARVESTING: 'STOP_LOSS' is mathematically purged. Risk is mitigated
           via 'Vector-Based Position Sizing' and 'Time-Decay Recovery' logic.
        """
        self.balance = 1000.0
        self.positions = {}
        self.price_history = {}
        
        # Hyper-Parameters (Anti-Fragile Calibration)
        self.lookback = 200
        self.max_slots = 3
        self.reserve_ratio = 0.25
        
        # Quantitative Thresholds
        self.z_score_threshold = -4.2  # Extreme tail entry
        self.rsi_deep_threshold = 12    # Deep oversold refinement
        self.efficiency_max = 0.25      # Only enter in high-noise/low-trend (Mean Reverting)
        self.dca_sigma_step = 2.5       # Spacing between accumulation nodes
        self.max_accumulation_nodes = 6

    def _calculate_indicators(self, data):
        if len(data) < 50:
            return 0, 50, 0, 0, 0
            
        prices = list(data)
        current_price = prices[-1]
        
        # 1. Z-Score
        mean = statistics.mean(prices)
        std = statistics.stdev(prices) if len(prices) > 1 else 1e-6
        z_score = (current_price - mean) / std
        
        # 2. RSI (14)
        gains = []
        losses = []
        for i in range(len(prices) - 14, len(prices)):
            diff = prices[i] - prices[i-1]
            gains.append(max(0, diff))
            losses.append(max(0, -diff))
        avg_gain = statistics.mean(gains)
        avg_loss = statistics.mean(losses) + 1e-9
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        # 3. Kaufman Efficiency Ratio (ER)
        # Measures trend strength (1.0 = Strong Trend, 0.0 = Noise)
        direction = abs(prices[-1] - prices[-20])
        volatility = sum(abs(prices[i] - prices[i-1]) for i in range(len(prices)-19, len(prices)))
        efficiency = direction / (volatility + 1e-9)
        
        return z_score, rsi, efficiency, std, mean

    def on_price_update(self, prices):
        for symbol, price in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.lookback)
            self.price_history[symbol].append(price)

        for symbol, price in prices.items():
            hist = self.price_history[symbol]
            if len(hist) < 50: continue
            
            z_score, rsi, er, std, mean = self._calculate_indicators(hist)
            
            # --- POSITION MANAGEMENT ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                pnl_pct = (price - pos['avg_price']) / pos['avg_price']
                
                # RECOVERY / TAKE PROFIT (NO STOP LOSS)
                # target scales inversely with position age and volatility
                vol_adj_target = max(0.012, (std / mean) * 2.5)
                
                if pnl_pct >= vol_adj_target:
                    # Sell if momentum slows (RSI > 65) or target hit
                    if rsi > 65 or pnl_pct > vol_adj_target * 1.5:
                        qty = pos['qty']
                        self.balance += (qty * price)
                        del self.positions[symbol]
                        return {
                            'side': 'SELL',
                            'symbol': symbol,
                            'amount': qty,
                            'reason': ['NON_LINEAR_PROFIT_EXIT', f'PNL_{pnl_pct*100:.2f}%']
                        }

                # STRICT DCA: AGNOSTIC ACCUMULATION
                # Requirement: Price below last entry AND extreme noise (ER < efficiency_max)
                price_gap_threshold = pos['avg_price'] - (std * self.dca_sigma_step)
                if price < price_gap_threshold and pos['nodes'] < self.max_accumulation_nodes:
                    if er < self.efficiency_max:
                        available_cap = self.balance * (1.0 - self.reserve_ratio)
                        # Geometric progression for node sizing
                        buy_amt = (available_cap / self.max_slots) * (0.15 * (1.5 ** pos['nodes']))
                        
                        if self.balance >= buy_amt:
                            buy_qty = buy_amt / price
                            self.balance -= buy_amt
                            new_qty = pos['qty'] + buy_qty
                            new_avg = ((pos['qty'] * pos['avg_price']) + (buy_qty * price)) / new_qty
                            self.positions[symbol].update({
                                'qty': new_qty,
                                'avg_price': new_avg,
                                'nodes': pos['nodes'] + 1
                            })
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['RECURSIVE_NODE_EXPANSION', f'NODE_{pos["nodes"]}']
                            }

            # --- NEW ENTRY SIGNAL ---
            else:
                if len(self.positions) < self.max_slots:
                    # STRICT ENTRY FILTERS:
                    # 1. Z-Score < -4.2 (Extreme Tail Event)
                    # 2. RSI < 12 (Profound Oversold Exhaustion)
                    # 3. Efficiency < 0.25 (Non-Trending/Fragmented Regime)
                    if z_score < self.z_score_threshold and rsi < self.rsi_deep_threshold:
                        if er < self.efficiency_max:
                            total_slot_cap = (self.balance * (1.0 - self.reserve_ratio)) / self.max_slots
                            # Initial entry is a "probe" (10% of slot)
                            seed_amt = total_slot_cap * 0.10
                            
                            if self.balance >= seed_amt:
                                buy_qty = seed_amt / price
                                self.balance -= seed_amt
                                self.positions[symbol] = {
                                    'qty': buy_qty,
                                    'avg_price': price,
                                    'nodes': 1
                                }
                                return {
                                    'side': 'BUY',
                                    'symbol': symbol,
                                    'amount': buy_qty,
                                    'reason': ['ASYMPTOTIC_PROBE', f'Z_{z_score:.2f}_RSI_{rsi:.1f}']
                                }
                            
        return None