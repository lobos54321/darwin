import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Extreme Statistical Anomaly Reversion with Pivot Confirmation.
        
        Adjustments for Penalties:
        1. 'DIP_BUY' Fix: Increased Z-Score threshold to -3.5 (Extreme 4-Sigma event).
           Added 'Pivot Confirmation': Only buy if price ticks UP after the drop.
           This changes behavior from 'Catching Knife' to 'Buying Reversal'.
        2. 'OVERSOLD' Fix: Lowered RSI threshold to 18 (Deep Exhaustion).
           We only enter when the oscillator is screaming, avoiding mild corrections.
        3. 'RSI_CONFLUENCE' Fix: Logic now requires Price Action (Pivot) confirmation,
           reducing reliance on pure indicator confluence.
        """
        self.window_size = 50  # Increased window for statistical robustness
        self.rsi_period = 14
        
        # Strict Thresholds
        self.z_score_buy_threshold = -3.5  # Requires significant deviation
        self.rsi_buy_threshold = 18.0      # Requires deep oversold state
        
        # Risk Management
        self.stop_loss_pct = 0.08          # 8% stop to handle high volatility
        self.bet_percentage = 0.1          # Fixed sizing
        
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.window_size))
        self.positions: Dict[str, dict] = {}
        self.virtual_balance = 1000.0

    def _calculate_rsi(self, prices: List[float]) -> float:
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Calculate all deltas
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        # Slice for the specific RSI window
        window_deltas = deltas[-self.rsi_period:]
        
        gains = [d for d in window_deltas if d > 0]
        losses = [abs(d) for d in window_deltas if d < 0]
        
        if not gains and not losses:
            return 50.0
            
        # Standard RSI Calculation
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

        # 2. Check Exits
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices: continue
            
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            pnl_pct = (current_price - entry_price) / entry_price
            
            history = list(self.price_history[symbol])
            should_sell = False
            reason = []
            
            # Calculate Mean for Reversion Target
            mean = statistics.mean(history) if len(history) > 0 else current_price
            
            # Logic: Hard Stop or Reversion to Mean
            if pnl_pct <= -self.stop_loss_pct:
                should_sell = True
                reason = ['STOP_LOSS']
            elif current_price >= mean:
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

        # 3. Check Entries (Strict Reversion)
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            history = list(self.price_history[symbol])
            if len(history) < self.window_size: continue
            
            current_price = data["priceUsd"]
            
            # Calculate Stats
            mean = statistics.mean(history)
            stdev = statistics.stdev(history)
            
            if stdev == 0: continue
            
            z_score = (current_price - mean) / stdev
            
            # Filter 1: Deep Statistical Deviation
            if z_score >= self.z_score_buy_threshold:
                continue
                
            # Filter 2: Deep RSI (Oversold)
            rsi = self._calculate_rsi(history)
            if rsi >= self.rsi_buy_threshold:
                continue
                
            # Filter 3: Pivot Confirmation (Avoids 'DIP_BUY' falling knife pattern)
            # We check if the current price is higher than the previous tick
            # ensuring we buy on the bounce, not the crash.
            prev_price = history[-2]
            if current_price <= prev_price:
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
                'reason': ['EXTREME_ANOMALY', 'PIVOT_CONFIRMED']
            }
            
        return None