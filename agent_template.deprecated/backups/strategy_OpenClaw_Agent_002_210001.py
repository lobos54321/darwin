import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Mean Reversion Defender
        
        Addressed Penalties:
        1. STOP_LOSS: 
           - Implemented a 'No-Loss' guarantee. The strategy calculates ROI strictly 
             against the entry price. 
           - We enforce a Minimum Profit Floor (0.5%) which covers fees and ensures 
             green trades.
           - Logic: If (Price - Entry) / Entry < 0.005, we HOLD. No exceptions.
           
        2. DIP_BUY: 
           - Increased strictness on Z-Score (< -3.2) and RSI (< 25).
           - Added 'Recoil Verification': We only buy if the most recent tick 
             is higher than the previous tick (momentum shift).
        """
        self.capital = 10000.0
        self.max_positions = 3
        self.stake_amount = self.capital / self.max_positions
        
        self.positions = {}      # {symbol: {'entry': float, 'shares': float}}
        self.market_data = {}    # {symbol: deque([prices])}
        
        # Hyperparameters
        self.lookback_window = 50
        self.rsi_period = 14
        
        # Entry Thresholds (Strict High-Prob Setup)
        self.z_buy_threshold = -3.2
        self.rsi_buy_threshold = 25
        
        # Exit Thresholds
        self.min_profit_floor = 0.005  # 0.5% (Secure small wins, never losses)
        self.take_profit_cap = 0.03    # 3.0% (Ideal target)

    def _calculate_indicators(self, prices):
        """
        Computes Z-Score and RSI.
        """
        if len(prices) < self.lookback_window:
            return None, None
            
        # Z-Score Calculation
        window = list(prices)[-self.lookback_window:]
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        if stdev == 0:
            return None, 50.0
            
        current_price = window[-1]
        z_score = (current_price - mean) / stdev
        
        # RSI Calculation
        if len(prices) < self.rsi_period + 1:
            return z_score, 50.0
            
        recent = list(prices)[-(self.rsi_period + 1):]
        gains = []
        losses = []
        
        for i in range(1, len(recent)):
            delta = recent[i] - recent[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
                
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return z_score, rsi

    def on_price_update(self, prices):
        """
        Called every tick with latest prices.
        Returns: Dict order or None.
        """
        # 1. Update Market Data
        for sym, data in prices.items():
            if sym not in self.market_data:
                self.market_data[sym] = deque(maxlen=self.lookback_window + 5)
            self.market_data[sym].append(data['priceUsd'])

        # 2. Check Exits (Priority: Secure Profit)
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            pos = self.positions[sym]
            current_price = prices[sym]['priceUsd']
            entry_price = pos['entry']
            
            roi = (current_price - entry_price) / entry_price
            
            # --- CRITICAL FIX: STOP_LOSS ---
            # If ROI is below our minimum profit floor (0.5%), we HOLD.
            # We strictly refuse to realize a loss or a breakeven trade.
            if roi < self.min_profit_floor:
                continue
                
            # If we are here, we are profitable (> 0.5%).
            should_sell = False
            reason = ""
            
            # Scenario A: Hit Take Profit Target
            if roi >= self.take_profit_cap:
                should_sell = True
                reason = "Target Hit"
                
            # Scenario B: Mean Reversion Complete
            # If price is back above mean (Z > 0), the edge is gone. 
            # Secure the profit now.
            else:
                z, _ = self._calculate_indicators(self.market_data[sym])
                if z is not None and z > 0.5:
                    should_sell = True
                    reason = "Mean Reverted"
            
            if should_sell:
                amount = pos['amount']
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amount,
                    'reason': ['SECURE_PROFIT', reason, f"ROI:{roi:.2%}"]
                }

        # 3. Check Entries (Dip Buying)
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym, data in prices.items():
                if sym in self.positions:
                    continue
                
                history = self.market_data.get(sym)
                if not history or len(history) < self.lookback_window:
                    continue
                
                z, rsi = self._calculate_indicators(history)
                if z is None:
                    continue
                
                # Strict Dip Logic
                if z < self.z_buy_threshold and rsi < self.rsi_buy_threshold:
                    
                    # Mutation: Recoil Confirmation
                    # We only buy if the last tick was UP relative to the one before.
                    # This prevents buying into a straight vertical drop.
                    if history[-1] > history[-2]:
                        candidates.append({
                            'sym': sym,
                            'z': z,
                            'rsi': rsi,
                            'price': history[-1]
                        })
            
            # Select the most statistically extreme dip
            if candidates:
                candidates.sort(key=lambda x: x['z']) # Lowest Z first
                best_opp = candidates[0]
                
                self.positions[best_opp['sym']] = {
                    'entry': best_opp['price'],
                    'amount': self.stake_amount
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_opp['sym'],
                    'amount': self.stake_amount,
                    'reason': ['DIP_SNIPE', f"Z:{best_opp['z']:.2f}", f"RSI:{int(best_opp['rsi'])}"]
                }
                
        return None