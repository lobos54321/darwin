import random
import statistics
import math
from collections import deque, defaultdict

class MyStrategy:
    def __init__(self):
        print("🧬 Strategy Evolved (Agent_006_v2: Mean Reversion + ATR Trailing + Time Decay)")
        
        # 1. Configuration (Absorbed from Winner + Mutation)
        self.rsi_period = 14
        self.bb_period = 20
        self.bb_std_dev = 2.0
        self.atr_period = 14
        
        # 2. Risk Management (Enhanced)
        self.max_position_size = 0.10  # Reduced from 0.15 to 0.10 for survival
        self.stop_loss_atr = 2.5       # Wide enough to breathe, tight enough to save
        self.take_profit_atr = 4.0
        self.max_hold_turns = 20       # Time-based stop loss (Mutation)
        
        # 3. Data Structures
        # Stores closing prices: {symbol: deque([p1, p2...])}
        self.price_history = defaultdict(lambda: deque(maxlen=50))
        # Stores High-Low-Close for ATR: {symbol: {'high': deque, 'low': deque, 'close': deque}}
        self.hlc_history = defaultdict(lambda: {'high': deque(maxlen=20), 'low': deque(maxlen=20), 'close': deque(maxlen=20)})
        
        # Track entry data for positions: {symbol: {'entry_price': float, 'entry_turn': int, 'stop_loss': float}}
        self.active_trades = {} 
        self.turn_count = 0

    def _calculate_rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50
        
        gains = []
        losses = []
        price_list = list(prices)
        
        for i in range(1, len(price_list)):
            delta = price_list[i] - price_list[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
                
        # Simple Average for efficiency in high-frequency
        avg_gain = statistics.mean(gains[-self.rsi_period:])
        avg_loss = statistics.mean(losses[-self.rsi_period:])
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calculate_bollinger_bands(self, prices):
        if len(prices) < self.bb_period:
            return None, None, None
        
        slice_prices = list(prices)[-self.bb_period:]
        sma = statistics.mean(slice_prices)
        std_dev = statistics.stdev(slice_prices)
        
        upper = sma + (self.bb_std_dev * std_dev)
        lower = sma - (self.bb_std_dev * std_dev)
        return upper, lower, sma

    def _calculate_atr(self, symbol):
        # Simplified ATR calculation using recent High-Low range proxy if full OHLC not available
        # Assuming we receive current price, we estimate volatility via standard deviation of recent closes if H/L missing
        prices = self.price_history[symbol]
        if len(prices) < self.atr_period:
            return prices[-1] * 0.02 # Default 2% volatility estimation
            
        # True Range approximation using Close volatility
        return statistics.stdev(list(prices)[-self.atr_period:])

    def next(self, current_prices, portfolio):
        """
        Main execution method for each trading iteration.
        :param current_prices: dict {symbol: price}
        :param portfolio: dict {'balance': float, 'positions': {symbol: quantity}}
        """
        self.turn_count += 1
        orders = []
        
        # 1. Update Data
        for symbol, price in current_prices.items():
            self.price_history[symbol].append(price)

        # 2. Manage Existing Positions (Exit Logic)
        for symbol, position_data in list(portfolio['positions'].items()):
            quantity = position_data['quantity'] if isinstance(position_data, dict) else position_data
            if quantity == 0: continue
            
            current_price = current_prices.get(symbol)
            if not current_price: continue
            
            trade_info = self.active_trades.get(symbol)
            
            # Safety cleanup if trade_info missing
            if not trade_info:
                # Force close unknown positions to reset state
                orders.append({'symbol': symbol, 'action': 'SELL', 'quantity': quantity, 'reason': 'SYNC_ERROR'})
                continue

            # A. Stop Loss / Take Profit
            if current_price <= trade_info['stop_loss']:
                orders.append({'symbol': symbol, 'action': 'SELL', 'quantity': quantity, 'reason': 'STOP_LOSS'})
                del self.active_trades[symbol]
                continue
            
            if current_price >= trade_info['take_profit']:
                orders.append({'symbol': symbol, 'action': 'SELL', 'quantity': quantity, 'reason': 'TAKE_PROFIT'})
                del self.active_trades[symbol]
                continue
                
            # B. Time Decay (Mutation: Don't hold dead money)
            turns_held = self.turn_count - trade_info['entry_turn']
            if turns_held > self.max_hold_turns:
                # If price hasn't moved much, exit to free capital
                orders.append({'symbol': symbol, 'action': 'SELL', 'quantity': quantity, 'reason': 'TIME_DECAY'})
                del self.active_trades[symbol]
                continue
            
            # C. Dynamic Trailing Stop (Winner DNA)
            # If price moves up, pull stop loss up
            atr = self._calculate_atr(symbol)
            new_stop = current_price - (self.stop_loss_atr * atr)
            if new_stop > trade_info['stop_loss']:
                trade_info['stop_loss'] = new_stop

        # 3. Scan for New Entries (Entry Logic)
        available_cash = portfolio['balance']
        
        for symbol, price in current_prices.items():
            if symbol in portfolio['positions'] and portfolio['positions'][symbol] > 0:
                continue # Already in position
                
            history = self.price_history[symbol]
            if len(history) < self.bb_period:
                continue

            # Indicators
            rsi = self._calculate_rsi(history)
            upper_bb, lower_bb, sma = self._calculate_bollinger_bands(history)
            atr = self._calculate_atr(symbol)
            
            if not lower_bb: continue

            # Logic: Mean Reversion + Momentum Filter
            # 1. Price is cheap (Below Lower BB or close to it)
            is_cheap = price < lower_bb * 1.01
            
            # 2. Oversold but stabilizing (RSI < 30 is too risky, RSI < 40 + UpTick is better)
            is_oversold = rsi < 40
            
            # 3. Price Action Confirmation (Tick Up)
            # Prevents buying a falling knife
            prev_price = history[-2] if len(history) > 1 else price
            is_ticking_up = price > prev_price

            # 4. Smart Randomness (Winner DNA) - Small chance to skip perfect setups to avoid herd traps
            # or small chance to buy "good enough" setups
            random_factor = random.random()
            
            should_buy = (is_cheap and is_oversold and is_ticking_up)
            
            if should_buy and available_cash > 10:
                # Position Sizing
                risk_per_share = atr * self.stop_loss_atr
                if risk_per_share == 0: continue
                
                # Calculate size based on % of equity
                target_value = portfolio['balance'] * self.max_position_size
                quantity = target_value / price
                cost = quantity * price
                
                if cost < available_cash:
                    orders.append({'symbol': symbol, 'action': 'BUY', 'quantity': quantity, 'reason': 'MEAN_REVERSION'})
                    
                    # Record Trade Metadata
                    self.active_trades[symbol] = {
                        'entry_price': price,
                        'entry_turn': self.turn_count,
                        'stop_loss': price - (atr * self.stop_loss_atr),
                        'take_profit': price + (atr * self.take_profit_atr)
                    }
                    available_cash -= cost

        return orders