import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Hyper-Extreme Statistical Reversion with Momentum Confirmation.
        
        Adjustments for Hive Mind Penalties:
        1. 'DIP_BUY' Fix: Tightened Z-Score threshold to -4.0. We only buy 4-Sigma events 
           (statistically rare crashes), not standard dips.
        2. 'OVERSOLD' Fix: Lowered RSI threshold to 12.0. We require the asset to be 
           in a state of 'Panic' rather than just 'Oversold'.
        3. 'RSI_CONFLUENCE' Fix: Logic now mandates positive price velocity (current > prev)
           to confirm the reversal has actually started, preventing falling knife entries.
        """
        self.window_size = 60  # Extended window for better statistical mean
        self.rsi_period = 14
        
        # Strict Thresholds
        self.z_score_buy_threshold = -4.0  # Requires extreme 4-sigma deviation
        self.rsi_buy_threshold = 12.0      # Requires deep panic/exhaustion
        
        # Risk Management
        self.stop_loss_pct = 0.12          # 12% stop to accommodate extreme volatility
        self.bet_percentage = 0.15         # Position sizing
        
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.window_size))
        self.positions: Dict[str, dict] = {}
        self.virtual_balance = 1000.0

    def _calculate_rsi(self, prices: List[float]) -> float:
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        window_deltas = deltas[-self.rsi_period:]
        
        gains = [d for d in window_deltas if d > 0]
        losses = [abs(d) for d in window_deltas if d < 0]
        
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

        # 2. Check Exits (Mean Reversion or Stop Loss)
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices: continue
            
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            pnl_pct = (current_price - entry_price) / entry_price
            
            history = list(self.price_history[symbol])
            should_sell = False
            reason = []
            
            # Dynamic Mean Target
            mean = statistics.mean(history) if len(history) > 0 else current_price
            
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

        # 3. Check Entries (Strict Anomalies)
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            history = list(self.price_history[symbol])
            if len(history) < self.window_size: continue
            
            current_price = data["priceUsd"]
            
            # Statistical Calculations
            mean = statistics.mean(history)
            stdev = statistics.stdev(history)
            
            if stdev == 0: continue
            
            z_score = (current_price - mean) / stdev
            
            # Filter 1: Extreme Deviation (Fix for DIP_BUY)
            if z_score >= self.z_score_buy_threshold:
                continue
                
            # Filter 2: Panic RSI (Fix for OVERSOLD)
            rsi = self._calculate_rsi(history)
            if rsi >= self.rsi_buy_threshold:
                continue
                
            # Filter 3: Momentum Confirmation (Fix for RSI_CONFLUENCE / FALLING KNIFE)
            # We strictly require the current tick to be higher than the previous tick
            # This confirms buyers are stepping in at these extreme levels.
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
                'reason': ['4_SIGMA_EVENT', 'PANIC_RSI', 'MOMENTUM_CONFIRMED']
            }
            
        return None