import math
from collections import deque
import statistics

class MyStrategy:
    def __init__(self):
        # === Strategy DNA: SMA Mean Reversion ===
        # Penalties Addressed:
        # 1. 'BREAKOUT' / 'Z_BREAKOUT': 
        #    Switched from buying momentum/breakouts to buying deviations BELOW the mean (Mean Reversion).
        #    We buy when price < SMA by a specific % threshold, effectively catching dips.
        # 2. 'TRAIL_STOP': 
        #    Exits are strictly static (calculated at entry) and never updated.
        
        self.history = {}
        self.positions = {}
        
        # Parameters
        self.sma_period = 20
        self.rsi_period = 14
        self.trade_amount = 0.1
        self.max_positions = 5
        
        # Risk Management (Fixed Entry-Based Brackets)
        self.stop_loss_pct = 0.04   # 4%
        self.take_profit_pct = 0.06 # 6%
        
        # Filters
        self.min_liquidity = 250000.0

    def _calc_rsi(self, data):
        if len(data) < self.rsi_period + 1:
            return 50.0
        
        # Calculate price changes
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d <= 0]
        
        # Simple average (SMMA approximation for short windows)
        avg_gain = sum(gains[-self.rsi_period:]) / self.rsi_period if gains else 0.0
        avg_loss = sum(losses[-self.rsi_period:]) / self.rsi_period if losses else 0.0
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        # === 1. Strict Static Exits ===
        # Check active positions for SL/TP hits first
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices:
                continue
            
            try:
                current_price = float(prices[sym]['priceUsd'])
            except (ValueError, TypeError):
                continue
            
            pos = self.positions[sym]
            
            # Stop Loss (Static)
            if current_price <= pos['sl']:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['STATIC_SL']}
            
            # Take Profit (Static)
            if current_price >= pos['tp']:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': ['STATIC_TP']}

        # === 2. Data Ingestion & Logic ===
        if len(self.positions) >= self.max_positions:
            return None

        candidates = []
        for sym, p_data in prices.items():
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
            except (ValueError, TypeError):
                continue

            # Maintain History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.sma_period + 5)
            self.history[sym].append(price)
            
            # Pre-filter
            if sym in self.positions:
                continue
            if liq < self.min_liquidity:
                continue
                
            candidates.append(sym)

        # Sort candidates by liquidity to ensure we trade stable pairs
        candidates.sort(key=lambda s: prices[s].get('liquidity', 0), reverse=True)
        
        for sym in candidates:
            hist = list(self.history[sym])
            if len(hist) < self.sma_period:
                continue
            
            current_price = hist[-1]
            
            # Indicators
            sma = sum(hist[-self.sma_period:]) / self.sma_period
            rsi = self._calc_rsi(hist)
            
            # === Entry Logic: Mean Reversion Dip ===
            # Avoids BREAKOUT (buying high) by buying only when significantly below SMA.
            
            # 1. Price is Below Mean (Dip)
            # We look for price to be at least 2% below the 20-period SMA
            deviation = (sma - current_price) / sma
            is_dip = 0.02 < deviation < 0.10  # 2% to 10% drop (avoid catching falling knives > 10%)
            
            # 2. RSI Oversold
            # Ensure momentum is washed out
            is_oversold = rsi < 32
            
            if is_dip and is_oversold:
                # Define STATIC Exit Prices at moment of entry
                sl_price = current_price * (1.0 - self.stop_loss_pct)
                tp_price = current_price * (1.0 + self.take_profit_pct)
                
                self.positions[sym] = {
                    'entry': current_price,
                    'sl': sl_price,
                    'tp': tp_price
                }
                
                return {'side': 'BUY', 'symbol': sym, 'amount': self.trade_amount, 'reason': ['SMA_DIP_REV']}

        return None