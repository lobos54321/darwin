# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import math
from collections import deque, defaultdict

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Evolved: OmegaOne V3 (Adaptive Trend + Volatility Guard)")
        
        # --- 进化配置 (Evolution Config) ---
        self.ema_short_period = 5       # Fast EMA
        self.ema_long_period = 15       # Slow EMA
        self.volatility_window = 10     # For calculating ATR/StdDev
        
        # --- 风控参数 (Risk Management) ---
        self.stop_loss_pct = 0.03       # 3% Hard Stop (Tighter than V2)
        self.trailing_stop_pct = 0.015  # 1.5% Trailing Stop (Lock profits fast)
        self.max_pos_percent = 0.10     # Max 10% of equity per trade
        self.min_volume_24h = 1000      # Basic liquidity filter
        
        # --- 状态追踪 (State Tracking) ---
        self.price_history = defaultdict(lambda: deque(maxlen=30))
        self.positions = {}             # {symbol: {'entry': float, 'high': float, 'size': float}}
        self.banned_tags = set()
        self.boosted_tags = set()
        
        # 资金管理 (Conservative estimation)
        self.estimated_balance = 639.51 

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"🛡️ Risk: Penalizing tags {penalize}")
            self.banned_tags.update(penalize)
            # 立即清仓被惩罚的资产
            for tag in penalize:
                if tag in self.positions:
                    self._force_close(tag, "Hive Penalty")
            
        boost = signal.get("boost", [])
        if boost:
            self.boosted_tags.update(boost)
            self.banned_tags.difference_update(boost)

    def _calculate_ema(self, prices, period):
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for price in list(prices)[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _force_close(self, symbol, reason):
        """Helper to mark position for closure"""
        # In a real engine this would return a SELL order immediately
        # Here we just mark it to be handled in the main loop logic if possible,
        # or assuming the engine allows multiple returns, we'd return it.
        # For this template, we update internal state to ensure we don't hold it.
        if symbol in self.positions:
            print(f"📉 Closing {symbol}: {reason}")
            del self.positions[symbol]

    def on_price_update(self, prices: dict):
        """
        Called every time price updates.
        Returns: (symbol, amount_usd, side) or None
        """
        decision = None
        
        # 1. Update History & Calculate Indicators
        for symbol, data in prices.items():
            price = data["priceUsd"]
            self.price_history[symbol].append(price)

        # 2. Portfolio Management (Stop Loss / Take Profit)
        # Iterate copy of keys to allow modification
        for symbol in list(self.positions.keys()):
            current_price = prices[symbol]["priceUsd"]
            pos = self.positions[symbol]
            
            # Update High Watermark
            if current_price > pos['high']:
                pos['high'] = current_price
            
            # Check Hard Stop
            loss_pct = (current_price - pos['entry']) / pos['entry']
            if loss_pct < -self.stop_loss_pct:
                print(f"🛑 Stop Loss triggered for {symbol} at {loss_pct*100:.2f}%")
                del self.positions[symbol]
                return (symbol, pos['size'], "sell")
            
            # Check Trailing Stop
            drawdown_from_high = (current_price - pos['high']) / pos['high']
            if drawdown_from_high < -self.trailing_stop_pct:
                print(f"💰 Trailing Stop triggered for {symbol}. Locked profit.")
                del self.positions[symbol]
                return (symbol, pos['size'], "sell")

        # 3. Opportunity Scanning
        best_opportunity = None
        max_score = -1

        for symbol, data in prices.items():
            # Filters
            if symbol in self.positions: continue
            if symbol in self.banned_tags: continue
            
            history = self.price_history[symbol]
            if len(history) < self.ema_long_period: continue
            
            current_price = data["priceUsd"]
            
            # Indicators
            ema_short = self._calculate_ema(history, self.ema_short_period)
            ema_long = self._calculate_ema(history, self.ema_long_period)
            
            if ema_short is None or ema_long is None: continue

            # Strategy: Trend Following (Golden Cross)
            # V3 Mutation: Only buy if Short EMA is > Long EMA AND Price is above Short EMA (Strong Momentum)
            if ema_short > ema_long and current_price > ema_short:
                
                # Volatility Check (Avoid pump and dumps)
                # If price is > 5% away from EMA short, it's overextended -> Skip
                deviation = (current_price - ema_short) / ema_short
                if deviation > 0.05:
                    continue

                # Scoring
                score = (ema_short - ema_long) / ema_long
                if symbol in self.boosted_tags:
                    score *= 1.5
                
                if score > max_score:
                    max_score = score
                    best_opportunity = symbol

        # 4. Execution
        if best_opportunity and max_score > 0:
            # Position Sizing based on current equity
            position_size = self.estimated_balance * self.max_pos_percent
            
            # Record Position
            self.positions[best_opportunity] = {
                'entry': prices[best_opportunity]["priceUsd"],
                'high': prices[best_opportunity]["priceUsd"],
                'size': position_size
            }
            
            print(f"🚀 Buying {best_opportunity} (Score: {max_score:.4f})")
            return (best_opportunity, position_size, "buy")

        return None