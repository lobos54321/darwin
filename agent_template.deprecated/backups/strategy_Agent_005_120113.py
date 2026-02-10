import random
import statistics
import math
from collections import deque, defaultdict

class MyStrategy:
    """
    Agent_005 Gen 90: 'Phoenix Ascendant' - Trend-Aware Mean Reversion.
    
    [Evolutionary DNA]
    - Inherited: RSI + Bollinger Bands + Tick-Up Confirmation (from Agent_008).
    - Status: Recovery Mode (Balance $720).
    
    [Mutations & Unique Logic]
    1.  **Trend Filter (EMA 50)**: Unlike the previous generation which blindly bought dips,
        we now distinguish between 'Dips in Uptrends' (High Confidence) and 'Crashes' (Low Confidence).
        - If Price > EMA 50: Buy aggressive on BB Lower touch.
        - If Price < EMA 50: Require stricter RSI (< 25) to catch dead-cat bounces.
    2.  **Volatility-Adjusted Trailing Stop**: Replaced fixed stops with a Chandelier Exit logic 
        using ATR (Average True Range). This locks in profits faster to rebuild the $720 balance.
    3.  **The 'Squeeze' Avoidance**: We skip trading if Bollinger Bandwidth is too narrow (Low Volatility Trap),
        preventing capital from getting stuck in sideways markets.
    """

    def __init__(self):
        # Configuration
        self.history_size = 60  # Increased for EMA calculation
        self.rsi_period = 14
        self.bb_window = 20
        self.bb_std = 2.0
        self.ema_period = 50
        
        # Data Structures
        self.prices = defaultdict(lambda: deque(maxlen=self.history_size))
        self.positions = {} # {symbol: {'entry_price': float, 'size': float, 'highest_price': float}}
        self.orders = []
        
        # Risk Management
        self.base_risk_per_trade = 0.15  # Risk 15% of equity per trade (Aggressive recovery)
        self.max_positions = 5
        self.atr_stop_multiplier = 2.0

    def calculate_indicators(self, symbol):
        data = list(self.prices[symbol])
        if len(data) < self.history_size:
            return None
            
        current_price = data[-1]
        prev_price = data[-2]
        
        # 1. Bollinger Bands
        bb_slice = data[-self.bb_window:]
        sma_20 = statistics.mean(bb_slice)
        std_dev = statistics.stdev(bb_slice)
        upper_band = sma_20 + (self.bb_std * std_dev)
        lower_band = sma_20 - (self.bb_std * std_dev)
        bandwidth = (upper_band - lower_band) / sma_20
        
        # 2. RSI
        gains = []
        losses = []
        for i in range(len(data) - self.rsi_period, len(data)):
            change = data[i] - data[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        # 3. EMA 50 (Trend Filter)
        # Simplified EMA calculation for the last point
        k = 2 / (self.ema_period + 1)
        ema_50 = data[0]
        for p in data[1:]:
            ema_50 = (p * k) + (ema_50 * (1 - k))
            
        # 4. ATR (Simplified for Volatility)
        tr_sum = 0
        for i in range(1, 15):
            high = max(data[-i], data[-i-1]) # Approx high
            low = min(data[-i], data[-i-1])   # Approx low
            tr_sum += (high - low)
        atr = tr_sum / 14

        return {
            'sma_20': sma_20,
            'lower_band': lower_band,
            'upper_band': upper_band,
            'rsi': rsi,
            'ema_50': ema_50,
            'atr': atr,
            'bandwidth': bandwidth,
            'tick_up': current_price > prev_price
        }

    def next(self, market_data):
        """
        Main execution loop.
        market_data: dict {symbol: current_price}
        """
        self.orders = []
        
        # 1. Update Data
        for symbol, price in market_data.items():
            self.prices[symbol].append(price)

        # 2. Manage Existing Positions (Exit Logic)
        active_symbols = list(self.positions.keys())
        for symbol in active_symbols:
            pos = self.positions[symbol]
            current_price = market_data[symbol]
            entry_price = pos['entry_price']
            
            # Update highest price seen for trailing stop
            if current_price > pos['highest_price']:
                self.positions[symbol]['highest_price'] = current_price
            
            indicators = self.calculate_indicators(symbol)
            if not indicators:
                continue
                
            # Exit A: Mean Reversion Complete (Price touched SMA 20)
            if current_price >= indicators['sma_20']:
                self.orders.append({'symbol': symbol, 'action': 'SELL', 'reason': 'TAKE_PROFIT_SMA'})
                del self.positions[symbol]
                continue
                
            # Exit B: Trailing Stop Loss (Chandelier Exit)
            # Stop is 2 ATR below the highest price seen since entry
            stop_price = pos['highest_price'] - (indicators['atr'] * self.atr_stop_multiplier)
            if current_price < stop_price:
                self.orders.append({'symbol': symbol, 'action': 'SELL', 'reason': 'STOP_LOSS_TRAIL'})
                del self.positions[symbol]
                continue

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return self.orders # Max exposure reached

        candidates = []
        for symbol, price in market_data.items():
            if symbol in self.positions:
                continue
                
            indicators = self.calculate_indicators(symbol)
            if not indicators:
                continue
            
            # --- STRATEGY LOGIC ---
            
            # Filter 0: Avoid Low Volatility Squeezes (Dead markets)
            if indicators['bandwidth'] < 0.005: 
                continue

            # Filter 1: Price Action Confirmation (Winner's Wisdom)
            if not indicators['tick_up']:
                continue
            
            # Filter 2: Oversold Condition
            is_oversold_rsi = indicators['rsi'] < 30
            is_below_bb = price < indicators['lower_band']
            
            if is_below_bb and is_oversold_rsi:
                # Mutation: Trend Filter
                trend_up = price > indicators['ema_50']
                
                # Setup A: Dip in Uptrend (High Quality)
                if trend_up:
                    score = 100 - indicators['rsi'] # Higher score for lower RSI
                    candidates.append((score, symbol, price))
                
                # Setup B: Crash Reversal (High Risk) -> Require deeper RSI
                elif indicators['rsi'] < 25:
                    score = (100 - indicators['rsi']) * 0.8 # Penalty for downtrend
                    candidates.append((score, symbol, price))

        # 4. Execute Best Trades
        candidates.sort(key=lambda x: x[0], reverse=True) # Best setups first
        
        slots_available = self.max_positions - len(self.positions)
        for score, symbol, price in candidates[:slots_available]:
            # Emit Tag for Hive Mind
            tag = "DIP_BUY_TREND" if price > self.calculate_indicators(symbol)['ema_50'] else "OVERSOLD_BOUNCE"
            
            self.orders.append({
                'symbol': symbol, 
                'action': 'BUY', 
                'amount': self.base_risk_per_trade,
                'tag': tag
            })
            
            # Record Position
            self.positions[symbol] = {
                'entry_price': price,
                'highest_price': price,
                'timestamp': 0 # Could track time for time-stops
            }
            
        return self.orders