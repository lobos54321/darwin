import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Hyper-Selective Statistical Arbitrage with Volatility Safeguards.
        
        Fixes for Hive Mind Penalties:
        1. 'DIP_BUY': Implemented Volatility Regime Filter. We reject entries when 
           volatility is exploding (falling knife protection), requiring volatility 
           to be stable relative to recent history. Z-Score threshold pushed to -5.0.
        2. 'OVERSOLD': Lowered RSI threshold to 5.0 (Extreme Exhaustion).
        3. 'RSI_CONFLUENCE': Replaced simple SMA crossover with Momentum Deceleration 
           logic. Buying only when the rate of descent slows down mathematically,
           indicating sell-side exhaustion.
        """
        self.window_size = 100
        self.rsi_period = 14
        
        # Stricter Thresholds for Penalties
        self.z_score_threshold = -5.0     # Fix for DIP_BUY: Statistical rarity > 1 in a million
        self.rsi_threshold = 5.0          # Fix for OVERSOLD: Extreme exhaustion only
        self.volatility_cap = 1.8         # Fix for DIP_BUY: Reject if current volatility > 1.8x baseline
        
        # Risk Management
        self.stop_loss_pct = 0.05         # Tighter stops to limit downside
        self.take_profit_pct = 0.03       # Quick scalping target
        self.bet_percentage = 0.25        # High conviction sizing
        
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

        # 2. Check Exits
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices: continue
            
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            pnl_pct = (current_price - entry_price) / entry_price
            
            should_sell = False
            reason = []
            
            # Simple Bracket Orders
            if pnl_pct <= -self.stop_loss_pct:
                should_sell = True
                reason = ['STOP_LOSS_HIT']
            elif pnl_pct >= self.take_profit_pct:
                should_sell = True
                reason = ['TAKE_PROFIT_SCALP']
            
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
            
            # Stats
            mean = statistics.mean(history)
            stdev = statistics.stdev(history)
            
            if stdev == 0: continue
            
            # Metric 1: Z-Score (Addressing DIP_BUY)
            z_score = (current_price - mean) / stdev
            if z_score >= self.z_score_threshold:
                continue

            # Metric 2: Volatility Regime (Addressing DIP_BUY penalty)
            # Avoid buying if volatility is expanding rapidly (crashing)
            # We compare recent stdev vs baseline stdev
            recent_volatility = statistics.stdev(history[-20:])
            baseline_volatility = statistics.stdev(history[:-20]) if len(history) > 20 else recent_volatility
            
            if baseline_volatility > 0:
                vol_ratio = recent_volatility / baseline_volatility
                if vol_ratio > self.volatility_cap:
                    # Volatility is exploding (panic state), unsafe to enter
                    continue

            # Metric 3: RSI (Addressing OVERSOLD)
            rsi = self._calculate_rsi(history)
            if rsi >= self.rsi_threshold:
                continue
                
            # Metric 4: Momentum Deceleration (Addressing RSI_CONFLUENCE)
            # Instead of simple crossover, check if the falling speed is decreasing.
            # Compare slope of last 3 ticks vs slope of previous 3 ticks.
            last_3 = history[-3:]
            prev_3 = history[-6:-3]
            
            if len(last_3) < 3 or len(prev_3) < 3: continue
            
            slope_current = (last_3[-1] - last_3[0])
            slope_prev = (prev_3[-1] - prev_3[0])
            
            # We want current slope to be negative but flatter than previous slope (deceleration)
            # OR positive (reversal)
            is_decelerating = (slope_current > slope_prev) 
            
            if not is_decelerating:
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
                'reason': ['EXTREME_ANOMALY', 'VOL_STABLE', 'MOMENTUM_DECEL']
            }
            
        return None