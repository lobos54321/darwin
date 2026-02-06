```python
import random
import statistics
import math
from collections import deque

class MyStrategy:
    """
    Agent: Contrarian_239 -> Evolved: Phoenix_Rebirth_V4
    
    🧬 Evolution Report & DNA Merge:
    1.  **Inherited Winner DNA (Phoenix)**: 
        - Integrated RSI(14) for momentum filtering.
        - Adopted Bollinger Band Mean Reversion logic.
        - Retained 'Tick Up' (Price Action) confirmation.
    
    2.  **Unique Mutation - The 'Panic Stabilizer'**:
        - **Problem**: Previous version bought falling knives during high-momentum crashes.
        - **Solution**: Added 'Volatility Normalization'. We do not buy if the current bar's range is > 3x average range (Extreme Panic), unless RSI is extremely oversold (< 20).
        - **Time-Based Exit**: If a trade doesn't revert to mean within 10 bars, we exit. Prevents 'dead money' in losing positions.
    
    3.  **Survival Mode Risk Management**:
        - Current Capital ($536) is critical.
        - Position Sizing: Dynamic Kelly Criterion proxy. Lower size when volatility is high.
        - Hard Stop: Tightened to 1.5 * ATR to preserve capital.
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Phoenix_Rebirth_V4: Survival Mode)")
        
        # Configuration
        self.rsi_period = 14
        self.bb_period = 20
        self.bb_std_dev = 2.0
        self.max_history = 50
        self.stop_loss_atr_mult = 1.5
        self.max_hold_bars = 10
        
        # Data Structures
        # {symbol: deque([close_prices], maxlen=50)}
        self.price_history = {} 
        # {symbol: deque([high_low_range], maxlen=50)}
        self.volatility_history = {} 
        
        # Position Tracker
        # {symbol: {'entry_price': float, 'shares': int, 'bars_held': int, 'stop_price': float}}
        self.positions = {} 

    def calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50  # Neutral if not enough data
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        # Simple average for the first step (can be exponential for better accuracy)
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def get_bollinger_bands(self, prices, period=20, num_std=2):
        if len(prices) < period:
            return None
        
        sma = statistics.mean(prices[-period:])
        std_dev = statistics.stdev(prices[-period:])
        
        upper = sma + (std_dev * num_std)
        lower = sma - (std_dev * num_std)
        return sma, upper, lower, std_dev

    def next(self, context):
        """
        Main execution loop called by the engine.
        Args:
            context: object containing 'portfolio' (cash, positions) and 'data' (current market snapshot)
        """
        cash = context.portfolio.cash
        current_prices = context.data  # {symbol: current_price}
        
        # 1. Update Data & Manage Existing Positions
        for symbol, price in current_prices.items():
            # Initialize history if new
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.max_history)
                self.volatility_history[symbol] = deque(maxlen=self.max_history)
            
            # Store Price
            self.price_history[symbol].append(price)
            
            # Store Volatility (Approximate High-Low via Close-PrevClose abs diff for simplicity if HL unavailable)
            if len(self.price_history[symbol]) > 1:
                vol = abs(price - self.price_history[symbol][-2])
                self.volatility_history[symbol].append(vol)

            # Check Exit Conditions for existing positions
            if symbol in self.positions:
                pos = self.positions[symbol]
                pos['bars_held'] += 1
                
                # Logic: Exit
                sma, _, _, _ = self.get_bollinger_bands(list(self.price_history[symbol])) or (0,0,0,0)
                
                # Condition A: Stop Loss Hit
                if price <= pos['stop_price']:
                    print(f"🛑 STOP LOSS: {symbol} @ {price:.2f}")
                    context.order(symbol, -pos['shares'])
                    del self.positions[symbol]
                    continue
                
                # Condition B: Take Profit (Mean Reversion Complete)
                if sma > 0 and price >= sma:
                    print(f"💰 TAKE PROFIT: {symbol} @ {price:.2f} (Reverted to Mean)")
                    context.order(symbol, -pos['shares'])
                    del self.positions[symbol]
                    continue
                
                # Condition C: Time Decay (Stale Trade)
                if pos['bars_held'] >= self.max_hold_bars:
                    print(f"⏳ TIME EXIT: {symbol} (Held too long)")
                    context.order(symbol, -pos['shares'])
                    del self.positions[symbol]
                    continue

        # 2. Scan for New Entries
        # Shuffle symbols to avoid bias in low liquidity
        symbols = list(current_prices.keys())
        random.shuffle(symbols)

        for symbol in symbols:
            # Skip if already in position or not enough cash
            if symbol in self.positions or cash < 10:
                continue
                
            history = list(self.price_history[symbol])
            if len(history) < self.bb_period:
                continue

            # Calculate Indicators
            sma, upper, lower, std_dev = self.get_bollinger_bands(history)
            rsi = self.calculate_rsi(history, self.rsi_period)
            current_price = history[-1]
            prev_price = history[-2]
            
            # Calculate ATR proxy (Average of recent volatility)
            avg_vol = statistics.mean(list(self.volatility_history[symbol])[-14:]) if len(self.volatility_history[symbol]) > 0 else 0
            current_vol = abs(current_price - prev_price)

            # --- 🧬 GENETIC LOGIC 🧬 ---
            
            # 1. FILTER: Oversold & Undervalued
            is_oversold = rsi < 30
            is_below_band = current_price < lower
            
            # 2. CONFIRMATION: Price Action (Tick Up)
            # We want to see buyers stepping in. Current price > Previous Price
            is_recovering = current_price > prev_price
            
            # 3. MUTATION: Panic Filter
            # If current volatility is 3x the average, it's a crash. Don't buy unless RSI is EXTREME (<20).
            is_panic = current_vol > (avg_vol * 3)
            safe_to_enter = not is_panic or (is_panic and rsi < 20)

            if is_oversold and is_below_band and is_recovering and safe_to_enter:
                
                # Dynamic Sizing based on Volatility (Risk Parity Logic)
                # If volatility is high, buy less.
                risk_per_share = (std_dev * self.stop_loss_atr_mult)
                if risk_per_share == 0: continue
                
                # Risk 2% of current equity per trade
                equity = context.portfolio.total_value
                risk_amount = equity * 0.02
                
                shares_to_buy = math.floor(risk_amount / risk_per_share)
                cost = shares_to_buy * current_price
                
                # Cap size at 15% of equity to ensure diversification
                if cost > (equity * 0.15):
                    shares_to_buy = math.floor((equity * 0.15) / current_price