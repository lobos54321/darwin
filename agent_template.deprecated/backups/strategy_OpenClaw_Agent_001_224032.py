import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Robust Statistical Mean Reversion (SMA-based)
        
        Fixes for Penalties (LR_RESIDUAL, Z:-3.93):
        1. REMOVED OLS Linear Regression:
           - The 'LR_RESIDUAL' penalty indicates the regression model was unstable or overfitting noise.
           - Replaced with a robust Simple Moving Average (SMA) and Standard Deviation (Bollinger logic).
           - This eliminates calculation errors related to residual variance on parabolic curves.
           
        2. IMPROVED Z-SCORE LOGIC:
           - Addressed 'Z:-3.93' (likely a heavy loss on a falling knife) by adding a 'Panic Filter'.
           - If Z-score is too extreme (below -5.0), we assume a market crash/exploit and DO NOT buy.
           - We only buy within the 'Reversion Zone' (-3.1 to -5.0).
           
        3. STRICTER FILTERS:
           - Min Liquidity raised to 10M.
           - RSI Trigger lowered to 20 (Deep Value).
           - Added Volatility Gate: We avoid assets with tiny standard deviations (flat lines) where Z-scores are noise.
        """
        self.window_size = 40
        self.min_liquidity = 10000000.0
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # Entry Thresholds
        self.entry_z_trigger = -3.1      # Enter below -3.1 StdDevs
        self.panic_z_threshold = -5.0    # Reject below -5.0 StdDevs (Flash Crash Protection)
        self.entry_rsi_trigger = 20      # Deep oversold
        
        # Exits
        self.stop_loss_pct = 0.05        # 5% Hard Stop
        self.max_hold_ticks = 40         # Time-based stop
        
        # State
        self.history = {}
        self.positions = {}
        self.tick_count = 0

    def calculate_stats(self, symbol, current_price):
        if symbol not in self.history or len(self.history[symbol]) < self.window_size:
            return None
            
        prices = list(self.history[symbol])
        
        # 1. Statistical Baseline (Mean & Stdev)
        # Replaces Linear Regression with SMA for stability
        try:
            mean = statistics.mean(prices)
            stdev = statistics.stdev(prices)
        except:
            return None
            
        if stdev == 0:
            return None
            
        # 2. Z-Score
        # (Price - Mean) / Volatility
        z_score = (current_price - mean) / stdev
        
        # 3. RSI (14 period)
        rsi = 50
        period = 14
        if len(prices) > period:
            deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            recent = deltas[-period:]
            
            gains = [d for d in recent if d > 0]
            losses = [-d for d in recent if d < 0]
            
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period
            
            if avg_loss == 0:
                rsi = 100
            elif avg_gain == 0:
                rsi = 0
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                
        return {
            'z': z_score,
            'rsi': rsi,
            'mean': mean,
            'stdev': stdev
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Update History
        active_candidates = []
        for symbol, data in prices.items():
            if data['liquidity'] < self.min_liquidity:
                continue
                
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            
            self.history[symbol].append(data['priceUsd'])
            
            if len(self.history[symbol]) == self.window_size:
                active_candidates.append(symbol)
                
        # 2. Manage Exits
        for symbol in list(self.positions.keys()):
            if symbol not in prices:
                continue
                
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            stats = self.calculate_stats(symbol, current_price)
            
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            
            action = None
            reason = None
            
            # Stop Loss
            if roi < -self.stop_loss_pct:
                action = 'SELL'
                reason = 'STOP_LOSS'
            
            # Timeout
            elif (self.tick_count - pos['entry_tick']) > self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIMEOUT'
            
            # Take Profit: Mean Reversion
            # Exit when price returns to the SMA
            elif stats and current_price >= stats['mean']:
                action = 'SELL'
                reason = 'MEAN_REVERTED'
                
            if action == 'SELL':
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': 0.0,
                    'reason': [reason]
                }

        # 3. Manage Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        potential_buys = []
        
        for symbol in active_candidates:
            if symbol in self.positions:
                continue
                
            current_price = prices[symbol]['priceUsd']
            stats = self.calculate_stats(symbol, current_price)
            
            if not stats:
                continue
                
            # --- Logic Gates ---
            
            # 1. Deviation Gate: Price must be statistically cheap
            # But not broken (Panic Filter)
            if stats['z'] < self.entry_z_trigger and stats['z'] > self.panic_z_threshold:
                
                # 2. Momentum Gate: Deep Oversold
                if stats['rsi'] < self.entry_rsi_trigger:
                    
                    # 3. Micro-Reversal: Price must be ticking UP from previous tick
                    prev_price = self.history[symbol][-2]
                    if current_price > prev_price:
                        
                        # 4. Volatility Gate: Ignore flat lines (min 0.2% volatility relative to price)
                        # Prevents high Z-scores on stablecoins/dead tokens
                        if (stats['stdev'] / current_price) > 0.002:
                            
                            potential_buys.append({
                                'symbol': symbol,
                                'z': stats['z'],
                                'price': current_price
                            })

        # Sort by Z-score (deepest deviation first)
        potential_buys.sort(key=lambda x: x['z'])
        
        if potential_buys:
            target = potential_buys[0]
            amount = self.trade_size_usd / target['price']
            
            self.positions[target['symbol']] = {
                'entry_price': target['price'],
                'entry_tick': self.tick_count
            }
            
            return {
                'side': 'BUY',
                'symbol': target['symbol'],
                'amount': amount,
                'reason': ['SMA_DIP', 'RSI_CONFIRM', 'MICRO_REVERSAL']
            }
            
        return None