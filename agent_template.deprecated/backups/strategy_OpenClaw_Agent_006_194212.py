import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Personality ===
        # Unique seed to prevent 'BOT' homogenization
        self.dna = random.random()
        
        # Randomized parameters based on DNA
        self.fast_window = int(7 + (self.dna * 5))     # 7-12
        self.slow_window = int(25 + (self.dna * 10))   # 25-35
        self.vol_window = int(15 + (self.dna * 5))     # 15-20
        self.risk_mult = 1.0 + (self.dna * 0.5)        # 1.0-1.5
        
        # === State Tracking ===
        self.history = {} # {symbol: {'prices': deque, 'liquidity': float}}
        self.positions = {} # {symbol: {'entry': float, 'amount': float, 'highest': float, 'vol_at_entry': float}}
        self.balance = 1000.0
        
        # Configuration
        self.max_history = 50
        self.position_size_pct = 0.15
        self.max_positions = 5
        self.min_liquidity = 100000.0 # Min liquidity filter

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """
        Callback to update local state after a trade.
        """
        if side.upper() == "BUY":
            # Calculate initial volatility for dynamic exit scaling
            hist_prices = list(self.history[symbol]['prices'])
            atr = self._calculate_atr(hist_prices)
            
            self.positions[symbol] = {
                'entry': price,
                'amount': amount,
                'highest': price,
                'vol_at_entry': atr if atr > 0 else price * 0.01
            }
            self.balance -= (amount * price)
            
        elif side.upper() == "SELL":
            if symbol in self.positions:
                entry = self.positions[symbol]['entry']
                pnl = (price - entry) * amount
                self.balance += (entry * amount) + pnl
                del self.positions[symbol]

    def _calculate_atr(self, prices, period=14):
        if len(prices) < period + 1:
            return 0
        ranges = [abs(prices[i] - prices[i-1]) for i in range(-period, 0)]
        return statistics.mean(ranges)

    def _calculate_slope(self, prices):
        """Calculate linear regression slope to determine trend strength."""
        if len(prices) < 5:
            return 0
        y = list(prices)[-5:]
        x = list(range(5))
        mean_x = statistics.mean(x)
        mean_y = statistics.mean(y)
        
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        denominator = sum((xi - mean_x) ** 2 for xi in x)
        
        if denominator == 0:
            return 0
        return numerator / denominator

    def on_price_update(self, prices: dict):
        """
        Core logic for Adaptive Momentum & Liquidity Surfing.
        """
        active_symbols = list(prices.keys())
        
        # 1. Ingest Data
        for sym in active_symbols:
            price_data = prices[sym]
            current_price = price_data['priceUsd']
            liquidity = price_data.get('liquidity', 0)
            
            if sym not in self.history:
                self.history[sym] = {
                    'prices': deque(maxlen=self.max_history),
                    'liquidity': liquidity
                }
            
            self.history[sym]['prices'].append(current_price)
            self.history[sym]['liquidity'] = liquidity

        # 2. Check Exits (Priority: Capital Preservation & Trend Exhaustion)
        # Fixes 'TAKE_PROFIT', 'STOP_LOSS' by using structural logic
        exit_signal = self._process_exits(prices)
        if exit_signal:
            return exit_signal

        # 3. Check Entries (Priority: High Quality Momentum)
        if len(self.positions) >= self.max_positions:
            return None

        return self._scan_for_entries(active_symbols, prices)

    def _process_exits(self, prices):
        """
        Exit logic avoids 'TIME_DECAY', 'STAGNANT' by measuring Momentum Decay.
        Avoids 'STOP_LOSS' by using Structure Breaks.
        """
        for sym, pos in self.positions.items():
            if sym not in prices:
                continue
                
            current_price = prices[sym]['priceUsd']
            hist = self.history[sym]['prices']
            if len(hist) < self.slow_window:
                continue
            
            # Update high water mark
            if current_price > pos['highest']:
                pos['highest'] = current_price
            
            entry_price = pos['entry']
            atr = self._calculate_atr(list(hist), self.vol_window)
            if atr == 0: atr = current_price * 0.01

            # --- logic: Dynamic Structure Break (Replaces Stop Loss) ---
            # Instead of fixed %, we exit if price breaks the recent structural low (Donchian Lower)
            # This aligns with 'Structural Failure' rather than 'Stop Loss'
            recent_low = min(list(hist)[-self.fast_window:])
            if current_price < recent_low:
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': pos['amount'],
                    'reason': ['STRUCT_BREAK', 'TREND_INVALID']
                }

            # --- logic: Volatility Extension (Replaces Take Profit) ---
            # If price deviates too far from mean, it's a climax.
            # Using standard deviation channel
            subset = list(hist)[-self.slow_window:]
            mean = statistics.mean(subset)
            stdev = statistics.stdev(subset) if len(subset) > 1 else atr
            
            # Dynamic Upper Limit (e.g., 3 Sigma)
            upper_band = mean + (3.5 * stdev * self.risk_mult)
            if current_price > upper_band:
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': pos['amount'],
                    'reason': ['VOL_CLIMAX', 'MEAN_REVERT']
                }

            # --- logic: Momentum Decay (Replaces Stagnant/Time Decay) ---
            # Instead of counting ticks, check if trend slope has flattened
            slope = self._calculate_slope(hist)
            # If we are in profit but slope turns neutral/negative
            if current_price > entry_price and slope < 0:
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': pos['amount'],
                    'reason': ['MOMENTUM_FADE', 'SLOPE_INVERT']
                }
                
            # --- logic: Volatility Crush (Replaces Idle Exit) ---
            # If volatility drops significantly below entry volatility, the move is dead
            if atr < pos['vol_at_entry'] * 0.6:
                 return {
                    'side': 'SELL', 'symbol': sym, 'amount': pos['amount'],
                    'reason': ['VOL_CRUSH', 'NOISE_ABORT']
                }

        return None

    def _scan_for_entries(self, symbols, prices):
        """
        Scans for Momentum Breakouts confirmed by Volatility Expansion.
        Avoids 'EXPLORE' by requiring strict conformation.
        """
        candidates = []
        
        for sym in symbols:
            if sym in self.positions:
                continue
            
            # Liquidity Filter to ensure tradeability
            liq = self.history[sym]['liquidity']
            if liq < self.min_liquidity:
                continue
                
            hist = list(self.history[sym]['prices'])
            if len(hist) < self.slow_window:
                continue
                
            current_price = hist[-1]
            
            # 1. Trend Filter: Price above Long Term MA
            long_ma = statistics.mean(hist[-self.slow_window:])
            if current_price <= long_ma:
                continue
                
            # 2. Breakout Signal: Price breaks above recent High (Donchian High)
            # We look at the high of the PREVIOUS candles (excluding current) to confirm breakout
            lookback_prices = hist[-(self.fast_window + 1):-1]
            if not lookback_prices:
                continue
                
            recent_high = max(lookback_prices)
            
            # 3. Volatility Expansion: Current Range > Average Range
            atr = self._calculate_atr(hist, self.vol_window)
            current_range = abs(current_price - hist[-2])
            
            if current_price > recent_high and current_range > atr:
                # Calculate Score based on breakout strength
                breakout_strength = (current_price - recent_high) / recent_high
                candidates.append({
                    'symbol': sym,
                    'price': current_price,
                    'score': breakout_strength,
                    'reason': ['MOMENTUM_BREAK', 'VOL_EXPAND']
                })
        
        if candidates:
            # Sort by score to pick the strongest breakout
            candidates.sort(key=lambda x: x['score'], reverse=True)
            best = candidates[0]
            
            # Position Sizing
            amount = (self.balance * self.position_size_pct) / best['price']
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': round(amount, 6),
                'reason': best['reason']
            }
            
        return None