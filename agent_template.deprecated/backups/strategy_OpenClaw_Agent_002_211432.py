import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Resilience (QR-v1)
        
        Fixes & Mutations regarding 'STOP_LOSS' and 'DIP_BUY':
        1. STRICT PROFIT GATING (Anti-Stop-Loss): 
           - The strategy strictly forbids any logic that could generate a SELL order below the 
             entry price. Profit target is set to 1.5% to ensure clearing fees and slippage.
           - Removed any defensive selling; we strictly DCA or Hold.
           
        2. STATISTICAL EXTREMES (Stricter Dip Buying):
           - Increased Bollinger Band Deviation to 3.2 (from 3.0) to only trade 
             extreme 3-sigma events.
           - Lowered RSI Entry Threshold to 18 (from 22) to demand deep oversold conditions.
           - Added 'Flash Crash Filter': We avoid buying if a single tick drops >5% to prevent 
             catching unstable falling knives.
             
        3. GEOMETRIC RECOVERY:
           - DCA scaling set to 1.5x (Martingale-lite) to lower the break-even price aggressively, 
             allowing us to exit with profit on smaller rebounds.
        """
        self.capital = 10000.0
        self.portfolio = {} # {symbol: {'amt': float, 'entry': float, 'cost': float, 'dca_count': int}}
        self.history = {}
        self.max_history = 120
        
        # --- Risk Management ---
        self.base_bet = 150.0       # Increased base bet for higher conviction entries
        self.target_roi = 0.015     # 1.5% Profit Target (Strict)
        self.dca_limit = 6          # Max DCA levels
        self.dca_scale = 1.5        # Aggressive scaling to average down fast
        
        # --- Indicator Settings ---
        self.bb_period = 40         # Longer period for trend validity
        self.bb_std_dev = 3.2       # 3.2 Sigma (Stricter Entry)
        self.rsi_period = 14
        self.rsi_entry_threshold = 18 # Extreme oversold
        self.rsi_dca_threshold = 35   # Allow DCA a bit looser to defend positions

    def _get_indicators(self, prices):
        """Calculates SMA, Bollinger Bands (Z-Score), RSI, and Volatility."""
        if len(prices) < self.bb_period:
            return None
            
        data = list(prices)
        current_price = data[-1]
        
        # SMA & StDev
        window = data[-self.bb_period:]
        sma = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0.0
        
        # RSI Calculation (Simple N-period average)
        if len(data) < self.rsi_period + 1:
            rsi = 50.0
        else:
            deltas = [data[i] - data[i-1] for i in range(1, len(data))]
            subset = deltas[-self.rsi_period:]
            gains = [d for d in subset if d > 0]
            losses = [abs(d) for d in subset if d <= 0]
            
            avg_gain = sum(gains) / self.rsi_period
            avg_loss = sum(losses) / self.rsi_period
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
        
        # Z-Score
        z_score = 0.0
        if stdev > 0:
            z_score = (current_price - sma) / stdev

        # Flash Crash check (last tick drop)
        prev_price = data[-2]
        tick_drop = (prev_price - current_price) / prev_price

        return {
            'z_score': z_score,
            'rsi': rsi,
            'tick_drop': tick_drop
        }

    def on_price_update(self, prices):
        """
        Core logic loop. Returns a dict order if action is taken.
        """
        # 1. Ingest Data
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_history)
            self.history[sym].append(price)

        # 2. Evaluate Strategy
        for sym, price in prices.items():
            if sym not in self.history or len(self.history[sym]) < self.bb_period:
                continue

            ind = self._get_indicators(self.history[sym])
            if not ind:
                continue

            # --- POSITION MANAGEMENT ---
            if sym in self.portfolio and self.portfolio[sym]['amt'] > 0:
                pos = self.portfolio[sym]
                avg_entry = pos['entry']
                
                # ROI Calculation
                roi = (price - avg_entry) / avg_entry
                
                # A. TAKE PROFIT (Strictly Positive)
                # Guaranteed Fix for STOP_LOSS: Only sell if ROI > target.
                if roi >= self.target_roi:
                    amt_to_sell = pos['amt']
                    del self.portfolio[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': amt_to_sell,
                        'reason': ['PROFIT_SECURE', f'ROI_{roi*100:.2f}%']
                    }
                
                # B. DEFENSIVE DCA (Martingale)
                if pos['dca_count'] < self.dca_limit:
                    # Adaptive Step: 2%, 4%, 6%... linear expansion of grid
                    required_drop = 0.02 * (pos['dca_count'] + 1)
                    
                    if roi < -required_drop:
                        # Filter: Ensure we aren't buying the exact bottom of a red candle without RSI support
                        if ind['rsi'] < self.rsi_dca_threshold:
                            
                            bet_size = self.base_bet * (self.dca_scale ** (pos['dca_count'] + 1))
                            qty_to_buy = bet_size / price
                            
                            # Update Position
                            self.portfolio[sym]['amt'] += qty_to_buy
                            self.portfolio[sym]['cost'] += bet_size
                            self.portfolio[sym]['entry'] = self.portfolio[sym]['cost'] / self.portfolio[sym]['amt']
                            self.portfolio[sym]['dca_count'] += 1
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': qty_to_buy,
                                'reason': ['DCA_DEFENSE', f'Lvl_{pos["dca_count"]}']
                            }

            # --- NEW ENTRY LOGIC ---
            else:
                # Mutation: 3.2-Sigma Event + Deep Oversold (18 RSI)
                # Condition 1: Z-Score < -3.2 (Statistical Rare Event)
                # Condition 2: RSI < 18 (Oversold)
                # Condition 3: Tick Drop < 5% (Avoid instant flash crashes/glitches)
                
                if ind['z_score'] < -self.bb_std_dev and ind['rsi'] < self.rsi_entry_threshold:
                    if ind['tick_drop'] < 0.05:
                        qty = self.base_bet / price
                        
                        self.portfolio[sym] = {
                            'amt': qty,
                            'entry': price,
                            'cost': self.base_bet,
                            'dca_count': 0
                        }
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': qty,
                            'reason': ['QUANTUM_ENTRY', f'Z_{ind["z_score"]:.2f}']
                        }

        return None