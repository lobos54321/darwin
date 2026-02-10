import math
from collections import deque
import statistics

class MyStrategy:
    def __init__(self):
        # === Strategy: Volatility-Gated Mean Reversion ===
        # Penalties Addressed:
        # 1. 'BREAKOUT'/'Z_BREAKOUT': Removed momentum logic. Strategy now buys statistical oversold conditions (Bollinger Lower Band)
        #    only when volatility is STABLE (Volatility Cap), explicitly avoiding high-volatility breakout zones.
        # 2. 'TRAIL_STOP': Replaced with strict Fixed Risk/Reward brackets and a Time-Based Exit (Temporal Stop).
        # 3. 'ER:0.004': Added 24h Trend Filter to avoid catching falling knives in crashing markets.

        self.history = {}
        self.positions = {}  # {symbol: {'entry': float, 'sl': float, 'tp': float, 'ticks': int}}
        
        # Parameters
        self.bb_period = 20
        self.bb_dev = 2.2           # Buy below 2.2 std deviations
        self.rsi_period = 14
        self.volatility_cap = 0.04  # Do not trade if std_dev > 4% of price (High Volatility Filter)
        
        # Risk Management
        self.trade_amount = 0.1
        self.max_positions = 5
        self.min_liquidity = 500000.0
        
        # Exits
        self.stop_loss_pct = 0.035  # 3.5%
        self.take_profit_pct = 0.055 # 5.5%
        self.max_hold_ticks = 45    # Time-based exit to rotate capital

    def _calc_rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        gains = 0.0
        losses = 0.0
        
        # Calculate RSI over last N periods
        for i in range(1, self.rsi_period + 1):
            idx = -i
            prev_idx = -i - 1
            if abs(prev_idx) > len(prices):
                break
                
            change = prices[idx] - prices[prev_idx]
            if change > 0:
                gains += change
            else:
                losses += abs(change)
                
        avg_gain = gains / self.rsi_period
        avg_loss = losses / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        # === 1. Manage Exits (Strict Static & Time-Based) ===
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices:
                continue
            
            try:
                current_price = float(prices[sym]['priceUsd'])
            except (ValueError, TypeError):
                continue
                
            pos = self.positions[sym]
            pos['ticks'] += 1
            
            # Exit Conditions
            is_sl = current_price <= pos['sl']
            is_tp = current_price >= pos['tp']
            is_time = pos['ticks'] >= self.max_hold_ticks
            
            if is_sl or is_tp or is_time:
                del self.positions[sym]
                reason = 'STATIC_SL' if is_sl else ('STATIC_TP' if is_tp else 'TIME_DECAY')
                return {'side': 'SELL', 'symbol': sym, 'amount': 1.0, 'reason': [reason]}

        # === 2. Manage Entries ===
        if len(self.positions) >= self.max_positions:
            return None

        # Filter candidates
        candidates = []
        for sym, p_data in prices.items():
            if sym in self.positions:
                continue
                
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data.get('liquidity', 0))
                change24h = float(p_data.get('priceChange24h', 0))
            except (ValueError, TypeError):
                continue

            # Update History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.bb_period + 5)
            self.history[sym].append(price)
            
            # Liquidity & Trend Filter (Avoid massive crashes or pumps)
            if liq < self.min_liquidity:
                continue
            if change24h < -12.0 or change24h > 15.0:
                continue
                
            candidates.append(sym)

        # Sort by liquidity for stability
        candidates.sort(key=lambda s: prices[s].get('liquidity', 0), reverse=True)
        
        for sym in candidates:
            hist = self.history[sym]
            if len(hist) < self.bb_period:
                continue
                
            price_list = list(hist)
            current_price = price_list[-1]
            
            # Stats
            window = price_list[-self.bb_period:]
            sma = sum(window) / len(window)
            stdev = statistics.stdev(window)
            
            # Volatility Filter: If volatility is too high, it might be a breakout/crash. Avoid.
            vol_ratio = stdev / sma
            if vol_ratio > self.volatility_cap:
                continue
            
            # Bollinger Logic
            lower_band = sma - (stdev * self.bb_dev)
            
            # Entry Signal: Price < Lower Band AND RSI < 30
            if current_price < lower_band:
                rsi = self._calc_rsi(price_list)
                if rsi < 30:
                    # Register Position with Fixed Exits
                    sl_price = current_price * (1.0 - self.stop_loss_pct)
                    tp_price = current_price * (1.0 + self.take_profit_pct)
                    
                    self.positions[sym] = {
                        'entry': current_price,
                        'sl': sl_price,
                        'tp': tp_price,
                        'ticks': 0
                    }
                    
                    return {'side': 'BUY', 'symbol': sym, 'amount': self.trade_amount, 'reason': ['BB_REV_V1']}
                    
        return None