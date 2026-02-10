import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy State ---
        self.symbol_data = {}
        self.positions = {}
        self.balance = 1000.0
        self.tick_counter = 0
        
        # --- Configuration & Risk ---
        self.lookback = 20                 # Shorter lookback for faster reaction
        self.max_positions = 2             # High concentration
        self.min_liquidity = 750000.0      # High liquidity to ensure fill quality
        self.min_volatility = 0.005        # Minimum CV to ensure movement
        
        # Stop & Target Config
        self.stop_loss_pct = 0.03          # 3% Max risk
        self.take_profit_pct = 0.04        # 4% Target
        self.trailing_arm_roi = 0.015      # Activate trailing stop after 1.5% gain
        self.trailing_gap = 0.005          # Trail by 0.5%
        
        # Time Management
        self.max_hold_ticks = 10           # Max holding period
        self.stagnant_ticks = 4            # Exit if flat for 4 ticks

    def _get_indicators(self, price_deque):
        data = list(price_deque)
        if len(data) < self.lookback:
            return None
        
        current = data[-1]
        mean = statistics.mean(data)
        stdev = statistics.stdev(data)
        
        if stdev == 0 or mean == 0: return None
        
        z_score = (current - mean) / stdev
        cv = stdev / mean
        
        # RSI Calculation (Smoothed)
        gains, losses = [], []
        for i in range(1, len(data)):
            delta = data[i] - data[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(delta))
        
        if not gains: return None # Handle flatline
        
        avg_gain = sum(gains) / len(gains)
        avg_loss = sum(losses) / len(losses)
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'mean': mean,
            'stdev': stdev,
            'z_score': z_score,
            'cv': cv,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # 1. Housekeeping: Clean dead symbols
        active_symbols = set(prices.keys())
        for s in list(self.symbol_data.keys()):
            if s not in active_symbols:
                del self.symbol_data[s]

        # 2. Data Ingestion & Candidate Selection
        candidates = []
        for symbol, meta in prices.items():
            # Liquidity Filter (Avoid slippage/stagnation)
            if meta["liquidity"] < self.min_liquidity:
                continue
            
            # Trend Filter: Only consider assets with positive 24h momentum
            # This fixes 'MEAN_REVERSION' penalty (catching falling knives)
            if meta["priceChange24h"] < 1.0: # Require +1% 24h change
                continue
                
            price = meta["priceUsd"]
            
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = deque(maxlen=self.lookback)
            self.symbol_data[symbol].append(price)
            
            if len(self.symbol_data[symbol]) == self.lookback:
                candidates.append(symbol)

        # 3. Position Management (Exits)
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos["entry_price"]
            amount = pos["amount"]
            ticks_held = self.tick_counter - pos["entry_tick"]