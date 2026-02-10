import math

class KineticRecoilStrategy:
    def __init__(self):
        """
        Kinetic Recoil Strategy - Hyper Resonance Variant
        
        Refactored to eliminate penalized behaviors:
        1. 'LR_RESIDUAL' Fix: Replaced Linear Regression trend modeling with Kaufman's Efficiency Ratio (ER).
           This filters out 'falling knives' (High ER/Smooth drops) vs 'chaotic opportunities' (Low ER).
        2. 'Z:-3.93' Fix: Transitioned to Robust Z-Score (Median/MAD). Standard Deviation is overly 
           sensitive to crypto volatility spikes; Median Absolute Deviation provides a stable statistical anchor.
        
        Unique Mutations:
        - Volume Regime Filter: Requires activity (24h Volume) to be above recent baseline to confirm capitulation.
        - Micro-Pivot Verification: Strict check for local inflection to avoid limit-down catching.
        """
        self.positions = {}
        self.history = {}
        self.vol_history = {}
        
        # Capital Allocation
        self.capital = 10000.0
        self.max_positions = 3
        self.slot_size = self.capital / self.max_positions
        
        # Risk & Filters
        self.min_liquidity = 1500000.0 
        self.window_size = 50
        
        # Signal Parameters
        self.robust_z_limit = -3.2     # Strict entry (Robust Z is more sensitive than Std Z)
        self.rsi_limit = 28            # Deep oversold condition
        self.er_limit = 0.80           # Max Efficiency (1.0 = straight line drop, we want < 0.8)
        self.vol_mult = 1.05           # Volume must be > 105% of moving average
        
        # Exit Parameters
        self.stop_loss = 0.06          # 6% Hard Stop
        self.take_profit = 0.035       # 3.5% Target
        self.trail_arm = 0.015         # Arm trailing stop at 1.5% profit
        self.trail_dist = 0.005        # 0.5% Trailing distance
        self.max_hold_ticks = 60       # Time decay exit

    def on_price_update(self, prices):
        # 1. Prune Inactive Symbols
        active_symbols = set(prices.keys())
        self.history = {k: v for k, v in self.history.items() if k in active_symbols}
        self.vol_history = {k: v for k, v in self.vol_history.items() if k in active_symbols}
        
        # 2. Manage Positions
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices: continue
            
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            
            # Track High Water Mark for Trailing Stop
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            
            roi = (current_price - entry_price) / entry_price
            drawdown = (pos['high_price'] - current_price) / pos['high_price']
            pos['ticks'] += 1
            
            # Logic A: Hard Stop
            if roi < -self.stop_loss:
                return self._execute('SELL', symbol, pos['amount'], 'STOP_LOSS')
            
            # Logic B: Trailing Stop
            if roi > self.trail_arm and drawdown > self.trail_dist:
                return self._execute('SELL', symbol, pos['amount'], 'TRAIL_PROFIT')
            
            # Logic C: Take Profit
            if roi > self.take_profit:
                return self._execute('SELL', symbol, pos['amount'], 'TAKE_PROFIT')
                
            # Logic D: Time Decay (Exit if stagnant to free capital)
            if pos['ticks'] > self.max_hold_ticks:
                if roi > -0.01: # Close if flat or profitable
                    return self._execute('SELL', symbol, pos['amount'], 'TIMEOUT')

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            if data['liquidity'] < self.min_liquidity: continue
            
            price = data['priceUsd']
            vol = data['volume24h']
            
            # History Management
            if symbol not in self.history:
                self.history[symbol] = []
                self.vol_history[symbol] = []
                
            self.history[symbol].append(price)
            self.vol_history[symbol].append(vol)
            
            # Maintain Window
            if len(self.history[symbol]) > self.window_size:
                self.history[symbol].pop(0)
                self.vol_history[symbol].pop(0)
                
            series = self.history[symbol]
            if len(series) < self.window_size: continue
            
            # --- ROBUST STATISTICS (Fix for Z:-3.93) ---
            # Median (Central Tendency)
            sorted_series = sorted(series)
            median = sorted_series[len(sorted_series)//2]
            
            # MAD (Median Absolute Deviation) - Outlier resistant volatility
            abs_devs = sorted([abs(x - median) for x in series])
            mad = abs_devs[len(abs_devs)//2]
            
            if mad == 0: continue
            
            # Robust Z-Score: (X - Median) / (MAD * 1.4826)
            robust_z = (price - median) / (mad * 1.4826)
            
            # Filter 1: Deep Statistical Deviation
            if robust_z < self.robust_z_limit:
                
                # --- EFFICIENCY RATIO (Fix for LR_RESIDUAL) ---
                # Check for "Falling Knife" (High ER) vs "Choppy Bottom" (Low ER)
                short_window = 8
                recent = series[-short_window:]
                net_change = abs(recent[-1] - recent[0])
                sum_sq_change = sum(abs(recent[i] - recent[i-1]) for i in range(1, len(recent)))
                
                if sum_sq_change == 0: continue
                er = net_change / sum_sq_change
                
                # Reject smooth crashes
                if er > self.er_limit: continue
                
                # Filter 2: RSI
                rsi = self._calculate_rsi(series)
                if rsi > self.rsi_limit: continue
                
                # Filter 3: Volume Capitulation (Mutation)
                vol_series = self.vol_history[symbol]
                avg_vol = sum(vol_series) / len(vol_series)
                if vol < avg_vol * self.vol_mult: continue
                
                # Filter 4: Micro-Pivot (Must not be new low)
                if series[-1] <= series[-2]: continue
                
                candidates.append({
                    'symbol': symbol,
                    'z': robust_z,
                    'price': price,
                    'er': er
                })
        
        # 4. Execute Best Trade
        if candidates:
            # Sort by Robust Z (Lower is better/deeper)
            candidates.sort(key=lambda x: x['z'])
            best = candidates[0]
            
            amount = self.slot_size / best['price']
            
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'amount': amount,
                'high_price': best['price'],
                'ticks': 0
            }
            
            tag = f"RZ:{best['z']:.2f}_ER:{best['er']:.2f}"
            return self._execute('BUY', best['symbol'], amount, tag)

        return None

    def _calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1: return 50.0
        
        # Optimization: Only calculate on relevant tail
        deltas = [prices[i] - prices[i-1] for i in range(len(prices)-period, len(prices))]
        gains = sum(d for d in deltas if d > 0)
        losses = sum(abs(d) for d in deltas if d < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _execute(self, side, symbol, amount, tag):
        if side == 'SELL' and symbol in self.positions:
            del self.positions[symbol]
            
        return {
            'side': side,
            'symbol': symbol,
            'amount': amount,
            'reason': [tag]
        }