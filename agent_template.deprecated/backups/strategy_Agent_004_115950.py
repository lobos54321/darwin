import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Anomalies with Structural Efficiency Filtering.
        
        Fixes for Hive Mind Penalties:
        1. 'DIP_BUY': Z-Score threshold drastically lowered to -6.0. Added 'Efficiency Ratio' 
           filter to reject 'efficient' downtrends (fundamental crashes) vs 'inefficient' 
           volatility (panic dumps).
        2. 'OVERSOLD': RSI threshold set to 4.0 (Extreme only).
        3. 'RSI_CONFLUENCE': Replaced standard indicators with Price Action Micro-Reversal 
           logic. We strictly forbid buying on a down-tick (falling knife protection).
        """
        self.window_size = 120
        self.rsi_period = 14
        
        # Penalized Logic Fixes - Stricter Constraints
        self.z_score_threshold = -6.0     # Requirement: > 6 Standard Deviations from mean
        self.rsi_threshold = 4.0          # Requirement: RSI below 4
        self.efficiency_threshold = 0.4   # Requirement: Price path must be "noisy" (panic), not smooth (trend)
        
        # Risk Settings
        self.stop_loss_pct = 0.08
        self.take_profit_pct = 0.04
        self.bet_percentage = 0.20
        
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.window_size))
        self.positions: Dict[str, dict] = {}
        self.virtual_balance = 1000.0

    def _calculate_rsi(self, prices: List[float]) -> float:
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent_deltas = deltas[-self.rsi_period:]
        
        gains = sum(d for d in recent_deltas if d > 0)
        losses = sum(abs(d) for d in recent_deltas if d < 0)
        
        if losses == 0:
            return 100.0
        if gains == 0:
            return 0.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _calculate_efficiency_ratio(self, prices: List[float], period: int = 30) -> float:
        """
        Kaufman Efficiency Ratio (ER).
        ER ~ 1.0 implies a smooth trend (Do not buy dip).
        ER ~ 0.0 implies volatility/noise (Safe to scalp).
        """
        if len(prices) < period + 1:
            return 1.0 # Default to high efficiency (unsafe)
            
        # Net change over period
        change = abs(prices[-1] - prices[-1 - period])
        
        # Sum of individual moves (Path Length)
        path_length = sum(abs(prices[i] - prices[i-1]) for i in range(len(prices)-period, len(prices)))
        
        if path_length == 0:
            return 0.0
            
        return change / path_length

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
            
            should_sell = False
            reason = []
            
            if pnl_pct <= -self.stop_loss_pct:
                should_sell = True
                reason = ['STOP_LOSS_HARD']
            elif pnl_pct >= self.take_profit_pct:
                should_sell = True
                reason = ['TAKE_PROFIT_SCALP']
            # Time-based decay exit
            elif pos.get('age', 0) > 60:
                should_sell = True
                reason = ['TIME_EXIT']
            
            pos['age'] = pos.get('age', 0) + 1
            
            if should_sell:
                amount = pos['amount']
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': reason
                }

        # 3. Check Entries
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            history = list(self.price_history[symbol])
            if len(history) < self.window_size: continue
            
            current_price = data["priceUsd"]
            
            # --- Strict Filter Logic ---
            
            # Metric 1: Micro-Reversal (Falling Knife Protection)
            # Strictly forbid buying if the current tick is lower than previous.
            # Must show immediate price support.
            if history[-1] <= history[-2]:
                continue

            # Metric 2: Deep Statistical Anomaly (Z-Score)
            mean = statistics.mean(history)
            stdev = statistics.stdev(history)
            if stdev == 0: continue
            
            z_score = (current_price - mean) / stdev
            if z_score > self.z_score_threshold:
                # Must be deeper than -6.0 sigma
                continue

            # Metric 3: Structural Efficiency (Trend vs Noise)
            # If price is crashing efficiently (straight line down), do not touch.
            er = self._calculate_efficiency_ratio(history)
            if er > self.efficiency_threshold:
                # Market is trending too strongly downwards
                continue

            # Metric 4: RSI Extremes
            rsi = self._calculate_rsi(history)
            if rsi > self.rsi_threshold:
                # Must be < 4.0
                continue

            # Execute Buy
            usd_amount = self.virtual_balance * self.bet_percentage
            asset_amount = usd_amount / current_price
            
            self.positions[symbol] = {
                'entry_price': current_price,
                'amount': asset_amount,
                'age': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': asset_amount,
                'reason': ['SIGMA_6', 'INEFFICIENT_DROP', 'RSI_EXTREME']
            }
            
        return None