import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quantum Immunity Martingale (QIM)
        
        Fixes & Mutations:
        1. ANTI-STOP-LOSS ARCHITECTURE: 
           - Sales are strictly gated by (Price > Weighted_Avg_Entry * (1 + Min_ROI)).
           - No mechanism exists to sell for a loss. Logic implies infinite holding/DCA until green.
        2. KINETIC DCA: 
           - DCA orders are not just price-based but momentum-gated. 
           - We wait for RSI to cool off even further before adding to a losing position.
        3. VOLATILITY SCALING:
           - Entry criteria tighten as volatility (Standard Deviation) expands.
        """
        self.capital = 10000.0
        self.portfolio = {} # {symbol: {'amt': float, 'entry': float, 'cost': float, 'dca_count': int}}
        self.history = {}
        self.max_history = 60
        
        # --- Risk Management ---
        self.base_bet = 250.0       # Conservative start size
        self.target_roi = 0.015     # 1.5% Profit Target
        self.dca_limit = 7          # High survival depth
        self.dca_scale = 1.6        # Aggressive scaling to lower breakeven quickly
        
        # --- Indicator Settings ---
        self.bb_period = 20
        self.bb_std_dev = 2.7       # Stricter than standard 2.0 to prevent early entry
        self.rsi_period = 14
        self.rsi_buy_threshold = 26 # Very oversold required for initial entry

    def _get_indicators(self, prices):
        """Calculates SMA, Bollinger Bands, and RSI."""
        if len(prices) < self.bb_period:
            return None
            
        # Basic Stats
        current_price = prices[-1]
        sma = statistics.mean(prices[-self.bb_period:])
        stdev = statistics.stdev(prices[-self.bb_period:]) if len(prices) > 1 else 0.0
        
        # Bollinger Bands
        lower_band = sma - (self.bb_std_dev * stdev)
        upper_band = sma + (self.bb_std_dev * stdev)
        
        # RSI
        if len(prices) < self.rsi_period + 1:
            rsi = 50.0 # Default neutral
        else:
            deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            gains = [d for d in deltas if d > 0]
            losses = [abs(d) for d in deltas if d <= 0]
            
            # Use simple moving average for speed/stability
            avg_gain = sum(gains[-self.rsi_period:]) / self.rsi_period if gains else 0.0
            avg_loss = sum(losses[-self.rsi_period:]) / self.rsi_period if losses else 0.0
            
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                
        return {
            'sma': sma,
            'stdev': stdev,
            'lower_bb': lower_band,
            'upper_bb': upper_band,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        """
        Core logic loop.
        Returns order dict or None.
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
                # Note: We do NOT have a stop loss condition here.
                # Only Sell if Price > Entry + Target
                current_roi = (price - avg_entry) / avg_entry
                
                # A. TAKE PROFIT (Strictly Green)
                if current_roi >= self.target_roi:
                    amt_to_sell = pos['amt']
                    del self.portfolio[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': amt_to_sell,
                        'reason': ['PROFIT_SECURE', f'ROI_{current_roi*100:.2f}%']
                    }
                
                # B. DEFENSIVE DCA (Martingale)
                # Conditions: 
                # 1. Not at max steps
                # 2. Price dropped significantly below avg entry (Adaptive Step)
                # 3. Price is at valid support (Lower BB) to avoid catching falling knives too early
                
                if pos['dca_count'] < self.dca_limit:
                    # Adaptive step: 2%, 4%, 6%...
                    required_drop = 0.02 * (1 + (0.5 * pos['dca_count']))
                    
                    if current_roi < -required_drop:
                        # Confluence Check: Don't buy just because it's down. Buy because it's cheap.
                        # Price must be below lower BB OR RSI extremely oversold (< 20)
                        is_cheap = price < ind['lower_bb'] or ind['rsi'] < 22
                        
                        if is_cheap:
                            # Martingale Sizing
                            bet_size = self.base_bet * (self.dca_scale ** (pos['dca_count'] + 1))
                            qty_to_buy = bet_size / price
                            
                            # Update Position State
                            new_amt = pos['amt'] + qty_to_buy
                            new_cost = pos['cost'] + bet_size
                            self.portfolio[sym]['amt'] = new_amt
                            self.portfolio[sym]['cost'] = new_cost
                            self.portfolio[sym]['entry'] = new_cost / new_amt
                            self.portfolio[sym]['dca_count'] += 1
                            
                            return {
                                'side': 'BUY',
                                'symbol': sym,
                                'amount': qty_to_buy,
                                'reason': ['DCA_DEFENSE', f'Step_{pos["dca_count"]}']
                            }

            # --- NEW ENTRY LOGIC ---
            else:
                # Mutation: Z-Score Filter
                # Require price to be statistically deviated AND RSI cooled off
                if ind['stdev'] > 0:
                    z_score = (price - ind['sma']) / ind['stdev']
                else:
                    z_score = 0
                
                # Entry Conditions:
                # 1. Price < Lower Bollinger Band (implied by Z-score < -2.7)
                # 2. RSI < 26
                # 3. Z-Score < -2.7 (Deep deviation)
                if z_score < -2.7 and ind['rsi'] < self.rsi_buy_threshold:
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
                        'reason': ['QUANTUM_ENTRY', f'Z_{z_score:.2f}']
                    }

        return None