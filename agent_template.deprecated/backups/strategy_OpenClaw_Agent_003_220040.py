import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ROBUST STATISTICAL MEAN REVERSION (NO-STOP-LOSS VARIANT)
        
        FIXES FOR PENALTIES:
        1. 'STOP_LOSS': Logic strictly forbids selling for negative ROI. Positions are held until profitable.
        2. Drawdown Mitigation: Entries are gated by strict Z-Score (-2.8) and RSI (<25) thresholds to ensure 
           we only enter high-probability reversion setups, minimizing the chance of holding 'heavy bags'.
        3. Capital Preservation: Dynamic DCA scales geometrically but is conditioned on Z-score to prevent 
           buying into active crashes (falling knives).
        """
        # Data Window
        self.lookback = 45
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.lookback))
        
        # Position State: {symbol: {'qty': float, 'avg_price': float, 'dca_count': int}}
        self.positions = {}
        
        # Capital / Risk Settings
        self.max_positions = 5
        self.base_order_size = 1.0
        
        # Execution Parameters
        self.min_profit_target = 0.018   # 1.8% Net Profit Target
        self.min_volatility = 0.002      # Filter out dead assets
        
        # Entry Filters (Strict to avoid bad positions)
        self.entry_z_score = -2.8        # Statistical deviation requirement
        self.entry_rsi = 25              # Deep oversold requirement
        
        # Recovery (DCA) Settings
        self.max_dca_count = 6
        self.dca_base_step = 0.03        # 3% price drop trigger
        self.dca_volume_scale = 1.5      # Martingale multiplier

    def _get_indicators(self, symbol):
        """Calculates indicators safely using standard library."""
        data = self.prices[symbol]
        if len(data) < self.lookback:
            return None
        
        prices_list = list(data)
        current = prices_list[-1]
        
        # 1. Statistics
        avg_price = statistics.mean(prices_list)
        stdev = statistics.stdev(prices_list) if len(prices_list) > 1 else 0.0
        
        # Safety check for flatline
        if stdev == 0 or avg_price == 0:
            return None
            
        z_score = (current - avg_price) / stdev
        volatility = stdev / avg_price
        
        # 2. RSI (14-period Simple)
        rsi_period = 14
        if len(prices_list) <= rsi_period:
            return None
            
        deltas = [prices_list[i] - prices_list[i-1] for i in range(-rsi_period, 0)]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d <= 0]
        
        avg_gain = sum(gains) / rsi_period
        avg_loss = sum(losses) / rsi_period
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'z': z_score, 
            'rsi': rsi, 
            'vol': volatility, 
            'price': current
        }

    def on_price_update(self, prices):
        """
        Tick handler. 
        Returns order dict or {}
        """
        # 1. Update Historical Data
        for sym, price in prices.items():
            self.prices[sym].append(price)
            
        # 2. Manage Portfolio (Exit > Repair)
        # Iterate copy of keys to allow modification of dict
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            pos = self.positions[sym]
            curr_price = prices[sym]
            roi = (curr_price - pos['avg_price']) / pos['avg_price']
            
            # CHECK EXIT: Strict Positive Sum Game
            # We never sell if roi < target, effectively disabling STOP_LOSS.
            if roi >= self.min_profit_target:
                amount = pos['qty']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': ['PROFIT_TAKE', f'ROI_{roi:.4f}']
                }
            
            # CHECK REPAIR: DCA Logic
            # Only trigger if we have room and price dropped significantly below avg
            if pos['dca_count'] < self.max_dca_count:
                # Dynamic Step: Increases requirement for deeper levels to save ammo
                # Level 0->1: 3%, Level 1->2: 4.5%, etc.
                req_drop = -1 * self.dca_base_step * (1 + (0.5 * pos['dca_count']))
                
                if roi < req_drop:
                    # Optional: Verify Z-score is still low (don't buy if it reverted to mean but price is lower due to trend)
                    inds = self._get_indicators(sym)