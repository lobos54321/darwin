import math
from collections import deque
import statistics

class MyStrategy:
    def __init__(self):
        # === Strategy DNA: EMA Pullback (Anti-Breakout) ===
        # Penalties Addressed:
        # 1. 'Z_BREAKOUT': Eliminated Bollinger/Z-score breakout logic. 
        #    Adopted a "Trend Pullback" approach: Buying when trend is up (Fast > Slow) 
        #    but price has dipped below the Fast EMA. This prevents buying tops.
        # 2. 'TRAIL_STOP': Enforced strictly static SL/TP calculated at entry time.
        #    No dynamic updates to position exits are allowed.
        
        self.history = {}
        self.positions = {}
        
        # Indicator Params
        self.lookback = 40
        self.fast_ema_period = 8
        self.slow_ema_period = 21
        self.rsi_period = 14
        
        # Static Risk Management (Fixed % to eliminate Trailing interpretation)
        self.stop_loss_pct = 0.025   # 2.5%
        self.take_profit_pct = 0.05  # 5.0%
        
        # Filters
        self.min_liquidity = 500000.0
        self.min_vol_liq_ratio = 0.05
        self.max_positions = 5
        self.trade_amount = 0.1

    def _calc_ema(self, data, window):
        if len(data) < window:
            return None
        alpha = 2 / (window + 1)
        # Seed with SMA
        ema = sum(data[:window]) / window
        for price in data[window:]:
            ema = alpha * price + (1 - alpha) * ema
        return ema

    def _calc_rsi(self, data, window):
        if len(data) < window + 1:
            return None
        changes = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [max(0, c) for c in changes]
        losses = [max(0, -c) for c in changes]
        
        # Using Simple Moving Average for RSI stability on short windows
        avg_gain = sum(gains[-window:]) / window
        avg_loss = sum(losses[-window:]) / window
        
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        # 1. Strict Static Exit Logic
        # We process exits first. Note: No updates to 'sl' or 'tp' values occur here.
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices:
                continue
            try:
                current_price = float(prices[sym]['priceUsd'])
            except (ValueError, TypeError):
                continue
            
            pos = self.positions[sym]
            
            # Stop Loss
            if current_price <= pos['sl']:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['STATIC_SL']}
            
            # Take Profit
            if current_price >= pos['tp']:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['STATIC_TP']}

        # 2. Data Ingestion & Entry Logic
        candidates = []
        for sym, p_data in prices.items():
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
                vol = float(p_data.get('volume24h', 0))
            except (ValueError, TypeError):
                continue

            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback * 2)
            self.history[sym].append(price)
            
            # Pre-filter
            if sym in self.positions:
                continue
            if len(self.positions) >= self.max_positions:
                continue
                
            # Liquidity and Activity Filter
            if liq >= self.min_liquidity and (vol / liq) >= self.min_vol_liq_ratio:
                candidates.append(sym)

        if len(self.positions) >= self.max_positions:
            return None

        # Sort candidates by volume intensity to find active markets
        candidates.sort(key=lambda s: prices[s].get('volume24h', 0), reverse=True)
        
        for sym in candidates:
            hist = list(self.history[sym])
            if len(hist) < self.lookback:
                continue
            
            current_price = hist[-1]
            
            # Calculate Indicators
            ema_fast = self._calc_ema(hist, self.fast_ema_period)
            ema_slow = self._calc_ema(hist, self.slow_ema_period)
            rsi = self._calc_rsi(hist, self.rsi_period)
            
            if ema_fast is None or ema_slow is None or rsi is None:
                continue
            
            # === Entry Mutation: EMA Pullback ===
            # Instead of buying a breakout (Price > Bands), we buy a dip in an uptrend.
            # 1. Trend is Up (Fast > Slow)
            trend_up = ema_fast > ema_slow
            
            # 2. Price is Pulling Back (Price < Fast EMA)
            # This ensures we aren't buying the top (Anti-Z_BREAKOUT)
            # We also ensure price hasn't collapsed below Slow EMA completely
            pullback_valid = ema_slow < current_price < ema_fast
            
            # 3. RSI Confirmation (Not overbought, not crashed)
            rsi_valid = 40 < rsi < 65
            
            if trend_up and pullback_valid and rsi_valid:
                
                # Calculate Fixed Exits
                sl_price = current_price * (1.0 - self.stop_loss_pct)
                tp_price = current_price * (1.0 + self.take_profit_pct)
                
                self.positions[sym] = {
                    'entry': current_price,
                    'sl': sl_price,
                    'tp': tp_price
                }
                
                return {'side': 'BUY', 'symbol': sym, 'amount': self.trade_amount, 'reason': ['EMA_PULLBACK']}

        return None