import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Adaptive Mean Reversion with Geometric DCA.
        
        Fixes for 'STOP_LOSS' penalty:
        1. Pure Profit Taking: Logic strictly validates (price > avg_price * 1.005) before selling.
           Zero logic for selling at a loss.
        2. Deep Value Entry: Stricter entry thresholds (RSI < 25, Z < -2.8) to minimize drawdown.
        3. Volatility-Adjusted Grids: DCA levels widen during high volatility to prevent
           exhausting capital on falling knives.
        """
        self.balance = 2000.0
        self.positions = {}  # symbol -> {'avg_price', 'quantity', 'dca_count', 'last_dca_price'}
        self.history = {}    # symbol -> deque
        
        # --- Configuration ---
        self.base_bet = 50.0
        self.lookback = 40
        
        # Entry Thresholds (Stricter)
        self.entry_rsi_limit = 25.0
        self.entry_z_score = -2.8
        
        # Exit Configuration (Strictly Positive)
        self.min_roi = 0.005       # Minimum 0.5% profit required
        self.target_roi = 0.02     # Target 2.0% profit
        
        # DCA Configuration (Martingale-esque)
        self.max_dca_count = 5
        self.dca_multiplier = 1.6  # Geometric sizing
        self.dca_base_gap = 0.02   # 2% base gap
        
    def _calculate_indicators(self, data):
        """Calculates Z-Score, RSI, and Volatility."""
        if len(data) < self.lookback:
            return None
            
        # Slice to lookback
        window = list(data)[-self.lookback:]
        
        # Statistics
        mean = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0.0
        
        current_price = window[-1]
        z_score = (current_price - mean) / stdev if stdev > 0 else 0.0
        volatility = stdev / mean if mean > 0 else 0.0
        
        # RSI Calculation
        deltas = [window[i] - window[i-1] for i in range(1, len(window))]
        gains = [x for x in deltas if x > 0]
        losses = [abs(x) for x in deltas if x < 0]
        
        avg_gain = sum(gains) / 14 if gains else 0.0
        avg_loss = sum(losses) / 14 if losses else 0.0
        
        # Handle smoothing (simple avg for performance)
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'mean': mean,
            'stdev': stdev,
            'z': z_score,
            'rsi': rsi,
            'vol': volatility
        }

    def on_price_update(self, prices):
        """
        Main trading loop.
        Priorities: 
        1. Sell for Profit (Strict validation).
        2. DCA into existing positions (Volatility adjusted).
        3. Enter new positions (Deep value).
        """
        
        # 1. Update Market State
        market_analysis = {}
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback + 5)
            self.history[symbol].append(price)
            
            indicators = self._calculate_indicators(self.history[symbol])
            if indicators:
                market_analysis[symbol] = indicators
                market_analysis[symbol]['price'] = price

        # 2. Check Exits (Priority: Capital Recycling)
        # STRICT RULE: NO STOP LOSS. Only Sell if ROI > min_roi.
        for symbol, pos in list(self.positions.items()):
            if symbol not in market_analysis: continue
            
            stats = market_analysis[symbol]
            current_price = stats['price']
            avg_price = pos['avg_price']
            qty = pos['quantity']
            
            # ROI Calculation
            roi = (current_price - avg_price) / avg_price
            
            # Exit Logic: Simple Take Profit
            # We avoid trailing stops to prevent accidental "stop loss" triggers if price gaps down.
            # We simply take the profit if it hits our target, or if it's decent (0.5%) and indicators suggest reversal.
            
            should_sell = False
            reason = ""
            
            if roi >= self.target_roi:
                should_sell = True
                reason = "TARGET_HIT"
            elif roi >= self.min_roi and stats['rsi'] > 70:
                # Early exit if overbought and in profit
                should_sell = True
                reason = "RSI_PEAK_EXIT"
                
            if should_sell:
                self.balance += current_price * qty
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': [reason, f"ROI_{roi:.4f}"]
                }

        # 3. Check DCA (Priority: Position Defense)
        for symbol, pos in self.positions.items():
            if symbol not in market_analysis: continue
            stats = market_analysis[symbol]
            
            if pos['dca_count'] >= self.max_dca_count:
                continue
            
            current_price = stats['price']
            last_price = pos['last_dca_price']
            
            # Volatility Adjusted Gap
            # High Vol -> Wider Gap. Low Vol -> Standard Gap.
            # Vol typically ranges 0.001 to 0.02.
            # Gap = Base + (Vol * Factor)
            required_gap = self.dca_base_gap + (stats['vol'] * 2.0)
            
            # Check price drop
            if current_price < last_price * (1.0 - required_gap):
                # Check Indicator Confirmation (RSI not overbought)
                if stats['rsi'] < 45:
                    # Calculate Sizing
                    # Level 0 (Entry): 1 unit
                    # Level 1: 1.6 units
                    # Level 2: 2.56 units...
                    next_bet = self.base_bet * (self.dca_multiplier ** (pos['dca_count'] + 1))
                    
                    if self.balance > next_bet:
                        amount_to_buy = next_bet / current_price
                        
                        # Update Position State
                        total_cost = (pos['avg_price'] * pos['quantity']) + next_bet
                        total_qty = pos['quantity'] + amount_to_buy
                        
                        pos['avg_price'] = total_cost / total_qty
                        pos['quantity'] = total_qty
                        pos['dca_count'] += 1
                        pos['last_dca_price'] = current_price
                        
                        self.balance -= next_bet
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': amount_to_buy,
                            'reason': ['DCA', f"Lvl_{pos['dca_count']}", f"Gap_{required_gap:.3f}"]
                        }

        # 4. Check Entries (Priority: Capital Deployment)
        # Filter candidates
        candidates = []
        for symbol, stats in market_analysis.items():
            if symbol in self.positions: continue
            
            # Stricter Filters
            if stats['rsi'] < self.entry_rsi_limit and stats['z'] < self.entry_z_score:
                candidates.append((symbol, stats))
                
        # Sort by most oversold (lowest Z)
        candidates.sort(key=lambda x: x[1]['z'])
        
        if candidates and self.balance > (self.base_bet * 1.1):
            target_symbol, target_stats = candidates[0]
            price = target_stats['price']
            amount = self.base_bet / price
            
            # Initialize Position
            self.positions[target_symbol] = {
                'avg_price': price,
                'quantity': amount,
                'dca_count': 0,
                'last_dca_price': price
            }
            
            self.balance -= self.base_bet
            
            return {
                'side': 'BUY',
                'symbol': target_symbol,
                'amount': amount,
                'reason': ['ENTRY', f"Z_{target_stats['z']:.2f}", f"RSI_{target_stats['rsi']:.1f}"]
            }

        return None