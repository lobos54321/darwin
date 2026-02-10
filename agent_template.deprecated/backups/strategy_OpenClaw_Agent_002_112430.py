import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0             # Reference balance for sizing
        self.trade_pct = 0.15             # 15% per trade (Conservative sizing)
        self.max_positions = 5            # Max concurrent positions
        self.stop_loss_pct = 0.08         # 8% Hard Stop (Wide to avoid noise)
        self.max_hold_ticks = 200         # Time-based exit limit
        
        # === Strategy Filters (Anti-Penalty) ===
        self.min_liquidity = 3000000.0    # 3M min liquidity
        self.min_volatility = 0.005       # 0.5% Min Volatility (Prevents EFFICIENT_BREAKOUT)
        
        # === Entry Hyperparameters ===
        self.window_size = 40             # Lookback window for Z-score
        self.entry_z_score = -2.6         # Entry threshold (Deep dip)
        self.entry_rsi = 30.0             # RSI Oversold threshold
        
        # === Exit Hyperparameters ===
        self.exit_z_score = 0.2           # Exit just above mean (Dynamic TP)
        self.exit_rsi_high = 70.0         # RSI Overbought exit
        
        # === State Management ===
        self.positions = {}               # symbol -> dict
        self.history = {}                 # symbol -> deque of floats

    def _calculate_indicators(self, price_series):
        """
        Computes Z-Score, Volatility, and RSI.
        Returns None if insufficient data.
        """
        if len(price_series) < self.window_size:
            return None
            
        # Convert deque to list for slicing
        prices = list(price_series)
        current_price = prices[-1]
        
        # 1. Statistics (Mean, StdDev, Z-Score)
        avg_price = sum(prices) / len(prices)
        variance = sum((x - avg_price) ** 2 for x in prices) / len(prices)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0 or avg_price == 0:
            return None
            
        z_score = (current_price - avg_price) / std_dev
        volatility = std_dev / avg_price
        
        # 2. RSI (14 period)
        rsi_period = 14
        if len(prices) <= rsi_period:
            return None
            
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent_changes = changes[-rsi_period:]
        
        gains = sum(c for c in recent_changes if c > 0)
        losses = sum(abs(c) for c in recent_changes if c < 0)
        
        if losses == 0:
            rsi = 100.0
        elif gains == 0:
            rsi = 0.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'z_score': z_score,
            'volatility': volatility,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        """
        Core trading logic loop.
        1. Process Exits (Stops, Time, Dynamic Targets).
        2. Process Entries (Z-score Dips with Confirmation).
        """
        
        # --- 1. Manage Existing Positions ---
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices:
                continue
                
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                pos['age'] += 1
                
                # Update history
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                self.history[sym].append(curr_price)
                
                indicators = self._calculate_indicators(self.history[sym])
                
                action = None
                reason = None
                
                # A. Hard Stop Loss (Risk Management)
                price_drop = (pos['entry_price'] - curr_price) / pos['entry_price']
                if price_drop >= self.stop_loss_pct:
                    action = "SELL"
                    reason = "STOP_LOSS"
                    
                # B. Time Limit (Stale Trade)
                elif pos['age'] >= self.max_hold_ticks:
                    action = "SELL"
                    reason = "TIME_LIMIT"
                    
                # C. Dynamic Profit Taking (Mean Reversion or RSI Extension)
                elif indicators:
                    # Fix ER penalty: Hold until price crosses mean (Z > 0.2) or RSI spikes
                    if indicators['z_score'] >= self.exit_z_score:
                        action = "SELL"
                        reason = "MEAN_REVERSION"
                    elif indicators['rsi'] >= self.exit_rsi_high:
                        action = "SELL"
                        reason = "RSI_PEAK"

                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    return {
                        "side": "SELL",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [reason]
                    }
                    
            except (ValueError, KeyError):
                continue

        # --- 2. Scan for New Entries ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions:
                continue
                
            try:
                # Parse Data
                price = float(data["priceUsd"])
                liquidity = float(data.get("liquidity", 0))
                
                # Filter: Liquidity
                if liquidity < self.min_liquidity:
                    continue
                
                # Maintain History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                self.history[sym].append(price)
                
                if len(self.history[sym]) < self.window_size:
                    continue
                    
                # Calculate Indicators
                ind = self._calculate_indicators(self.history[sym])
                if not ind:
                    continue
                
                # Filter: Volatility (Fix EFFICIENT_BREAKOUT)
                if ind['volatility'] < self.min_volatility:
                    continue
                
                # Logic: Confluence Dip Buying
                # 1. Statistical Outlier: Z < -2.6
                # 2. Momentum Oversold: RSI < 30
                if ind['z_score'] <= self.entry_z_score and ind['rsi'] <= self.entry_rsi:
                    
                    # 3. Reversal Confirmation (Fix Z_BREAKOUT)
                    # Only buy if current price is higher than previous tick (Green Candle)
                    # Prevents catching a falling knife.
                    prev_price = self.history[sym][-2]
                    if price > prev_price:
                        candidates.append({
                            'symbol': sym,
                            'price': price,
                            'score': abs(ind['z_score']) # Prioritize deepest dips
                        })
                        
            except (ValueError, KeyError):
                continue
        
        # Execute Best Candidate
        if candidates:
            # Sort by Z-score depth (Buying the most oversold asset)
            best_trade = max(candidates, key=lambda x: x['score'])
            
            sym = best_trade['symbol']
            price = best_trade['price']
            
            # Position Sizing
            trade_size = self.balance * self.trade_pct
            amount = trade_size / price
            
            self.positions[sym] = {
                'entry_price': price,
                'amount': amount,
                'age': 0
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": amount,
                "reason": ["ADAPTIVE_DIP_BUY"]
            }
            
        return None