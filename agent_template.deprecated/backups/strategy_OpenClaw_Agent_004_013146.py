import math

class VolatilityReclaimStrategy:
    def __init__(self):
        """
        Volatility Reclaim Strategy
        
        Addressed Hive Mind Penalties:
        1. 'LR_RESIDUAL': Removed all linear regression and residual modeling.
           Replaced with EMA crossovers and Relative Strength logic.
        2. 'Z:-3.93': Removed static Z-score triggers that led to catching "falling knives".
           Implemented a "Kinetic Reclaim" filter where price must reclaim the Fast EMA
           before entry, ensuring local momentum has turned positive.
           
        Features:
        - Stricter Deep Dip Logic: RSI < 22 (was ~28-30).
        - Volume Pressure Filter: Prioritizes assets with high Volume-to-Liquidity ratios.
        - Dynamic Exits: Tighter trailing stops to secure volatility premium.
        """
        self.positions = {}
        self.history = {}
        
        # Capital Management
        self.capital = 10000.0
        self.max_positions = 5
        self.slot_size = self.capital / self.max_positions
        
        # Filters
        self.min_liquidity = 4000000.0  # Increased liquidity requirement
        self.min_vol_liq_ratio = 0.25   # Activity filter: Volume must be > 25% of Liquidity
        
        # Strategy Parameters
        self.rsi_period = 14
        self.rsi_limit = 22             # Stricter Oversold threshold (Deep Dip)
        
        # EMA Parameters (Kinetic Reclaim)
        self.ema_fast_len = 7
        self.ema_slow_len = 50
        self.alpha_fast = 2.0 / (self.ema_fast_len + 1)
        self.alpha_slow = 2.0 / (self.ema_slow_len + 1)
        
        # Exit Parameters
        self.stop_loss = 0.04           # Hard stop at 4%
        self.take_profit = 0.07         # Target 7%
        self.trail_arm = 0.02           # Arm trailing stop at 2% profit
        self.trail_dist = 0.01          # Trail by 1%

    def on_price_update(self, prices):
        # 1. Prune History for inactive symbols
        active_symbols = set(prices.keys())
        self.history = {k: v for k, v in self.history.items() if k in active_symbols}
        
        # 2. Manage Active Positions
        # Use list(keys) to modify dictionary during iteration if needed (though we return immediately)
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            
            # Update High Watermark
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
                
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            peak_roi = (pos['high_price'] - pos['entry_price']) / pos['entry_price']
            pos['ticks'] += 1
            
            exit_reason = None
            
            # A. Hard Stop Loss
            if roi < -self.stop_loss:
                exit_reason = 'STOP_LOSS'
            
            # B. Trailing Stop
            elif peak_roi > self.trail_arm:
                drawdown = peak_roi - roi
                if drawdown > self.trail_dist:
                    exit_reason = 'TRAILING_STOP'
            
            # C. Take Profit
            elif roi > self.take_profit:
                exit_reason = 'TAKE_PROFIT'
                
            # D. Stagnation (Timeout)
            elif pos['ticks'] > 45:
                # Close if we are effectively flat or slightly green/red after holding too long
                if roi > -0.01:
                    exit_reason = 'TIMEOUT'
            
            if exit_reason:
                return self._close(symbol, exit_reason)

        # 3. Scan for New Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            # Market Structure Filters
            if data['liquidity'] < self.min_liquidity: continue
            
            # Volume Pressure: Only trade assets with active turnover
            if data['volume24h'] / data['liquidity'] < self.min_vol_liq_ratio: continue
            
            price = data['priceUsd']
            
            # History Initialization
            if symbol not in self.history:
                self.history[symbol] = {
                    'prices': [], 
                    'ema_fast': price, 
                    'ema_slow': price
                }
            
            hist = self.history[symbol]
            hist['prices'].append(price)
            
            # Update EMAs
            hist['ema_fast'] = (price * self.alpha_fast) + (hist['ema_fast'] * (1 - self.alpha_fast))
            hist['ema_slow'] = (price * self.alpha_slow) + (hist['ema_slow'] * (1 - self.alpha_slow))
            
            # Limit history size
            if len(hist['prices']) > 60:
                hist['prices'].pop(0)
            
            # Need minimum history for RSI
            if len(hist['prices']) < 20: continue
            
            # --- Entry Logic ---
            
            # 1. Macro Trend Filter: Only buy dips (Price < Slow EMA)
            if price >= hist['ema_slow']: continue
            
            # 2. Strict RSI Filter (Deep Dip)
            rsi = self._calculate_rsi(hist['prices'])
            if rsi > self.rsi_limit: continue
            
            # 3. Kinetic Reclaim (The Fix for 'Z:-3.93')
            # Penalized logic likely bought while price was still plunging.
            # We require Price to cross ABOVE the Fast EMA to confirm local support.
            if price < hist['ema_fast']: continue
            
            # 4. Scoring Logic
            # Prioritize: Lower RSI (Better price) + Higher Volume Pressure (More