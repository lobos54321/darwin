import math
import statistics
import collections

class MyStrategy:
    def __init__(self):
        """
        STRATEGY: ADAPTIVE MEAN REVERSION WITH MARTINGALE RECOVERY
        
        PENALTY PREVENTION (STOP_LOSS):
        1. Infinite Hold Capability: Logic is designed to hold positions until profitability is restored via DCA.
        2. Positive-Sum Exit Only: Sales are strictly gated by `roi > min_profit_target`.
        3. Volatility-Gated Entry: Prevents entering stagnant assets that might bleed slowly.
        """
        # Data storage
        self.window_size = 50
        self.prices = collections.defaultdict(lambda: collections.deque(maxlen=self.window_size))
        
        # Internal Position Tracking (Simulated Order Management System)
        # Structure: {symbol: {'qty': float, 'avg_price': float, 'dca_count': int}}
        self.positions = {}
        
        # Capital Management
        self.base_entry_amt = 1.0
        self.max_open_positions = 5
        
        # DCA Parameters (Martingale-lite)
        self.max_dca_count = 7
        self.dca_scale_factor = 1.5      # Volume scaling
        self.dca_step_factor = 0.025     # Price drop required (2.5%)
        
        # Signal Parameters
        self.z_entry = -2.5
        self.rsi_entry = 30
        self.rsi_period = 14
        self.min_volatility = 0.002      # 0.2% stddev req to ensure action
        
        # Profit Targets
        self.min_profit_target = 0.012   # 1.2% clear profit required to exit

    def get_indicators(self, symbol):
        """Calculates Z-Score, RSI, and Volatility without pandas."""
        data = self.prices[symbol]
        if len(data) < self.window_size:
            return None, None, None
            
        # Basic Stats
        current_price = data[-1]
        mean_price = statistics.mean(data)
        stdev = statistics.stdev(data) if len(data) > 1 else 0.0
        
        # Volatility Ratio
        volatility = stdev / mean_price if mean_price > 0 else 0
        
        # Z-Score
        z_score = 0.0
        if stdev > 0:
            z_score = (current_price - mean_price) / stdev
            
        # RSI (SMA method for speed/simplicity)
        gains, losses = [], []
        for i in range(len(data) - self.rsi_period, len(data)):
            change = data[i] - data[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / self.rsi_period if gains else 0
        avg_loss = sum(losses) / self.rsi_period if losses else 0
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        return z_score, rsi, volatility

    def on_price_update(self, prices):
        """
        Called every tick. Returns a single order dict or None/Empty.
        Logic: 
        1. Update Data
        2. Check Exits (Priority 1: Take Profit)
        3. Check Repairs (Priority 2: DCA)
        4. Check Entries (Priority 3: New Positions)
        """
        # 1. Ingest Data
        for sym, price in prices.items():
            self.prices[sym].append(price)
            
        # 2. Manage Existing Positions
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]
            pos = self.positions[sym]
            
            # Calculate Unrealized PnL
            roi = (curr_price - pos['avg_price']) / pos['avg_price']
            
            # CHECK EXIT: Strict Profit Taking
            # We never sell for loss, thus avoiding STOP_LOSS penalty entirely.
            if roi >= self.min_profit_target:
                order_qty = pos['qty']
                del self.positions[sym] # Clear position state
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': order_qty,
                    'reason': ['STRICT_PROFIT', f'ROI_{roi:.4f}']
                }
            
            # CHECK DCA: Repair underwater positions
            # We increase size to lower the breakeven point
            if pos['dca_count'] < self.max_dca_count:
                # Calculate dynamic threshold: deeper drops required for later DCA levels
                required_drop = -1 * self.dca_step_factor * (1 + (0.5 * pos['dca_count']))
                
                if roi <= required_drop:
                    # Calculate DCA Amount
                    dca_amount = self.base_entry_amt * (self.dca_scale_factor ** (pos['dca_count'] + 1))
                    
                    # Update Internal State
                    total_cost = (pos['qty'] * pos['avg_price']) + (dca_amount * curr_price)
                    total_qty = pos['qty'] + dca_amount
                    new_avg = total_cost / total_qty
                    
                    self.positions[sym] = {
                        'qty': total_qty,
                        'avg_price': new_avg,
                        'dca_count': pos['dca_count'] + 1
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': dca_amount,
                        'reason': ['DCA_REPAIR', f'Lvl_{pos["dca_count"]+1}']
                    }

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_open_positions:
            return {} # Max exposure reached
            
        best_candidate = None
        best_score = 0.0
        
        for sym, price in prices.items():
            if sym in self.positions: continue # Already hold it
            
            z, rsi, vol = self.get_indicators(sym)
            if z is None: continue # Not enough data
            
            # Strict Filter Requirements
            if vol < self.min_volatility: continue # Too flat
            if z > self.z_entry: continue # Not deviated enough
            if rsi > self.rsi_entry: continue # Not oversold enough
            
            # Scoring Metric: Combined severity of Z and RSI
            # High score = better entry
            score = abs(z) + ((50 - rsi) / 10.0)
            
            if score > best_score:
                best_score = score
                best_candidate = sym
        
        if best_candidate:
            entry_qty = self.base_entry_amt
            self.positions[best_candidate] = {
                'qty': entry_qty,
                'avg_price': prices[best_candidate],
                'dca_count': 0
            }
            return {
                'side': 'BUY',
                'symbol': best_candidate,
                'amount': entry_qty,
                'reason': ['ALPHA_ENTRY', f'Score_{best_score:.2f}']
            }
            
        return {}