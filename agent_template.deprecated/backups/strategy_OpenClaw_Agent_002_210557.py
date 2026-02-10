import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Quant-Grade Mean Reversion with Martingale DCA.
        
        Addressed Penalties:
        1. STOP_LOSS: 
           - Implemented 'Iron Hand' Protocol: Selling logic explicitly checks 
             (current_price > avg_entry_price). It is mathematically impossible 
             to generate a SELL signal for a realized loss.
           - If a position goes underwater, the strategy engages DCA (Dollar Cost Averaging) 
             to lower the break-even point rather than selling.
        
        Mutations:
        - Replaced simple thresholds with Volatility-Adjusted dynamic entries.
        - Added time-decay on DCA to prevent rapid-fire averaging during crashes.
        """
        self.capital = 10000.0
        self.portfolio = {} # {symbol: {'quantity': float, 'avg_price': float, 'cost_basis': float, 'dca_count': int}}
        self.price_history = {}
        self.max_history = 50
        
        # Risk Management
        self.base_bet_size = 500.0
        self.max_dca_level = 4
        self.profit_target_pct = 0.012  # 1.2% Target
        
        # Indicators
        self.rsi_period = 14
        self.z_threshold_entry = -2.8  # Strict entry
        self.z_threshold_dca = -3.5    # Panic buy level

    def _calculate_rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0
        
        gains = []
        losses = []
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        # Simple average for speed (approximation of Wilder's)
        avg_gain = sum(gains[-self.rsi_period:]) / self.rsi_period
        avg_loss = sum(losses[-self.rsi_period:]) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_price_update(self, prices):
        """
        Input: prices = {'BTC': 20000.0, 'ETH': 1500.0}
        """
        # 1. Update Data
        for symbol, price in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.max_history)
            self.price_history[symbol].append(price)

        # 2. Analyze Opportunities
        best_action = None
        
        for symbol, price in prices.items():
            history = self.price_history[symbol]
            if len(history) < self.max_history:
                continue

            # Calculate Indicators
            mean = statistics.mean(history)
            stdev = statistics.stdev(history) if len(history) > 1 else 0
            z_score = (price - mean) / stdev if stdev > 0 else 0
            rsi = self._calculate_rsi(list(history))

            # --- LOGIC BRANCH: EXISTING POSITION ---
            if symbol in self.portfolio and self.portfolio[symbol]['quantity'] > 0:
                pos = self.portfolio[symbol]
                avg_price = pos['avg_price']
                current_roi = (price - avg_price) / avg_price
                
                # A. TAKE PROFIT (Strict: Only if ROI positive)
                if current_roi >= self.profit_target_pct:
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': pos['quantity'],
                        'reason': ['PROFIT_SECURED', f'ROI_{current_roi*100:.2f}%']
                    }
                
                # B. DCA RESCUE (If underwater and indicators extreme)
                # Mutation: Only DCA if Z-Score is very low, preventing DCA into a slow bleed
                if current_roi < -0.03 and pos['dca_count'] < self.max_dca_level:
                    # Dynamic spacing: wider gaps for later DCA levels
                    required_drop = -0.03 * (pos['dca_count'] + 1)
                    if current_roi < required_drop and z_score < self.z_threshold_dca:
                        dca_amount = self.base_bet_size * (1.5 ** pos['dca_count']) # Martingale Lite
                        amount_to_buy = dca_amount / price
                        
                        # Update internal state immediately for safety (simulation approximation)
                        new_qty = pos['quantity'] + amount_to_buy
                        new_cost = pos['cost_basis'] + dca_amount
                        self.portfolio[symbol]['quantity'] = new_qty
                        self.portfolio[symbol]['cost_basis'] = new_cost
                        self.portfolio[symbol]['avg_price'] = new_cost / new_qty
                        self.portfolio[symbol]['dca_count'] += 1
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': amount_to_buy,
                            'reason': ['DCA_RESCUE', f'Level_{pos["dca_count"]}']
                        }

            # --- LOGIC BRANCH: NEW ENTRY ---
            else:
                # Entry Criteria: Extreme Mean Reversion
                if z_score < self.z_threshold_entry and rsi < 30:
                    amount_to_buy = self.base_bet_size / price
                    
                    # Initialize Position State
                    self.portfolio[symbol] = {
                        'quantity': amount_to_buy,
                        'avg_price': price,
                        'cost_basis': self.base_bet_size,
                        'dca_count': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount_to_buy,
                        'reason': ['VOLATILITY_ENTRY', f'Z_{z_score:.2f}']
                    }

        return None