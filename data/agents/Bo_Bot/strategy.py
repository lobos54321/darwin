```python
import random
import statistics
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧬 AGENT: Bo_Bot | GEN: 98 | CODENAME: VULTURE_ADAPTIVE")
        print("📝 Evolution: Integrated Agent_008 DNA (RSI+BB). Added Volatility Sizing & Time-Decay Exits.")
        
        # --- Capital Management ---
        self.initial_balance = 1000.0
        self.current_balance = 1000.0
        self.positions = {}  # {symbol: {'entry': float, 'size': float, 'stop': float, 'tp': float, 'age': int, 'highest': float}}
        
        # --- Hyperparameters ---
        self.MAX_HISTORY = 60
        self.RSI_PERIOD = 14
        self.BB_PERIOD = 20
        self.BB_STD = 2.1          # Slightly wider than standard to avoid noise
        self.ATR_PERIOD = 14
        
        # --- Risk Management ---
        self.RISK_PER_TRADE = 0.02 # Risk 2% of equity per trade
        self.MAX_POSITIONS = 4     # Concentration limit
        self.TIME_STOP_TICKS = 8   # Exit if trade is stagnant
        self.MIN_ROI_TO_KEEP = 0.005 # 0.5% profit required to reset time stop
        
        # --- Data ---
        self.history = {}          # {symbol: deque(maxlen=60)}
        self.prev_prices = {}
        self.volatility_state = {} # 'LOW', 'NORMAL', 'HIGH'

    def calculate_rsi(self, prices):
        if len(prices) < self.RSI_PERIOD + 1:
            return 50.0
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        avg_gain = sum(gains[-self.RSI_PERIOD:]) / self.RSI_PERIOD if gains else 0
        avg_loss = sum(losses[-self.RSI_PERIOD:]) / self.RSI_PERIOD if losses else 0
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def calculate_indicators(self, symbol, prices):
        if len(prices) < self.MAX_HISTORY:
            return None
            
        current = prices[-1]
        
        # 1. Bollinger Bands
        bb_slice = list(prices)[-self.BB_PERIOD:]
        sma_20 = statistics.mean(bb_slice)
        std_dev = statistics.stdev(bb_slice)
        upper = sma_20 + (self.BB_STD * std_dev)
        lower = sma_20 - (self.BB_STD * std_dev)
        bb_width = (upper - lower) / sma_20
        
        # 2. RSI
        rsi = self.calculate_rsi(list(prices))
        
        # 3. ATR (Approximate using High-Low proxy from close prices)
        # Using standard deviation as a volatility proxy for sizing
        atr_proxy = std_dev 
        
        return {
            'sma': sma_20,
            'upper': upper,
            'lower': lower,
            'rsi': rsi,
            'atr': atr_proxy,
            'bb_width': bb_width
        }

    def get_position_size(self, price, stop_loss_price):
        """Kelly-lite sizing: Risk fixed % of equity based on distance to stop."""
        risk_amount = self.current_balance * self.RISK_PER_TRADE
        distance = abs(price - stop_loss_price)
        if distance == 0: return 0
        
        qty = risk_amount / distance
        # Cap max exposure to 20% of balance per trade to prevent ruin
        max_qty = (self.current_balance * 0.20) / price
        return min(qty, max_qty)

    def on_tick(self, market_data):
        """
        Main execution loop.
        market_data: dict {symbol: current_price}
        """
        orders = []
        
        # 1. Sync History
        for symbol, price in market_data.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.MAX_HISTORY)
            self.history[symbol].append(price)

        # 2. Manage Existing Positions (Risk & Exit)
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            current_price = market_data.get(symbol)
            
            if not current_price: continue
            
            # Track Age & Highs
            pos['age'] += 1
            if current_price > pos['highest']:
                pos['highest'] = current_price
            
            pnl_pct = (current_price - pos['entry']) / pos['entry']
            
            # A. Hard Stop Loss
            if current_price <= pos['stop']:
                orders.append({'action': 'SELL', 'symbol': symbol, 'reason': 'STOP_LOSS'})
                self.current_balance += current_price * pos['size']
                del self.positions[symbol]
                continue
                
            # B. Take Profit (Dynamic Mean Reversion)
            # If we revert to SMA and RSI is high, take profit
            indicators = self.calculate_indicators(symbol, self.history[symbol])
            if indicators:
                if current_price >= indicators['sma'] and indicators['rsi'] > 60:
                    orders.append({'action': 'SELL', 'symbol': symbol, 'reason': 'TAKE_PROFIT_SMA'})
                    self.current_balance += current_price * pos['size']
                    del self.positions[symbol]
                    continue

            # C. Time-Decay Stop (Zombie Protocol)
            # If held for N ticks and profit is negligible, kill it to free capital
            if pos['age'] > self.TIME_STOP_TICKS and pnl_pct < self.MIN_ROI_TO_KEEP:
                 orders.append({'action': 'SELL', 'symbol': symbol, 'reason': 'TIME_DECAY'})
                 self.current_balance += current_price * pos['size']
                 del self.positions[symbol]
                 continue
                 
            # D. Trailing Stop (Lock in profits)
            # If price moved up 3 ATRs, move stop to entry
            if indicators and (current_price - pos['entry']) > (3 * indicators['atr']):
                new_stop = current_price - (2 * indicators['atr'])
                if new_stop > pos['stop']:
                    pos['stop'] = new_stop

        # 3. Scan for New Entries
        if len(self.positions) >= self.MAX_POSITIONS:
            return orders

        available_cash = self.current_balance * 0.9 # Reserve 10%
        
        for symbol, price in market_data.items():
            if symbol in self.positions: continue
            if len(self.history[symbol]) < self.MAX_HISTORY: continue
            
            ind = self.calculate_indicators(symbol, self.history[symbol])
            if not ind: continue
            
            prev_price = self.prev_prices.get(symbol, price)
            
            # --- STRATEGY CORE: "The Elastic Band" ---
            # 1. Deep Value: Price below Lower BB
            is_oversold_price = price < ind['lower']
            
            # 2. RSI Confluence: RSI < 30 (Winner's DNA)
            is_oversold_rsi = ind['rsi'] < 30
            
            # 3. Price Action Confirmation: Tick Up (Winner's DNA)
            is_ticking_up = price > prev_price
            
            # 4. Volatility Filter: