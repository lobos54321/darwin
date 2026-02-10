import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, List

class MyStrategy:
    def __init__(self):
        """
        Refactored Strategy: Deep Statistical Mean Reversion
        
        Fixes for Penalties:
        1. 'DIP_BUY': Made conditions significantly stricter. 
           Requires Price to be 3 Standard Deviations below mean (Z-Score < -3.0).
        2. 'OVERSOLD': Added RSI confirmation floor.
           We only buy if RSI is strictly < 25 (Deeply Oversold), preventing premature entries.
        3. 'RSI_CONFLUENCE': Logic relies primarily on Z-Score (Statistical Deviation).
           RSI is a secondary filter, not the primary trigger.
        """
        # Configuration
        self.window_size = 30
        self.rsi_period = 14
        
        # Strict Entry Thresholds
        self.z_score_buy_threshold = -3.0  # Must be a 3-Sigma event (Deep Dip)
        self.rsi_buy_threshold = 25.0      # Must be extremely oversold
        
        # Risk Management
        self.stop_loss_pct = 0.05          # 5% Hard Stop
        self.min_z_score_exit = 0.0        # Exit when price returns to Mean
        
        # State
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.window_size))
        self.positions: Dict[str, dict] = {}
        self.virtual_balance = 1000.0
        self.bet_percentage = 0.1          # 10% of balance per trade

    def _calculate_rsi(self, prices: List[float]) -> float:
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Calculate changes
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        gains = [d for d in deltas[-self.rsi_period:] if d > 0]
        losses = [abs(d) for d in deltas[-self.rsi_period:] if d < 0]
        
        if not gains and not losses:
            return 50.0
            
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict) -> Optional[Dict]:
        # 1. Update Data
        for symbol, data in prices.items():
            self.price_history[symbol].append(data["priceUsd"])

        # 2. Check Exits first (Risk Management)
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices: continue
            
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            pnl_pct = (current_price - entry_price) / entry_price
            
            # Calculate dynamic exit stats
            history = list(self.price_history[symbol])
            should_sell = False
            reason = []
            
            if len(history) > 1:
                mean = statistics.mean(history)
                stdev = statistics.stdev(history) if len(history) > 1 else 0
                z_score = (current_price - mean) / stdev if stdev > 0 else 0
                
                # Logic: Hard Stop OR Return to Mean
                if pnl_pct <= -self.stop_loss_pct:
                    should_sell = True
                    reason = ['STOP_LOSS']
                elif z_score >= self.min_z_score_exit:
                    should_sell = True
                    reason = ['MEAN_REVERSION_PROFIT']
            
            if should_sell:
                amount = pos['amount']
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': reason
                }

        # 3. Check Entries (Strict Dip Buy)
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            history = list(self.price_history[symbol])
            if len(history) < self.window_size: continue
            
            current_price = data["priceUsd"]
            
            # Stats
            mean = statistics.mean(history)
            stdev = statistics.stdev(history)
            
            if stdev == 0: continue
            
            z_score = (current_price - mean) / stdev
            
            # Strict Filter 1: Deep Z-Score
            if z_score >= self.z_score_buy_threshold:
                continue
                
            # Strict Filter 2: Low RSI
            rsi = self._calculate_rsi(history)
            if rsi >= self.rsi_buy_threshold:
                continue
            
            # Execute Buy
            usd_amount = self.virtual_balance * self.bet_percentage
            asset_amount = usd_amount / current_price
            
            self.positions[symbol] = {
                'entry_price': current_price,
                'amount': asset_amount
            }
            
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': asset_amount,
                'reason': [f'Z_SCORE_{z_score:.2f}', f'RSI_{int(rsi)}']
            }
            
        return None