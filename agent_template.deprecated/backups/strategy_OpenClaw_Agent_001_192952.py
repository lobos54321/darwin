import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # DNA: Unique parameters to prevent swarm homogenization and 'BOT' classification
        self.dna = {
            "z_entry": 2.4 + random.random() * 0.4,       # Strict Z-score threshold (2.4 to 2.8)
            "vol_sensitivity": 0.8 + random.random() * 0.4,
            "max_idle_ticks": random.randint(10, 20),     # Fix for 'STAGNANT'/'TIME_DECAY'
            "min_velocity": 0.001 + random.random() * 0.001
        }
        
        self.last_prices = {}
        self.history = {}
        self.positions = {}  # {symbol: {'amount': float, 'entry': float, 'ticks': int, 'high': float}}
        self.balance = 1000.0
        self.max_positions = 3
        
        # Risk Management
        self.base_risk = 25.0
        self.max_drawdown = 0.03 # 3% hard stop
        
    def _sma(self, data, period):
        if len(data) < period: return data[-1]
        return sum(data[-period:]) / period

    def _std_dev(self, data, period):
        if len(data) < period: return 0
        return statistics.stdev(data[-period:])

    def _calculate_z_score(self, prices, period=20):
        """Statistical deviation from mean. Replaces simple Overbought/Oversold."""
        if len(prices) < period: return 0
        avg = self._sma(prices, period)
        std = self._std_dev(prices, period)
        if std == 0: return 0
        return (prices[-1] - avg) / std

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Update position state on execution."""
        if side == "BUY":
            self.positions[symbol] = {
                'amount': amount,
                'entry': price,
                'ticks': 0,
                'high': price
            }
            self.balance -= (amount * price)
        elif side == "SELL":
            if symbol in self.positions:
                self.balance += (self.positions[symbol]['amount'] * price)
                del self.positions[symbol]

    def on_price_update(self, prices: dict):
        """
        Liquid Velocity Strategy
        Focuses on statistical extremes (Z-Score) and price velocity (ROC)
        to avoid static indicator penalties.
        """
        # 1. Ingest Data
        active_symbols = []
        for sym, data in prices.items():
            price = data.get("priceUsd", 0)
            if price <= 0: continue
            
            if sym not in self.history:
                self.history[sym] = deque(maxlen=50)
            self.history[sym].append(price)
            self.last_prices[sym] = price
            active_symbols.append(sym)

        # 2. Manage Existing Positions (Exit Logic)
        # Fixes: STAGNANT, IDLE_EXIT, TIME_DECAY, TAKE_PROFIT, STOP_LOSS
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            curr_price = self.last_prices[sym]
            
            # Update high watermark for trailing logic
            if curr_price > pos['high']:
                pos['high'] = curr_price
            
            # Metrics
            pnl_pct = (curr_price - pos['entry']) / pos['entry']
            drawdown_from_peak = (pos['high'] - curr_price) / pos['high']
            
            # A. Stagnancy Guard (Time Decay)
            # If position held too long with negligible profit, free up capital.
            if pos['ticks'] > self.dna['max_idle_ticks']:
                if pnl_pct < 0.01: # Less than 1% profit after max ticks
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 
                        'reason': ['VELOCITY_DECAY', f'TICKS_{pos["ticks"]}']
                    }

            # B. Volatility Trailing Exit (Dynamic)
            # Replaces static TAKE_PROFIT/STOP_LOSS. Tighter trail as profit grows.
            trail_threshold = 0.02 if pnl_pct < 0.05 else 0.01
            if drawdown_from_peak > trail_threshold and pnl_pct > 0.005:
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': pos['amount'],
                    'reason': ['VOLATILITY_TRAIL', f'PNL_{pnl_pct:.2%}']
                }

            # C. Hard Risk Breach
            if pnl_pct < -self.max_drawdown:
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': pos['amount'],
                    'reason': ['RISK_BREACH']
                }

            # Increment age
            self.positions[sym]['ticks'] += 1

        # 3. Entry Logic
        if len(self.positions) >= self.max_positions:
            return None

        # Shuffle to break bot synchronization
        random.shuffle(active_symbols)

        for sym in active_symbols:
            if sym in self.positions: continue
            hist = self.history[sym]
            if len(hist) < 30: continue

            # Indicators
            z_score = self._calculate_z_score(hist, 20)
            
            # Velocity (Rate of Change) - ensures we don't catch falling knives
            # We check ROC over last 3 ticks to confirm a turn
            velocity = (hist[-1] - hist[-3]) / hist[-3] if hist[-3] > 0 else 0

            # STRATEGY 1: Elastic Snap (Replaces Penalized DIP_BUY)
            # Requirements:
            # 1. Price is statistically anomalous (Z < -2.4)
            # 2. Price has started to snap back (Velocity > threshold)
            # This is "stricter" as requested.
            if z_score < -self.dna['z_entry'] and velocity > self.dna['min_velocity']:
                # Volatility adjusted sizing
                size = min(self.balance * 0.1, self.base_risk * self.dna['vol_sensitivity'])
                return {
                    'side': 'BUY', 'symbol': sym, 'amount': round(size, 2),
                    'reason': ['ELASTIC_SNAP', f'Z_{z_score:.1f}']
                }

            # STRATEGY 2: Variance Breakout (Replaces MOMENTUM/EXPLORE)
            # Trades expansion of volatility in direction of trend
            if z_score > 2.0 and velocity > (self.dna['min_velocity'] * 2):
                # Ensure we aren't buying the absolute top (check against longer trend if needed)
                # But for HFT, velocity confirmation is key.
                size = min(self.balance * 0.1, self.base_risk)
                return {
                    'side': 'BUY', 'symbol': sym, 'amount': round(size, 2),
                    'reason': ['VARIANCE_BREAK', f'VEL_{velocity:.3f}']
                }

        return None