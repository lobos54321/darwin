import math
import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, List, Any

class MyStrategy:
    """
    Agent_006: "Kinetic Momentum"
    
    Addressed Penalties: ['DIP_BUY', 'OVERSOLD', 'RSI_CONFLUENCE']
    
    Logic Changes:
    1.  **Anti-Dip Logic**: We completely removed mean reversion. We only buy positive volatility breakouts.
    2.  **Stricter Entry**: Z-Score threshold raised to 2.5 (was 2.0). Price must be 2.5 std devs ABOVE the mean.
    3.  **RSI Floor**: Added strict RSI > 55 check. We never buy when 'Oversold'.
    4.  **Trend Confirmation**: Added Linear Regression Slope check to ensure we are buying into an uptrend.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Agent_006: Kinetic Momentum)")
        
        # --- Configuration ---
        self.history_len = 50           # Extended for better trend context
        self.min_history = 30           # Min data points before trading
        
        # Entry Filters (Strict Momentum)
        self.z_entry_threshold = 2.5    # Price must be exceptional (Breakout)
        self.slope_threshold = 0.0      # Trend must be positive
        self.rsi_min_filter = 55.0      # Only buy in Bullish RSI territory (Avoid OVERSOLD tags)
        
        # Risk Settings
        self.stop_loss_fixed = 0.025    # 2.5% Hard Stop
        self.take_profit = 0.06         # 6% Target
        self.trailing_arm = 0.02        # Arm trailing stop after 2% profit
        self.trailing_gap = 0.01        # 1% trailing distance
        
        # --- State ---
        self.prices_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_len))
        self.positions: Dict[str, dict] = {} 
        self.virtual_balance = 1000.0   
        self.bet_size = 0.2             

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculates RSI to ensure we aren't in OVERSOLD territory."""
        if len(prices) < period + 1: return 50.0
        
        # Calculate changes
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        # Use last 'period' changes
        recent_deltas = deltas[-period:]
        
        gains = [d for d in recent_deltas if d > 0]
        losses = [abs(d) for d in recent_deltas if d < 0]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calculate_slope(self, prices: List[float]) -> float:
        """Calculates linear regression slope to confirm trend direction."""
        n = len(prices)
        if n < 2: return 0.0
        
        x = list(range(n))
        y = prices
        mean_x = statistics.mean(x)
        mean_y = statistics.mean(y)
        
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        denominator = sum((xi - mean_x) ** 2 for xi in x)
        
        return numerator / denominator if denominator != 0 else 0.0

    def on_price_update(self, prices: dict) -> Dict:
        decision = None
        
        # 1. Process Data & Check Exits (Priority)
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            self.prices_history[symbol].append(current_price)
            
            if symbol in self.positions:
                exit_signal = self._check_exits(symbol, current_price)
                if exit_signal:
                    return exit_signal 
        
        # 2. Check Entries (Strict Breakout only)
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            history = list(self.prices_history[symbol])
            if len(history) < self.min_history: continue
            
            current_price = data["priceUsd"]
            
            # --- Indicators ---
            avg = statistics.mean(history)
            stdev = statistics.stdev(history)
            if stdev == 0: continue
            
            z_score = (current_price - avg) / stdev
            
            # --- Strict Filters to fix Penalties ---
            
            # 1. FIX 'DIP_BUY': Must be a high breakout (Z > 2.5), not a dip.
            if z_score <= self.z_entry_threshold: continue
                
            # 2. FIX 'OVERSOLD'/'RSI_CONFLUENCE': RSI must be > 55 (Momentum).
            rsi = self._calculate_rsi(history)
            if rsi < self.rsi_min_filter: continue
            
            # 3. Confirmation: Positive Trend Slope
            slope = self._calculate_slope(history[-10:]) # Slope of last 10 ticks
            if slope <= self.slope_threshold: continue
            
            candidates.append({
                'symbol': symbol,
                'price': current_price,
                'z_score': z_score
            })
        
        # Select best Momentum Candidate
        if candidates:
            best = max(candidates, key=lambda x: x['z_score'])
            
            usd_size = self.virtual_balance * self.bet_size
            amount = usd_size / best['price']
            
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'highest_price': best['price'],
                'amount': amount
            }
            
            decision = {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': ['STRICT_BREAKOUT', f"Z:{best['z_score']:.2f}", 'NO_DIP']
            }
            
        return decision

    def _check_exits(self, symbol: str, current_price: float) -> Optional[Dict]:
        pos = self.positions[symbol]
        entry = pos['entry_price']
        high = pos['highest_price']
        amount = pos['amount']
        
        # Update High Water Mark
        if current_price > high:
            pos['highest_price'] = current_price
            high = current_price
            
        pnl_pct = (current_price - entry) / entry
        drawdown_from_peak = (high - current_price) / high
        
        reason = []
        should_sell = False
        
        if pnl_pct < -self.stop_loss_fixed:
            should_sell = True
            reason.append('STOP_LOSS')
        elif pnl_pct > self.take_profit:
            should_sell = True
            reason.append('TAKE_PROFIT')
        elif pnl_pct > self.trailing_arm and drawdown_from_peak > self.trailing_gap:
            should_sell = True
            reason.append('TRAILING_STOP')

        if should_sell:
            pnl_val = (current_price - entry) * amount
            self.virtual_balance += pnl_val
            del self.positions[symbol]
            return {
                'side': 'SELL',
                'symbol': symbol,
                'amount': amount,
                'reason': reason
            }
            
        return None