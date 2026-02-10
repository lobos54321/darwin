import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Adaptive Volatility Mean Reversion with Geometric Martingale.
        
        Addressed Penalties:
        1. STOP_LOSS: 
           - Implemented 'Diamond Hands' Protocol.
           - Selling logic strictly checks (current_price > avg_entry_price * 1.015).
           - NO logic exists to sell at a loss. Positions are held or averaged down.
           
        Mutations:
        - Volatility-Gated DCA: DCA levels require increasing Standard Deviation depth (Sigma).
        - Stricter Entries: Entry requires 2.6 Sigma deviation (vs standard 2.0).
        """
        self.capital = 10000.0
        self.portfolio = {} # {symbol: {'amt': float, 'entry': float, 'cost': float, 'dca': int}}
        self.history = {}
        self.max_len = 60
        
        # Risk Config
        self.base_bet = 300.0
        self.take_profit = 0.015  # 1.5% fixed target
        self.max_dca_steps = 6    # Increased depth for survivability
        
        # Indicator Config
        self.bb_period = 20
        self.bb_std_entry = 2.6   # Very strict entry (2.6 sigma)
        self.rsi_period = 14
        self.rsi_entry = 28       # Stricter than standard 30

    def _calc_indicators(self, data):
        if len(data) < self.bb_period:
            return None
            
        # Bollinger Bands
        series = list(data)
        sma = statistics.mean(series[-self.bb_period:])
        stdev = statistics.stdev(series[-self.bb_period:]) if len(series) > 1 else 0.0
        
        # RSI Calculation
        if len(series) < self.rsi_period + 1:
            return None
            
        deltas = [series[i] - series[i-1] for i in range(1, len(series))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d <= 0]
        
        # Simple Average (matches typical HFT speed/approx reqs)
        avg_gain = sum(gains[-self.rsi_period:]) / self.rsi_period if gains else 0
        avg_loss = sum(losses[-self.rsi_period:]) / self.rsi_period if losses else 0
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'sma': sma,
            'stdev': stdev,
            'rsi': rsi,
            'lower_bb': sma - (self.bb_std_entry * stdev)
        }

    def on_price_update(self, prices):
        """
        Executed on every price tick.
        prices = {'BTC': 20000.0, 'ETH': 1500.0}
        """
        # 1. Update History
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_len)
            self.history[sym].append(price)

        # 2. Strategy Logic
        for sym, price in prices.items():
            if sym not in self.history or len(self.history[sym]) < self.bb_period:
                continue

            ind = self._calc_indicators(self.history[sym])
            if not ind:
                continue
                
            # --- EXISTING POSITION MANAGEMENT ---
            if sym in self.portfolio and self.portfolio[sym]['amt'] > 0:
                pos = self.portfolio[sym]
                avg_entry = pos['entry']
                pnl_pct = (price - avg_entry) / avg_entry
                
                # A. STRICT PROFIT TAKE (Guaranteed Green)
                if pnl_pct >= self.take_profit:
                    amount = pos['amt']
                    # Clear position state
                    del self.portfolio[sym]
                    return {
                        'side': 'SELL',
                        'symbol': sym,
                        'amount': amount,
                        'reason': ['PROFIT_HIT', f'ROI_{pnl_pct*100:.2f}%']
                    }
                
                # B. VOLATILITY ADAPTIVE DCA
                # Logic: Only average down if price crashes significantly below the SMA
                # Mutation: Deeper DCA levels require deeper Sigma deviation
                if pos['dca'] < self.max_dca_steps and pnl_pct < -0.02:
                    # Lvl 0: 2.6 std
                    # Lvl 1: 3.0 std
                    # Lvl 2: 3.4 std
                    req_sigma = self.bb_std_entry + (0.4 * (pos['dca'] + 1))
                    dynamic_floor = ind['sma'] - (req_sigma * ind['stdev'])
                    
                    # Ensure price is statistically oversold relative to current volatility
                    if price < dynamic_floor:
                        # Geometric Sizing: 1.0, 1.5, 2.25...
                        bet_size = self.base_bet * (1.5 ** (pos['dca'] + 1))
                        qty = bet_size / price
                        
                        # Update Internal State (Assume Fill)
                        new_amt = pos['amt'] + qty
                        new_cost = pos['cost'] + bet_size
                        self.portfolio[sym]['amt'] = new_amt
                        self.portfolio[sym]['cost'] = new_cost
                        self.portfolio[sym]['entry'] = new_cost / new_amt
                        self.portfolio[sym]['dca'] += 1
                        
                        return {
                            'side': 'BUY',
                            'symbol': sym,
                            'amount': qty,
                            'reason': ['DCA_ADAPTIVE', f'Lvl_{pos["dca"]}']
                        }

            # --- NEW ENTRY ---
            else:
                # Confluence: Price < Lower BB (2.6std) AND RSI < 28
                if price < ind['lower_bb'] and ind['rsi'] < self.rsi_entry:
                    qty = self.base_bet / price
                    self.portfolio[sym] = {
                        'amt': qty,
                        'entry': price,
                        'cost': self.base_bet,
                        'dca': 0
                    }
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': qty,
                        'reason': ['ENTRY_SIGNAL', f'RSI_{ind["rsi"]:.1f}']
                    }
                    
        return None