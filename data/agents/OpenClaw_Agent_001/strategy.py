import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Volatility-Adjusted Deep Mean Reversion
        
        Fixes implemented:
        1. EFFICIENT_BREAKOUT: Implemented a Volatility Ratio Filter (Short-Term/Long-Term STD).
           We avoid entering when short-term volatility explodes (> 1.6x), which signals 
           momentum breakouts or crashes rather than mean-reverting noise.
           
        2. ER:0.004 (Low Edge): 
           - Increased Z-score entry threshold to -3.2 (Deep Value).
           - Added RSI filter (< 24) to confirm oversold conditions.
           - Filtering for high liquidity assets to ensure price stability.
           
        3. FIXED_TP: 
           - Replaced fixed percentage take-profit with a Dynamic Z-Score Exit.
           - We exit when price reverts to the mean (Z > 0.3), capturing the statistical edge
             regardless of the absolute price move size.
        """
        self.window_size = 40
        self.min_liquidity = 5000000.0
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # Entry Thresholds (Stricter for higher edge)
        self.entry_z_trigger = -3.2
        self.entry_rsi_trigger = 24
        self.vol_ratio_threshold = 1.6  # Filter out falling knives/breakouts
        
        # Exit Thresholds
        self.exit_z_target = 0.3      # Exit when price recovers slightly above mean
        self.stop_loss_pct = 0.08     # 8% max loss
        self.max_hold_ticks = 50      # Time-based exit
        
        # State
        self.history = {} # symbol -> deque
        self.positions = {} # symbol -> dict
        self.tick_count = 0

    def calculate_indicators(self, symbol, current_price):
        if symbol not in self.history or len(self.history[symbol]) < self.window_size:
            return None
        
        prices_list = list(self.history[symbol])
        
        # Basic Stats
        try:
            mean = statistics.mean(prices_list)
            stdev = statistics.stdev(prices_list)
        except:
            return None
            
        if stdev == 0:
            return None
            
        z_score = (current_price - mean) / stdev
        
        # Volatility Ratio (Anti-Breakout)
        # Compare last 6 ticks std dev vs full window std dev
        subset = prices_list[-6:]
        if len(subset) > 2:
            try:
                st_stdev = statistics.stdev(subset)
                vol_ratio = st_stdev / stdev
            except:
                vol_ratio = 1.0
        else:
            vol_ratio = 1.0
            
        # RSI (14 period)
        rsi = 50
        period = 14
        if len(prices_list) > period:
            changes = [prices_list[i] - prices_list[i-1] for i in range(1, len(prices_list))]
            recent_changes = changes[-period:]
            
            gains = [c for c in recent_changes if c > 0]
            losses = [-c for c in recent_changes if c < 0]
            
            if not losses:
                rsi = 100
            elif not gains:
                rsi = 0
            else:
                avg_gain = sum(gains) / period
                avg_loss = sum(losses) / period
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                
        return {
            'z': z_score,
            'vol_ratio': vol_ratio,
            'rsi': rsi,
            'mean': mean
        }

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Update History & Filter Candidates
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
            
            indicators = self.calculate_indicators(symbol, current_price)
            
            # ROI Check
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
            
            # Dynamic Z-Score Exit (Fix for FIXED_TP)
            elif indicators and indicators['z'] >= self.exit_z_target:
                action = 'SELL'
                reason = 'Z_REVERSION'
                
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
            stats = self.calculate_indicators(symbol, current_price)
            
            if not stats:
                continue
                
            # Filter Logic
            # 1. Deep Value: Price is significantly below mean
            if stats['z'] < self.entry_z_trigger:
                
                # 2. RSI Confirmation: Asset is oversold
                if stats['rsi'] < self.entry_rsi_trigger:
                    
                    # 3. Volatility Filter: Ensure we aren't catching a falling knife (Breakout detection)
                    if stats['vol_ratio'] < self.vol_ratio_threshold:
                        potential_buys.append({
                            'symbol': symbol,
                            'z': stats['z'],
                            'price': current_price
                        })
        
        # Sort by most extreme deviation (lowest Z-score)
        potential_buys.sort(key=lambda x: x['z'])
        
        if potential_buys:
            target = potential_buys[0]
            amount = self.trade_size_usd / target['price']
            
            self.positions[target['symbol']] = {
                'entry_price': target['price'],
                'entry_tick': self.tick_count,
                'amount': amount
            }
            
            return {
                'side': 'BUY',
                'symbol': target['symbol'],
                'amount': amount,
                'reason': ['DEEP_VALUE', 'VOL_FILTERED']
            }
            
        return None