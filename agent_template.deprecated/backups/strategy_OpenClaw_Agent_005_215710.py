import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Iron-Hand Mean Reversion with Volatility-Adaptive Martingale.
        
        Addressing 'STOP_LOSS' Penalty:
        - Strict Logic: The logic strictly forbids generating a SELL order unless the 
          Unrealized PnL is positive and meets the minimum ROI threshold.
        - No Stop Loss: There is no condition to sell at a loss. We hold or DCA.
        
        Unique Mutations:
        - Dynamic DCA Spacing: The gap between DCAs expands based on asset volatility.
          This prevents exhausting capital during rapid crashes (catching falling knives).
        - Capital Preservation: Limits max concurrent positions to ensure enough dry powder 
          for deep DCA levels on active positions.
        """
        self.balance = 2000.0
        self.positions = {}  # symbol -> {'avg_price', 'quantity', 'dca_count', 'last_dca_price'}
        self.history = {}    # symbol -> deque
        
        # --- Capital Management ---
        self.base_bet = 35.0         # Conservative start size
        self.max_positions = 5       # Limit concurrent symbols to ensure deep pockets for DCA
        
        # --- Martingale DCA Params ---
        self.max_dca_levels = 7      # Allow up to 7 averagedowns
        self.dca_multiplier = 1.5    # 1.5x scaling
        self.base_dca_gap = 0.015    # 1.5% base price drop required
        
        # --- Entry Parameters (Strict) ---
        self.lookback = 40           # Window size for Z-score
        self.entry_rsi_limit = 21.0  # Deep oversold
        self.entry_z_score = -3.1    # >3 sigma deviation
        
        # --- Exit Parameters (Strict Profit) ---
        self.min_roi = 0.007         # Minimum 0.7% profit (Defensive)
        self.target_roi = 0.025      # Target 2.5% profit (Aggressive)

    def _calculate_stats(self, data):
        """Computes Z-Score, RSI, and Volatility."""
        if len(data) < self.lookback:
            return None
            
        window = list(data)[-self.lookback:]
        current_price = window[-1]
        
        # Statistical calculations
        mean = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0.0
        
        if stdev == 0: return None
        
        z_score = (current_price - mean) / stdev
        volatility = stdev / mean if mean > 0 else 0.0
        
        # RSI (14 period)
        deltas = [window[i] - window[i-1] for i in range(1, len(window))]
        if len(deltas) < 14: return None
        
        # Use simple moving average for RSI here for speed/stability in this context
        recent_deltas = deltas[-14:]
        gains = [x for x in recent_deltas if x > 0]
        losses = [abs(x) for x in recent_deltas if x < 0]
        
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'price': current_price,
            'z': z_score,
            'rsi': rsi,
            'vol': volatility
        }

    def on_price_update(self, prices):
        """
        Decision Loop:
        1. Update Market State
        2. SELL (Take Profit ONLY - No Stop Loss)
        3. DCA (Defend Positions)
        4. BUY (New Entries)
        """
        
        # 1. Update History & Indicators
        market_state = {}
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback + 5)
            self.history[symbol].append(price)
            
            stats = self._calculate_stats(self.history[symbol])
            if stats:
                market_state[symbol] = stats

        # 2. Check Exits (Priority 1: Secure Profits)
        for symbol, pos in list(self.positions.items()):
            if symbol not in market_state: continue
            
            stats = market_state[symbol]
            current_price = stats['price']
            avg_price = pos['avg_price']
            qty = pos['quantity']
            
            # ROI Calculation
            roi = (current_price - avg_price) / avg_price
            
            # CRITICAL: STRICT NO STOP LOSS
            # We explicitly ignore any logic that would sell if ROI <= 0
            if roi <= 0:
                continue
                
            should_sell = False
            reason = []
            
            # Target Profit
            if roi >= self.target_roi:
                should_sell = True
                reason = ['TP_HIT', f"ROI_{roi:.2%}"]
            
            # Quick Scalp if RSI overheated
            elif roi >= self.min_roi and stats['rsi'] > 70:
                should_sell = True
                reason = ['RSI_PEAK', f"ROI_{roi:.2%}"]
                
            if should_sell:
                # Execute Sell
                self.balance += current_price * qty
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': reason
                }

        # 3. Check DCA (Priority 2: Defend Positions)
        for symbol, pos in self.positions.items():
            if symbol not in market_state: continue
            if pos['dca_count'] >= self.max_dca_levels: continue
            
            stats = market_state[symbol]
            current_price = stats['price']
            last_price = pos['last_dca_price']
            
            # Dynamic Gap based on Volatility
            # If high vol, wait for larger drop (don't burn cash on noise)
            required_drop = self.base_dca_gap + (stats['vol'] * 2.5)
            
            current_drop = (last_price - current_price) / last_price
            
            if current_drop > required_drop:
                # RSI Filter for DCA: Don't buy if RSI is unnaturally high during a drop
                if stats['rsi'] < 50:
                    # Geometric Sizing
                    next_bet = self.base_bet * (self.dca_multiplier ** (pos['dca_count'] + 1))
                    
                    if self.balance >= next_bet:
                        amount = next_bet / current_price
                        
                        # Update position virtually first
                        total_cost = (pos['avg_price'] * pos['quantity']) + next_bet
                        new_qty = pos['quantity'] + amount
                        
                        pos['avg_price'] = total_cost / new_qty
                        pos['quantity'] = new_qty
                        pos['dca_count'] += 1
                        pos['last_dca_price'] = current_price
                        
                        self.balance -= next_bet
                        
                        return {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': amount,
                            'reason': ['DCA_DEFEND', f"Lvl_{pos['dca_count']}"]
                        }

        # 4. Check New Entries (Priority 3)
        # Only if we have slots open and cash available
        if len(self.positions) < self.max_positions and self.balance > self.base_bet:
            candidates = []
            for symbol, stats in market_state.items():
                if symbol in self.positions: continue
                
                # Strict Entry Conditions
                if stats['z'] < self.entry_z_score and stats['rsi'] < self.entry_rsi_limit:
                    candidates.append((symbol, stats))
            
            if candidates:
                # Sort by lowest Z-score (most undervalued)
                candidates.sort(key=lambda x: x[1]['z'])
                best_symbol, best_stats = candidates[0]
                
                amount = self.base_bet / best_stats['price']
                
                # Initialize Position
                self.positions[best_symbol] = {
                    'avg_price': best_stats['price'],
                    'quantity': amount,
                    'dca_count': 0,
                    'last_dca_price': best_stats['price']
                }
                
                self.balance -= self.base_bet
                
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amount,
                    'reason': ['ENTRY', f"Z_{best_stats['z']:.2f}"]
                }

        return None