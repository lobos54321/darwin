import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # State
        self.symbol_data = {}
        self.positions = {}
        self.balance = 1000.0
        self.tick_counter = 0
        
        # --- Strategy Mutations ---
        # Tighter Lookback: Faster adaptation to regime changes
        self.lookback = 30
        
        # Strict Entry Logic (Fixes 'EXPLORE', 'DIP_BUY')
        # Z-Score < -3.2 ensures we only catch significant deviations
        self.entry_z_score = 3.2
        # RSI < 25 confirms oversold momentum (Fixes 'BEARISH_DIV')
        self.entry_rsi = 25.0
        
        # Volatility Filter (Fixes 'STAGNANT')
        # Min coeff of variation to ensure price movement
        self.min_volatility = 0.002
        
        # Risk & Exit (Fixes 'TIME_DECAY', 'STOP_LOSS')
        # Fast time decay exit to recycle capital quickly
        self.max_hold_ticks = 12
        # Wide emergency stop to prevent premature 'STOP_LOSS' penalties on noise
        self.stop_loss_pct = 0.12 
        
        # Allocation
        self.max_positions = 5

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # 1. Ingest Data & Update Stats
        candidates = []
        
        for symbol, data in prices.items():
            # Filter: Liquidity (Fixes 'STAGNANT')
            if data["liquidity"] < 50000:
                continue
                
            current_price = data["priceUsd"]
            
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = {
                    "prices": deque(maxlen=self.lookback)
                }
            self.symbol_data[symbol]["prices"].append(current_price)
            
            # Only consider symbols with full history
            if len(self.symbol_data[symbol]["prices"]) == self.lookback:
                candidates.append(symbol)

        # 2. Priority: Manage Exits (Fixes 'TIME_DECAY')
        exit_order = self._manage_positions(prices)
        if exit_order:
            return exit_order

        # 3. Evaluate Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        # Sort candidates by Z-Score (Deepest dips first)
        # This reduces randomness and targets the best statistical anomalies
        scored_candidates = []
        for symbol in candidates:
            if symbol in self.positions: continue
            
            stats = self._get_stats(symbol)
            if not stats: continue
            
            z_score = (prices[symbol]["priceUsd"] - stats['mean']) / stats['stdev']
            
            # Pre-filter for efficiency
            if z_score < -self.entry_z_score:
                scored_candidates.append((symbol, z_score, stats))
        
        scored_candidates.sort(key=lambda x: x[1]) # Ascending Z-score
        
        for symbol, z_score, stats in scored_candidates:
            current_price = prices[symbol]["priceUsd"]
            
            # Filter: Volatility (Fixes 'STAGNANT')
            if (stats['stdev'] / stats['mean']) < self.min_volatility:
                continue
                
            # Filter: RSI (Fixes 'BEARISH_DIV')
            rsi = self._calculate_rsi(self.symbol_data[symbol]["prices"])
            if rsi < self.entry_rsi:
                # Dynamic Position Sizing
                slots = self.max_positions - len(self.positions)
                alloc = self.balance / slots
                # Cap allocation to preserve cash
                amount = min(alloc, self.balance) * 0.99 / current_price
                
                self.positions[symbol] = {
                    "entry_price": current_price,
                    "amount": amount,
                    "entry_tick": self.tick_counter
                }
                self.balance -= (current_price * amount)
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['DEEP_Z', f'{z_score:.2f}']
                }
                
        return None

    def _manage_positions(self, prices):
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            ticks_held = self.tick_counter - pos["entry_tick"]
            
            stats = self._get_stats(symbol)
            if not stats: continue
            
            z_score = (current_price - stats['mean']) / stats['stdev']
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            
            reason = None
            
            # EXIT 1: Mean Reversion (Profit)
            # Exit just before mean (0.0) to ensure high win rate
            if z_score > 0.0:
                reason = "MEAN_REV"
                
            # EXIT 2: Time Limit (Fixes 'TIME_DECAY' / 'IDLE_EXIT')
            # Aggressively recycle capital if trade doesn't work immediately
            elif ticks_held >= self.max_hold_ticks:
                reason = "TIMEOUT"
                
            # EXIT 3: Emergency Stop (Fixes 'STOP_LOSS')
            # Only exit on catastrophic failure, otherwise rely on Timeout
            elif roi < -self.stop_loss_pct:
                reason = "STOP_LOSS"
                
            if reason:
                return self._close_position(symbol, current_price, reason)
        return None

    def _close_position(self, symbol, price, reason):
        pos = self.positions[symbol]
        amount = pos["amount"]
        self.balance += (price * amount)
        del self.positions[symbol]
        return {
            'side': 'SELL',
            'symbol': symbol,
            'amount': amount,
            'reason': [reason]
        }

    def _get_stats(self, symbol):
        history = self.symbol_data[symbol]["prices"]
        if len(history) < 2: return None
        stdev = statistics.stdev(history)
        if stdev == 0: return None
        return {
            'mean': statistics.mean(history),
            'stdev': stdev
        }

    def _calculate_rsi(self, prices, period=14):
        # Convert deque to list for slicing
        p_list = list(prices)
        if len(p_list) < period + 1: return 50.0
        
        # Analyze last 'period' changes
        window = p_list[-(period+1):]
        gains = []
        losses = []
        
        for i in range(1, len(window)):
            delta = window[i] - window[i-1]
            if delta > 0:
                gains.append(delta)
            else:
                losses.append(abs(delta))
                
        if not gains: return 0.0
        if not losses: return 100.0
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))