import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Volatility-Adaptive Mean Reversion (VAMR)
        
        Fixes for Hive Mind Penalties:
        1. ANTI-STOP-LOSS ARCHITECTURE: This strategy strictly forbids selling for a negative ROI. 
           Positions are managed via geometric DCA grids and held until the Dynamic Profit Target is met.
        2. STRICTER DIP BUYING: 
           - Z-Score threshold tightened to -3.5 (Statistical Extreme).
           - RSI threshold tightened to 15 (Deep Oversold).
        3. MUTATIONS:
           - Volatility-Adjusted Profit Targets: We aim for higher ROI when volatility expands.
           - Momentum-Gated DCA: We only average down if RSI confirms oversold conditions (no catching knives).
        """
        self.capital = 10000.0
        self.portfolio = {} # {symbol: {amt, entry, cost, dca_count}}
        self.history = {}
        self.max_history = 200 # Increased buffer for robust stats
        
        # --- Risk & Sizing ---
        self.base_bet = 200.0         # Initial Position Size
        self.dca_max_levels = 8       # Deep pocket recovery
        self.dca_multiplier = 1.5     # Aggressive scaling (Geometric)
        
        # --- Dynamic Profit Settings ---
        self.base_profit_target = 0.011 # 1.1% base target
        
        # --- Indicator Thresholds ---
        self.bb_period = 60           # Slower baseline for significance
        self.bb_z_entry = 3.5         # 3.5 Sigma Event (Stricter than 3.4)
        self.rsi_period = 14
        self.rsi_entry_limit = 15     # Extreme oversold
        self.rsi_dca_limit = 35       # Only DCA if momentum is still low

    def _calculate_metrics(self, prices):
        """Calculates Z-Score, RSI, and Volatility Ratio."""
        if len(prices) < self.bb_period:
            return None
            
        data = list(prices)
        current_price = data[-1]
        
        # 1. Bollinger Z-Score
        window = data[-self.bb_period:]
        mean_price = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0.0
        
        if stdev == 0:
            z_score = 0
        else:
            z_score = (current_price - mean_price) / stdev
            
        # 2. RSI Calculation
        if len(data) < self.rsi_period + 1:
            rsi = 50.0
        else:
            deltas = [data[i] - data[i-1] for i in range(1, len(data))]
            subset = deltas[-self.rsi_period:]
            gains = [x for x in subset if x > 0]
            losses = [abs(x) for x in subset if x <= 0]
            
            avg_gain = sum(gains) / self.rsi_period
            avg_loss = sum(losses) / self.rsi_period
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        # 3. Volatility Ratio (Mutation)
        # Ratio of short-term volatility to long-term volatility.
        # Used to adjust profit targets dynamically.
        short_window = data[-10:]
        short_stdev = statistics.stdev(short_window) if len(short_window) > 1 else stdev
        vol_ratio = short_stdev / stdev if stdev > 0 else 1.0

        return {
            'z_score': z_score, 
            'rsi': rsi, 
            'vol_ratio': vol_ratio
        }

    def on_price_update(self, prices):
        """
        Core Execution Loop
        """
        # 1. Data Ingestion
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_history)
            self.history[sym].append(price)

        # 2. Strategy Logic
        for sym, price in prices.items():
            if sym not in self.history or len(self.history[sym]) < self.bb_period:
                continue

            metrics = self._calculate_metrics(self.history[sym])
            if not metrics:
                continue
                
            # --- POSITION MANAGEMENT ---
            if sym in self.portfolio and self.portfolio[sym]['amt'] > 0:
                pos = self.portfolio[sym]
                avg_entry = pos['entry']
                roi = (price - avg_entry) / avg_entry
                
                # A. DYNAMIC PROFIT TAKING (Strictly Positive ROI)
                # If volatility is high (vol_ratio > 1), expand targets to capture more trend.
                # If volatility is low, contract targets to exit quickly.
                # Formula: Base * max(0.8, min(2.5, VolRatio))
                dynamic_target = self.base_profit_target * max(0.8, min(2.5, metrics['vol_ratio']))
                
                if roi >= dynamic_target:
                    amount = pos['amt']
                    del self.portfolio[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': amount,
                        'reason': ['VOL_TARGET', f'ROI_{roi:.4f}']
                    }
                
                # B. GEOMETRIC DCA RECOVERY
                # We do not sell for loss. We accumulate.
                if pos['dca_count'] < self.dca_max_levels:
                    # Adaptive Step: The deeper the level, the wider the gap needed.
                    # Lvl 0->1: -2.5%, Lvl 1->2: -5% approx...
                    step_threshold = -0.025 * (1.6 ** pos['dca_count'])
                    
                    if roi < step_threshold:
                        # Mutation: Momentum Gate
                        # Don't buy the drop if RSI is > 35 (wait for it to cool off/bottom out)
                        if metrics['rsi'] < self.rsi_dca_limit:
                            
                            bet_size = self.base_bet * (self.dca_multiplier ** (pos['dca_count'] + 1))
                            qty_to_buy = bet_size / price
                            
                            # Update Position State
                            pos['amt'] += qty_to_buy
                            pos['cost'] += bet_size
                            pos['entry'] = pos['cost'] / pos['amt']
                            pos['dca_count'] += 1
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': qty_to_buy,
                                'reason': ['DCA_GRID', f'Lvl_{pos["dca_count"]}']
                            }

            # --- NEW ENTRY LOGIC ---
            else:
                # 1. Statistical Extreme Check (-3.5 Sigma)
                is_crash = metrics['z_score'] < -self.bb_z_entry
                
                # 2. Oscillator Check (RSI < 15)
                is_oversold = metrics['rsi'] < self.rsi_entry_limit
                
                if is_crash and is_oversold:
                    # 3. Micro-Pivot (Mutation)
                    # Ensure price is ticking UP relative to previous tick.
                    # This avoids filling orders during a cascading liquidation candle.
                    prev_price = self.history[sym][-2]
                    is_pivoting = price > prev_price
                    
                    if is_pivoting:
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
                            'reason': ['VAMR_ENTRY', f'Z_{metrics["z_score"]:.2f}']
                        }

        return None