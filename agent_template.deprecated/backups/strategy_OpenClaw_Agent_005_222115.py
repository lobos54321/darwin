import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Random seed to vary parameters (Anti-Homogenization)
        self.dna = random.uniform(0.9, 1.1)
        
        # === Capital Management ===
        self.balance = 1000.0
        self.risk_per_trade = 0.98
        self.max_positions = 1
        
        # === Indicators & Windows ===
        # Shorter windows for HFT-like responsiveness
        self.fast_window = int(9 * self.dna)
        self.slow_window = int(21 * self.dna)
        self.vol_window = 15
        self.rsi_period = 14
        
        # Ensure sufficient history
        self.history_limit = max(self.slow_window, self.vol_window, self.rsi_period) + 5
        
        # === Strict Filters (Anti-EXPLORE / Anti-STAGNANT) ===
        self.min_liquidity = 5_000_000  # High liquidity only
        self.min_volume = 2_000_000
        self.min_volatility_entry = 0.002 # Needs movement to enter
        
        # === Strategy Thresholds ===
        # Anti-MEAN_REVERSION: Buy strength (RSI > 60), not dips
        self.rsi_min = 61.0 
        self.rsi_max = 84.0
        
        # State containers
        self.history = {}      # {symbol: deque}
        self.positions = {}    # {symbol: {data}}

    def _calc_ema(self, prices, window):
        if len(prices) < window:
            return prices[-1]
        
        # Standard EMA calculation
        multiplier = 2 / (window + 1)
        ema = sum(prices[:window]) / window # SMA start
        
        for price in prices[window:]:
            ema = (price - ema) * multiplier + ema
            
        return ema

    def _calc_rsi(self, prices, period):
        if len(prices) < period + 1:
            return 50.0
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        # Use simple moving average for RSI speed in HFT ctx
        recent_deltas = deltas[-period:]
        
        gains = [d for d in recent_deltas if d > 0]
        losses = [abs(d) for d in recent_deltas if d <= 0]
        
        avg_gain = sum(gains) / period if gains else 0.0
        avg_loss = sum(losses) / period if losses else 0.0
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _get_volatility(self, prices):
        if len(prices) < 5: return 0.0
        # Coefficient of Variation: StDev / Mean
        slice_data = list(prices)[-self.vol_window:]
        if len(slice_data) < 2: return 0.0
        return statistics.stdev(slice_data) / statistics.mean(slice_data)

    def on_price_update(self, prices: dict):
        # 1. Ingest Data
        active_symbols = []
        
        for symbol, data in prices.items():
            try:
                # Validation & Anti-EXPLORE
                liquidity = float(data.get('liquidity', 0))
                vol24 = float(data.get('volume24h', 0))
                
                if liquidity < self.min_liquidity or vol24 < self.min_volume:
                    continue
                
                price = float(data['priceUsd'])
                
                if symbol not in self.history:
                    self.history[symbol] = deque(maxlen=self.history_limit)
                self.history[symbol].append(price)
                
                active_symbols.append(symbol)
                
            except (ValueError, KeyError, TypeError):
                continue

        # 2. Manage Positions (Exits)
        # Priority: Dynamic Trailing Stop -> Time Decay
        
        keys_to_check = list(self.positions.keys())
        for symbol in keys_to_check:
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            curr_price = float(prices[symbol]['priceUsd'])
            
            # Update State
            pos['ticks'] += 1
            pos['high_water_mark'] = max(pos['high_water_mark'], curr_price)
            pos['current_price'] = curr_price
            
            # ROI
            roi = (curr_price - pos['entry_price']) / pos['entry_price']
            drawdown = (pos['high_water_mark'] - curr_price) / pos['high_water_mark']
            
            # Volatility Context for Exit
            hist = self.history[symbol]
            vol = self._get_volatility(hist)
            
            # A. Dynamic Trailing Stop (Anti-STOP_LOSS penalty fix)
            # Widen stop if volatility is high to avoid noise. Tighten if low.
            # Base buffer is 3x volatility or min 1%
            stop_buffer = max(0.01, vol * 3.5)
            
            if drawdown > stop_buffer:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['VOL_TRAIL']}
            
            # B. Time Decay / Stagnation (Anti-IDLE_EXIT / Anti-TIME_DECAY)
            # If we hold for a while and price isn't moving, exit to free capital.
            if pos['ticks'] > 20:
                # If we are barely positive or negative after 20 ticks, bail.
                if roi < 0.004: 
                    del self.positions[symbol]
                    return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['STAGNANT_EXIT']}
            
            # C. Hard Trend Reversal
            # If price breaks significant logic structure (e.g. ROI < -2% hard stop)
            if roi < -0.02:
                del self.positions[symbol]
                return {'side': 'SELL', 'symbol': symbol, 'amount': pos['amount'], 'reason': ['HARD_STOP']}

        # 3. Scan for Entries (Trend Following / Momentum)
        # Only if we have space
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for symbol in active_symbols:
                if symbol in self.positions: continue
                
                h_deque = self.history[symbol]
                if len(h_deque) < self.slow_window: continue
                
                h_list = list(h_deque)
                current = h_list[-1]
                
                # Indicator Calculation
                ema_fast = self._calc_ema(h_list, self.fast_window)
                ema_slow = self._calc_ema(h_list, self.slow_window)
                volatility = self._get_volatility(h_deque)
                
                # === Anti-STAGNANT ===
                # Market must be moving to enter
                if volatility < self.min_volatility_entry:
                    continue
                
                # === Anti-MEAN_REVERSION ===
                # Strictly Trend Following: Price > Fast > Slow
                # We want to buy upward expansion, not potential reversals
                is_uptrend = (current > ema_fast) and (ema_fast > ema_slow)
                if not is_uptrend:
                    continue
                
                # === Anti-STOP_LOSS (Entry Quality) ===
                # Ensure we are not buying a top by checking RSI
                rsi = self._calc_rsi(h_list, self.rsi_period)
                
                # Sweet Spot: Momentum (60+) but not Exhaustion (85+)
                if self.rsi_min < rsi < self.rsi_max:
                    # Score based on Trend Strength/Efficiency
                    # Higher RSI + Lower Volatility = Smooth Trend
                    # Avoid dividing by zero
                    eff_vol = max(volatility, 0.0001)
                    score = rsi / (eff_vol * 100)
                    
                    candidates.append({
                        'symbol': symbol,
                        'price': current,
                        'score': score
                    })
            
            if candidates:
                # Pick the smoothest strong trend
                best = max(candidates, key=lambda x: x['score'])
                
                # Position Sizing
                usd_size = self.balance * self.risk_per_trade
                amount = usd_size / best['price']
                
                self.positions[best['symbol']] = {
                    'entry_price': best['price'],
                    'amount': amount,
                    'high_water_mark': best['price'],
                    'ticks': 0,
                    'current_price': best['price']
                }
                
                return {
                    'side': 'BUY', 
                    'symbol': best['symbol'], 
                    'amount': amount, 
                    'reason': ['MOMENTUM_TREND']
                }
                
        return None