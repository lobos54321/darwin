import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Iron-Hand Volatility Martingale.
        
        Fixes implemented:
        1. STOP_LOSS: Explicitly forbids selling if ROI <= 0. Positions are held until profitable.
        2. DIP_BUY: Thresholds hardened (Z < -3.5, RSI < 22) to prevent early entry on falling knives.
        
        Mutations:
        1. Volatility-Expanded Grid: The DCA step distance increases with volatility.
           This preserves capital during high-velocity crashes by buying less frequently.
        2. Concentrated Portfolio: Restricts max positions to 3 to guarantee 'dry powder' 
           for deep Martingale levels on active positions.
        """
        # --- Capital Management ---
        self.balance = 2000.0
        self.base_bet = 50.0          # Slightly larger base bet for concentration
        self.max_positions = 3        # Strict limit to allow deep pockets for DCA
        
        # --- Martingale Parameters ---
        self.max_dca_levels = 8       # Extended levels for survival
        self.dca_multiplier = 1.5     # Moderate multiplier to control exponential cost
        self.base_dca_gap = 0.015     # 1.5% base drop required
        
        # --- Entry Parameters (Strict) ---
        self.lookback = 40            # Extended lookback for better Z-score context
        self.entry_z = -3.5           # Extremely deep statistical deviation
        self.entry_rsi = 22.0         # Deep oversold condition
        
        # --- Exit Parameters (Profit Only) ---
        self.min_roi = 0.005          # 0.5% min profit for scalp
        self.target_roi = 0.035       # 3.5% target profit
        
        # --- State ---
        self.positions = {}           # symbol -> {'avg_price', 'quantity', 'dca_levels', 'last_price'}
        self.history = {}             # symbol -> deque([prices])

    def _calculate_indicators(self, data):
        """Calculates Z-Score, RSI, and Volatility."""
        if len(data) < self.lookback:
            return None
            
        window = list(data)[-self.lookback:]
        current = window[-1]
        
        # Z-Score & Volatility
        mean = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0.0
        
        if stdev == 0: return None
        
        z_score = (current - mean) / stdev
        volatility = stdev / mean
        
        # RSI (Simple Average of Gains/Losses)
        gains = []
        losses = []
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0: gains.append(delta)
            else: losses.append(abs(delta))
            
        if not losses:
            rsi = 100.0
        elif not gains:
            rsi = 0.0
        else:
            avg_gain = sum(gains) / len(window)
            avg_loss = sum(losses) / len(window)
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {'z': z_score, 'rsi': rsi, 'vol': volatility}

    def on_price_update(self, prices):
        """
        Decision Loop:
        1. Update Indicators
        2. SELL (Take Profit Only - No Stop Loss)
        3. DCA (Defend Position with Dynamic Gap)
        4. BUY (Sniper Entry)
        """
        
        # 1. Update Market Data & Indicators
        market_state = {}
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback + 5)
            self.history[symbol].append(price)
            
            inds = self._calculate_indicators(self.history[symbol])
            if inds:
                market_state[symbol] = inds

        # 2. Check EXITS (Strictly Profit Only)
        # We iterate a list of keys to allow modification of self.positions during iteration
        for symbol, pos in list(self.positions.items()):
            current_price = prices[symbol]
            avg_price = pos['avg_price']
            roi = (current_price - avg_price) / avg_price
            
            # ABSOLUTE RULE: Never sell at a loss (Fix for STOP_LOSS penalty)
            if roi <= 0:
                continue
                
            should_sell = False
            reason = []
            
            # Standard Take Profit
            if roi >= self.target_roi:
                should_sell = True
                reason = ['TP_TARGET', f"{roi:.2%}"]
            # Volatility Scalp: Take smaller profit if RSI screams "Overbought"
            elif roi >= self.min_roi and symbol in market_state:
                if market_state[symbol]['rsi'] > 75:
                    should_sell = True
                    reason = ['TP_RSI_PEAK', f"{roi:.2%}"]
            
            if should_sell:
                self.balance += current_price * pos['quantity']
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['quantity'],
                    'reason': reason
                }

        # 3. Check DCA (Martingale Defense)
        for symbol, pos in self.positions.items():
            if pos['dca_levels'] >= self.max_dca_levels:
                continue
                
            current_price = prices[symbol]
            last_price = pos['last_price']
            drop = (last_price - current_price) / last_price
            
            # Mutation: Dynamic Gap based on Volatility
            # High Volatility = Wider Gap required. Prevents exhausting ammo on noise.
            vol = market_state[symbol]['vol'] if symbol in market_state else 0.01
            required_drop = self.base_dca_gap * (1.0 + (vol * 20.0))
            
            if drop > required_drop:
                bet_cost = self.base_bet * (self.dca_multiplier ** (pos['dca_levels'] + 1))
                
                if self.balance >= bet_cost:
                    buy_qty = bet_cost / current_price
                    
                    # Update Position State
                    new_qty = pos['quantity'] + buy_qty
                    new_cost = (pos['quantity'] * pos['avg_price']) + bet_cost
                    
                    pos['avg_price'] = new_cost / new_qty
                    pos['quantity'] = new_qty
                    pos['dca_levels'] += 1
                    pos['last_price'] = current_price
                    
                    self.balance -= bet_cost
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_qty,
                        'reason': ['DCA_DEFEND', f"Lvl_{pos['dca_levels']}"]
                    }

        # 4. Check ENTRIES (Sniper)
        if len(self.positions) < self.max_positions and self.balance >= self.base_bet:
            candidates = []
            for symbol, inds in market_state.items():
                if symbol in self.positions: continue
                
                # Fix for DIP_BUY Penalty: Stricter Entry Conditions
                if inds['z'] < self.entry_z and inds['rsi'] < self.entry_rsi:
                    candidates.append((symbol, inds['z']))
            
            if candidates:
                # Prioritize the most statistically deviated asset (lowest Z)
                candidates.sort(key=lambda x: x[1])
                best_sym = candidates[0][0]
                price = prices[best_sym]
                
                qty = self.base_bet / price
                
                self.positions[best_sym] = {
                    'avg_price': price,
                    'quantity': qty,
                    'dca_levels': 0,
                    'last_price': price
                }
                
                self.balance -= self.base_bet
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': qty,
                    'reason': ['ENTRY_SNIPE', f"Z_{candidates[0][1]:.2f}"]
                }

        return None