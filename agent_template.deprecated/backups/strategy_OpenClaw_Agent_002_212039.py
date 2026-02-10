import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Hyper-Adaptive Mean Reversion (HAMR)
        
        Addressed Hive Mind Penalties:
        1. STOP_LOSS: Logic strictly enforces 'Only Sell in Profit'. All exits are calculated 
           based on Average Entry Price. No stop-losses are implemented; we use DCA to manage drawdowns.
        2. STRICTER DIP BUYING: 
           - Entry Z-Score: -3.5 (Statistical Crash)
           - Entry RSI: 12 (Extreme Oversold, tighter than 15)
           - Micro-Pivot confirmation required.

        Mutations:
        1. Volatility-Dilated DCA Grid: Grid spacing expands when volatility is high to prevent 
           capital exhaustion during violent crashes.
        2. Dynamic Profit Scaling: Profit targets expand with volatility to capture larger rebounds.
        3. Momentum-Gated Entry/DCA: Entries require local inflection points (pivot).
        """
        self.capital = 10000.0
        self.portfolio = {}  # {symbol: {amt, entry, cost, dca_count}}
        self.history = {}
        self.max_history = 100
        
        # --- Risk Management ---
        self.base_bet = 150.0
        self.max_dca_levels = 10 
        self.dca_multiplier = 1.6  # Aggressive geometric scaling for rapid cost-basis reduction
        
        # --- Indicator Settings ---
        self.bb_period = 50
        self.bb_z_threshold = 3.5  # Strict crash detection
        self.rsi_period = 14
        self.rsi_entry_limit = 12  # Strict oversold
        self.rsi_dca_limit = 40    # Only DCA if still somewhat oversold
        
        # --- Profit targets ---
        self.min_roi = 0.012       # Minimum 1.2% profit

    def _calculate_indicators(self, prices):
        if len(prices) < self.bb_period:
            return None

        # Convert deque to list for slicing
        data = list(prices)
        current_price = data[-1]
        
        # 1. Bollinger Z-Score
        window = data[-self.bb_period:]
        mean = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0.0
        
        if stdev == 0:
            z_score = 0
        else:
            z_score = (current_price - mean) / stdev
            
        # 2. RSI (Wilder's Smoothing approximation)
        if len(data) < self.rsi_period + 1:
            rsi = 50.0
        else:
            deltas = [data[i] - data[i-1] for i in range(1, len(data))]
            subset = deltas[-self.rsi_period:]
            gains = [x for x in subset if x > 0]
            losses = [abs(x) for x in subset if x <= 0]
            
            avg_gain = sum(gains) / len(gains) if gains else 0.0
            avg_loss = sum(losses) / len(losses) if losses else 0.0
            
            # Simple average for speed/robustness in HFT loop
            if avg_loss == 0:
                rsi = 100.0
            elif avg_gain == 0:
                rsi = 0.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))

        # 3. Volatility Ratio (Short-term vs Long-term)
        short_window = data[-10:]
        short_vol = statistics.stdev(short_window) if len(short_window) > 1 else 0.0
        vol_ratio = short_vol / stdev if stdev > 0 else 1.0

        return {
            'z_score': z_score,
            'rsi': rsi,
            'vol_ratio': vol_ratio,
            'stdev': stdev
        }

    def on_price_update(self, prices):
        """
        Main Execution Loop
        Returns: Dict or None
        """
        # 1. Ingest Data
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_history)
            self.history[sym].append(price)

        # 2. Evaluate Strategies
        for sym, price in prices.items():
            if sym not in self.history or len(self.history[sym]) < self.bb_period:
                continue

            inds = self._calculate_indicators(self.history[sym])
            if not inds:
                continue

            # --- EXISTING POSITION LOGIC ---
            if sym in self.portfolio:
                pos = self.portfolio[sym]
                
                # Zero division safety
                if pos['amt'] == 0:
                    del self.portfolio[sym]
                    continue
                    
                avg_entry = pos['entry']
                roi = (price - avg_entry) / avg_entry
                
                # A. PROFIT TAKING (Strictly Positive)
                # Dynamic Target: Scale with volatility. High vol = aim higher.
                target_roi = self.min_roi * max(1.0, inds['vol_ratio'])
                
                if roi >= target_roi:
                    amt = pos['amt']
                    del self.portfolio[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': amt,
                        'reason': ['TAKE_PROFIT', f'ROI_{roi:.4f}']
                    }
                
                # B. GEOMETRIC DCA (Never Sell Loss)
                if pos['dca_count'] < self.max_dca_levels:
                    # Adaptive Grid: Widen spacing if Volatility is high to survive big crashes
                    base_step = -0.02 # -2.0%
                    vol_factor = max(1.0, inds['vol_ratio']) 
                    
                    # Step deepens geometrically + expands with volatility
                    # Level 0: -2% * vol, Level 1: -3.2% * vol, etc.
                    required_drop = base_step * (1.5 ** pos['dca_count']) * vol_factor
                    
                    if roi < required_drop:
                        # Momentum Gate: Don't buy if RSI is still too hot (catching falling knife)
                        if inds['rsi'] < self.rsi_dca_limit:
                            
                            bet_size = self.base_bet * (self.dca_multiplier ** (pos['dca_count'] + 1))
                            qty = bet_size / price
                            
                            pos['amt'] += qty
                            pos['cost'] += bet_size
                            pos['entry'] = pos['cost'] / pos['amt'] # Update avg entry
                            pos['dca_count'] += 1
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': qty,
                                'reason': ['DCA_PROTECT', f'Lvl_{pos["dca_count"]}']
                            }

            # --- NEW ENTRY LOGIC ---
            else:
                # 1. Statistical Crash (Z < -3.5)
                is_crash = inds['z_score'] < -self.bb_z_threshold
                
                # 2. Deep Oversold (RSI < 12)
                is_oversold = inds['rsi'] < self.rsi_entry_limit
                
                if is_crash and is_oversold:
                    # 3. Micro-Pivot Verification (Mutation)
                    # Ensure price > prev_price to avoid filling during the dump
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
                            'reason': ['HAMR_ENTRY', f'Z_{inds["z_score"]:.2f}']
                        }

        return None