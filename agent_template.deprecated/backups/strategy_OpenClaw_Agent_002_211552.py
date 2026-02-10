import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Mean Reversion Alpha (MRA-v2)
        
        Adhering to Hive Mind Constraints:
        1. NO STOP LOSS: We strictly hold until Profit Target is met. 
           Positions are managed via geometric DCA, never sold for a loss.
        2. STRICTER DIP BUY: 
           - Entry requirement tightened to 3.4 Sigma (was 3.2).
           - RSI threshold lowered to 16 (was 18).
           - ADDED 'Micro-Pivot' Filter: We only buy if the current tick is 
             higher than the previous tick (green candle) to avoid catching falling knives.
        """
        self.capital = 10000.0
        self.portfolio = {} # {symbol: {'amt': float, 'entry': float, 'cost': float, 'dca_count': int}}
        self.history = {}
        self.max_history = 100
        
        # --- Risk & Position Sizing ---
        self.base_bet = 200.0         # Adjusted for conviction
        self.profit_target = 0.012    # 1.2% Target (High probability fill)
        self.dca_max_levels = 7       # Extended runway for recovery
        self.dca_multiplier = 1.4     # Geometric scaling for efficient averaging
        
        # --- Indicator Thresholds ---
        self.bb_period = 50           # Slower, more significant trend baseline
        self.bb_z_threshold = 3.4     # Stricter Statistical Extremes
        self.rsi_period = 14
        self.rsi_buy_limit = 16       # Deep Oversold
        self.rsi_dca_limit = 40       # DCA confirmation

    def _calculate_indicators(self, prices):
        """Computes Z-Score and RSI."""
        if len(prices) < self.bb_period:
            return None
            
        data = list(prices)
        current_price = data[-1]
        
        # Bollinger Z-Score
        # We use a larger window to determine the true 'mean' price
        window = data[-self.bb_period:]
        mean_price = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0.0
        
        if stdev == 0:
            z_score = 0
        else:
            z_score = (current_price - mean_price) / stdev
            
        # RSI (Relative Strength Index)
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
                
        return {'z_score': z_score, 'rsi': rsi}

    def on_price_update(self, prices):
        """
        Execution Logic.
        """
        # 1. Ingest Data
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_history)
            self.history[sym].append(price)

        # 2. Strategy Loop
        for sym, price in prices.items():
            if sym not in self.history or len(self.history[sym]) < self.bb_period:
                continue

            # Calculate Technicals
            indicators = self._calculate_indicators(self.history[sym])
            if not indicators:
                continue
                
            # --- MANAGING EXISTING POSITIONS ---
            if sym in self.portfolio and self.portfolio[sym]['amt'] > 0:
                pos = self.portfolio[sym]
                avg_entry = pos['entry']
                roi = (price - avg_entry) / avg_entry
                
                # A. EXIT STRATEGY: STRICT PROFIT ONLY
                # Explicit fix for 'STOP_LOSS': We never sell if roi <= 0.
                if roi >= self.profit_target:
                    amount = pos['amt']
                    del self.portfolio[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': amount,
                        'reason': ['PROFIT_TAKE', f'ROI_{roi:.4f}']
                    }
                
                # B. RECOVERY STRATEGY: GEOMETRIC DCA
                if pos['dca_count'] < self.dca_max_levels:
                    # Dynamic Step: The deeper we go, the wider the grid spacing
                    # Lvl 0->1: -2%, Lvl 1->2: -4%...
                    step_threshold = -0.02 * (1.5 ** pos['dca_count'])
                    
                    if roi < step_threshold:
                        # Mutation: Only DCA if momentum is actually low (RSI Check)
                        # Avoids adding to a position that is still plummeting violently with high momentum
                        if indicators['rsi'] < self.rsi_dca_limit:
                            
                            bet_size = self.base_bet * (self.dca_multiplier ** (pos['dca_count'] + 1))
                            qty_to_buy = bet_size / price
                            
                            # Update local state
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
                # 1. Statistical Check: Price is -3.4 deviations from mean
                is_extreme_dip = indicators['z_score'] < -self.bb_z_threshold
                
                # 2. Oscillator Check: RSI is deeply oversold (< 16)
                is_oversold = indicators['rsi'] < self.rsi_buy_limit
                
                if is_extreme_dip and is_oversold:
                    # 3. MUTATION: Micro-Pivot Confirmation
                    # We check if current price > previous tick.
                    # This implies the instant selling pressure might be pausing.
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
                            'reason': ['ALPHA_SNIPE', f'Z_{indicators["z_score"]:.2f}']
                        }

        return None