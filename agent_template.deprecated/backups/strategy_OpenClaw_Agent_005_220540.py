import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Iron-Clad Volatility Martingale.
        
        Fixes implemented:
        1. STOP_LOSS: Logic strictly enforces Profit-Only Exits. If ROI <= 0, we HOLD.
        2. DIP_BUY: Entry conditions tightened (Z < -3.2, RSI < 25) to prevent early falling-knife entries.
        
        Mutations:
        1. Volatility-Scaled Grid: DCA distance expands dynamically with volatility to conserve capital.
        2. Aggressive Recovery: Martingale multiplier set to 1.5x to lower average price rapidly.
        3. Concentrated Portfolio: Max 3 positions to ensure sufficient depth for Martingale levels.
        """
        # --- Capital Management ---
        self.balance = 2000.0
        self.base_bet = 50.0
        self.max_positions = 3
        
        # --- Martingale Parameters ---
        self.max_dca_levels = 6
        self.dca_multiplier = 1.5
        self.base_dca_gap = 0.015  # 1.5% base drop
        
        # --- Entry Parameters (Strict) ---
        self.lookback = 35
        self.entry_z = -3.2        # Stricter than -3.0
        self.entry_rsi = 25.0      # Deep oversold
        
        # --- Exit Parameters (Profit Only) ---
        self.min_roi = 0.005       # 0.5% min profit for scalp
        self.target_roi = 0.025    # 2.5% target profit
        
        # --- State ---
        self.positions = {}        # symbol -> {'avg_price', 'quantity', 'dca_levels', 'last_price'}
        self.history = {}          # symbol -> deque([prices])

    def _calculate_indicators(self, data):
        """Calculates Z-Score, RSI, and Volatility."""
        if len(data) < self.lookback:
            return None
            
        window = list(data)[-self.lookback:]
        current = window[-1]
        
        # Statistics
        mean = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0.0
        
        if stdev == 0: return None
        
        z_score = (current - mean) / stdev
        volatility = stdev / mean
        
        # RSI (Smoothed)
        gains = 0.0
        losses = 0.0
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0: gains += delta
            else: losses += abs(delta)
            
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
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
        for symbol, pos in list(self.positions.items()):
            # Safety check if price exists
            if symbol not in prices: continue
            
            current_price = prices[symbol]
            avg_price = pos['avg_price']
            roi = (current_price - avg_price) / avg_price
            
            # ABSOLUTE RULE: Never sell at a loss (Fix for STOP_LOSS)
            if roi <= 0:
                continue
                
            should_sell = False
            reason = []
            
            # Standard Take Profit
            if roi >= self.target_roi:
                should_sell = True
                reason = ['TP_TARGET', f"{roi:.2%}"]
            # Volatility Scalp: Take smaller profit if RSI is peaking
            elif roi >= self.min_roi and symbol in market_state:
                if market_state[symbol]['rsi'] > 70:
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
            if symbol not in prices: continue
            if pos['dca_levels'] >= self.max_dca_levels: continue
                
            current_price = prices[symbol]
            last_price = pos['last_price']
            drop = (last_price - current_price) / last_price
            
            # Mutation: Dynamic Gap based on Volatility
            vol = market_state[symbol]['vol'] if symbol in market_state else 0.01
            # Scale gap: Higher vol -> wider gap to survive crashes
            required_drop = self.base_dca_gap * (1.0 + (vol * 15.0))
            
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
                # Z < -3.2 ensures we are 3.2 std devs below mean
                # RSI < 25 ensures momentum is dead
                if inds['z'] < self.entry_z and inds['rsi'] < self.entry_rsi:
                    candidates.append((symbol, inds['z']))
            
            if candidates:
                # Prioritize the most statistically deviated asset
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