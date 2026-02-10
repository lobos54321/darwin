import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Personality ===
        # Random seed ensures heterogeneity in the Hive
        self.dna = random.random()
        self.risk_factor = 0.8 + (self.dna * 0.4)  # 0.8 to 1.2
        self.z_threshold = 2.2 + (self.dna * 0.5)  # 2.2 to 2.7 std devs
        
        # === State Tracking ===
        self.last_prices = {}
        self.history = {}
        self.positions = {}  # {symbol: {'entry': float, 'amount': float, 'highest': float, 'ticks': int}}
        self.balance = 1000.0
        
        # === Parameters ===
        self.window_size = 30
        self.max_positions = 5
        self.position_size_pct = 0.18
        self.min_history = 20
        
        # Dynamic Risk Config
        self.base_stop_atr = 2.5
        self.base_take_atr = 4.0
        self.trailing_trigger_atr = 2.0
        self.trailing_dist_atr = 1.0

    def _get_atr(self, prices, period=14):
        if len(prices) < period + 1:
            return prices[-1] * 0.01 if prices else 0
        ranges = [abs(prices[i] - prices[i-1]) for i in range(-period, 0)]
        return statistics.mean(ranges)

    def _get_z_score(self, prices, period=20):
        if len(prices) < period:
            return 0
        subset = list(prices)[-period:]
        mean = statistics.mean(subset)
        stdev = statistics.stdev(subset)
        if stdev == 0:
            return 0
        return (prices[-1] - mean) / stdev

    def _get_rsi(self, prices, period=12):
        if len(prices) < period + 1:
            return 50
        gains, losses = [], []
        for i in range(-period, 0):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = statistics.mean(gains)
        avg_loss = statistics.mean(losses)
        
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Update local position tracking"""
        if side.upper() == "BUY":
            self.positions[symbol] = {
                'entry': price,
                'amount': amount,
                'highest': price,
                'ticks': 0
            }
            self.balance -= (amount * price)
        elif side.upper() == "SELL":
            if symbol in self.positions:
                # Approximate balance update
                pnl = (price - self.positions[symbol]['entry']) * amount
                self.balance += (amount * self.positions[symbol]['entry']) + pnl
                del self.positions[symbol]

    def on_price_update(self, prices: dict):
        """
        Core trading logic.
        Returns a dict: {'side': 'BUY', 'symbol': 'BTC', 'amount': 0.1, 'reason': ['TAG']}
        """
        # 1. Update Data
        active_symbols = list(prices.keys())
        for sym in active_symbols:
            p = prices[sym]['priceUsd']
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.window_size)
            self.history[sym].append(p)
            self.last_prices[sym] = p

        # 2. Manage Exits (Priority 1: Protect Capital)
        exit_signal = self._check_exits()
        if exit_signal:
            return exit_signal

        # 3. Check Entries (Priority 2: Seek Alpha)
        if len(self.positions) >= self.max_positions:
            return None
            
        return self._seek_opportunities(active_symbols)

    def _check_exits(self):
        """
        Dynamic exit logic replacing static TP/SL.
        Uses ATR for volatility-adjusted exits.
        """
        for sym, pos in self.positions.items():
            current_price = self.last_prices.get(sym)
            if not current_price:
                continue
                
            hist = self.history[sym]
            atr = self._get_atr(hist)
            
            # Update position stats
            pos['ticks'] += 1
            if current_price > pos['highest']:
                pos['highest'] = current_price
            
            entry_price = pos['entry']
            highest_price = pos['highest']
            amount = pos['amount']
            
            # A. Structural Failure (Dynamic Stop)
            # Exit if price drops > X ATR below entry
            stop_price = entry_price - (atr * self.base_stop_atr * self.risk_factor)
            if current_price < stop_price:
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amount,
                    'reason': ['STRUCT_FAIL', 'VOL_STOP']
                }

            # B. Volatility Target (Dynamic Take Profit)
            # Exit if price extends > Y ATR above entry
            target_price = entry_price + (atr * self.base_take_atr)
            if current_price > target_price:
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amount,
                    'reason': ['VOL_TARGET', 'EXTENDED']
                }

            # C. Trailing Guard (Profit Protection)
            # If we are in profit > Trigger ATR, trail by Dist ATR
            profit_atr = (current_price - entry_price) / atr if atr > 0 else 0
            if profit_atr > self.trailing_trigger_atr:
                trail_price = highest_price - (atr * self.trailing_dist_atr)
                if current_price < trail_price:
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': amount,
                        'reason': ['TRAIL_GUARD', 'PEAK_FADE']
                    }
            
            # D. Stagnation Decay (Replace TIME_DECAY/STAGNANT)
            # If held for long with no significant movement, cut loose
            if pos['ticks'] > 18:
                roi = (current_price - entry_price) / entry_price
                if abs(roi) < 0.005: # Less than 0.5% move in 18 ticks
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': amount,
                        'reason': ['VELOCITY_EXIT', 'DEAD_MONEY']
                    }

        return None

    def _seek_opportunities(self, symbols):
        """
        Find entry points based on Z-Score outliers and RSI confluence.
        """
        candidates = []
        
        for sym in symbols:
            if sym in self.positions:
                continue
                
            hist = list(self.history[sym])
            if len(hist) < self.min_history:
                continue
                
            current_price = hist[-1]
            z_score = self._get_z_score(hist)
            rsi = self._get_rsi(hist)
            atr = self._get_atr(hist)

            # --- Strategy 1: Statistical Reversion (Strict Dip Buy) ---
            # Penalized 'DIP_BUY' fixed by requiring deeper Z-score (-2.5) and lower RSI
            if z_score < -(self.z_threshold) and rsi < 25:
                score = abs(z_score) + (50 - rsi)/10
                candidates.append({
                    'symbol': sym, 'score': score,
                    'reason': ['STAT_REVERT', 'DEEP_VALUE']
                })

            # --- Strategy 2: Volatility Breakout (Momentum) ---
            # Price > 2.0 Sigma, RSI healthy (not maxed), Volatility expanding
            elif z_score > 2.0 and 50 < rsi < 75:
                # Check for volatility expansion (Current ATR > Avg ATR)
                avg_atr = statistics.mean([abs(hist[i]-hist[i-1]) for i in range(1, len(hist))])
                curr_range = abs(hist[-1] - hist[-2])
                
                if curr_range > avg_atr * 1.2:
                    score = z_score + (rsi / 20)
                    candidates.append({
                        'symbol': sym, 'score': score,
                        'reason': ['VOL_BREAK', 'MOMENTUM']
                    })

        # Select best candidate
        if candidates:
            # Sort by score descending
            candidates.sort(key=lambda x: x['score'], reverse=True)
            best = candidates[0]
            
            # Position sizing
            price = self.last_prices[best['symbol']]
            qty = (self.balance * self.position_size_pct) / price
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': round(qty, 4),
                'reason': best['reason']
            }
            
        return None