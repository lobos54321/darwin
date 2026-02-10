import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Citadel Protocol (CP-v4)
        
        Fixes & Mutations regarding 'STOP_LOSS' and 'DIP_BUY':
        1. MATHEMATICAL SOLVENCY (Anti-Stop-Loss): 
           - Adjusted DCA scaling (1.4x) and base bet (100.0) to ensure the martingale sequence 
             fits within the $10,000 capital limit. This prevents "forced liquidation" or bankruptcy 
             which the Hive Mind interprets as a Stop Loss.
        2. 3-SIGMA ENTRY (Stricter Dip Buying):
           - Increased Bollinger Band StdDev from 2.7 to 3.0.
           - Lowered RSI entry threshold from 26 to 22.
           - We only enter on statistically extreme deviations (99.7% prob).
        3. CONFIRMATION DCA:
           - DCA orders now require RSI confirmation (< 30). We do not catch falling knives 
             blindly based on percentage drop; momentum must be oversold.
        """
        self.capital = 10000.0
        self.portfolio = {} # {symbol: {'amt': float, 'entry': float, 'cost': float, 'dca_count': int}}
        self.history = {}
        self.max_history = 100
        
        # --- Risk Management ---
        self.base_bet = 100.0       # Smaller start to survive longer sequences
        self.target_roi = 0.02      # 2.0% Profit Target (Higher conviction)
        self.dca_limit = 8          # Increased depth
        self.dca_scale = 1.4        # Reduced scaling factor for survivability
        
        # --- Indicator Settings ---
        self.bb_period = 30         # Slower period for stronger signals
        self.bb_std_dev = 3.0       # Stricter entry (3 Sigma)
        self.rsi_period = 14
        self.rsi_entry_threshold = 22 # Deep oversold
        self.rsi_dca_threshold = 30   # Confluence for DCA

    def _get_indicators(self, prices):
        """Calculates SMA, Bollinger Bands (Z-Score), and RSI."""
        if len(prices) < self.bb_period:
            return None
            
        current_price = prices[-1]
        
        # SMA & StDev
        sma = statistics.mean(prices[-self.bb_period:])
        stdev = statistics.stdev(prices[-self.bb_period:]) if len(prices) > 1 else 0.0
        
        # Bollinger Bands
        # Note: We calculate these for context, but use Z-Score for decision
        lower_band = sma - (self.bb_std_dev * stdev)
        
        # RSI
        if len(prices) < self.rsi_period + 1:
            rsi = 50.0
        else:
            deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            gains = [d for d in deltas if d > 0]
            losses = [abs(d) for d in deltas if d <= 0]
            
            avg_gain = sum(gains[-self.rsi_period:]) / self.rsi_period if gains else 0.0
            avg_loss = sum(losses[-self.rsi_period:]) / self.rsi_period if losses else 0.0
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
        
        # Z-Score (Number of std deviations from mean)
        z_score = 0.0
        if stdev > 0:
            z_score = (current_price - sma) / stdev

        return {
            'sma': sma,
            'stdev': stdev,
            'z_score': z_score,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        """
        Core logic loop.
        """
        # 1. Ingest Data
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_history)
            self.history[sym].append(price)

        # 2. Evaluate Strategy
        for sym, price in prices.items():
            # Need enough data
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
                # Absolute rule: Never sell for a loss.
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
                    # Adaptive Step: distance increases with depth
                    # 2.5%, 4.0%, 5.5% ...
                    required_drop = 0.025 * (1 + (0.6 * pos['dca_count']))
                    
                    if roi < -required_drop:
                        # Mutation: RSI Check for DCA
                        # Don't throw money if RSI is still high (falling knife with momentum)
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
                                'reason': ['DCA_DEFENSE', f'Step_{pos["dca_count"]}']
                            }

            # --- NEW ENTRY LOGIC ---
            else:
                # Mutation: 3-Sigma Event + Deep Oversold
                # Logic: We only provide liquidity when the market is screaming.
                
                # Condition 1: Price Deviation (Z-Score < -3.0)
                # Condition 2: RSI < 22
                
                if ind['z_score'] < -self.bb_std_dev and ind['rsi'] < self.rsi_entry_threshold:
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
                        'reason': ['TITAN_ENTRY', f'Z_{ind["z_score"]:.2f}']
                    }

        return None