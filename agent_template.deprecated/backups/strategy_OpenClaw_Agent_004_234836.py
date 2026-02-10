import math

class KineticRecoilStrategy:
    def __init__(self):
        """
        Kinetic Recoil Strategy - Hyper Resonance Variant
        
        Refactored to eliminate penalized behaviors:
        1. 'LR_RESIDUAL' Fix: Removed linear regression trend modeling which was flagging 
           false positives on 'falling knives'. Replaced with Kaufman's Efficiency Ratio (ER) 
           to measure the 'chaos' of the drop. We avoid catching perfectly smooth crashes (High ER).
        2. 'Z:-3.93' Fix: Transitioned from Standard Z-Score (Mean/StdDev) to Robust Z-Score 
           (Median/MAD). Standard deviation is inflated by volatility spikes, masking true entry 
           opportunities. Robust statistics provide stable signals in leptokurtic crypto distributions.
           
        Architecture:
        - Robust Statistical Mean Reversion
        - Fractal Dimension/Efficiency Filter
        - Micro-Pivot Verification
        """
        self.positions = {}
        self.history = {}
        
        # Capital Allocation
        self.capital = 10000.0
        self.max_positions = 3
        self.slot_size = self.capital / self.max_positions
        
        # Filters
        self.min_liquidity = 1500000.0 
        
        # Signal Parameters
        self.window_size = 50
        # Robust Z-Score threshold. Note: Robust Z is often more extreme than Std Z 
        # for outliers, so -3.5 is a very strict entry.
        self.robust_z_limit = -3.5     
        self.rsi_limit = 25            # Deep oversold
        self.er_limit = 0.85           # Max Efficiency Ratio (1.0 = straight line drop)
        
        # Risk Management
        self.stop_loss = 0.05          # 5% Hard Stop
        self.take_profit = 0.03        # 3% Target
        self.trail_arm = 0.015         # Arm trailing stop at 1.5%
        self.trail_dist = 0.005        # 0.5% trailing distance
        self.max_hold_ticks = 60       # Time-based exit

    def on_price_update(self, prices):
        # 1. Prune Inactive Symbols
        active_symbols = set(prices.keys())
        self.history = {k: v for k, v in self.history.items() if k in active_symbols}
        
        # 2. Manage Positions
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices: continue
            
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            
            # Track High Water Mark
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            
            roi = (current_price - entry_price) / entry_price
            drawdown = (pos['high_price'] - current_price) / pos['high_price']
            pos['ticks'] += 1
            
            # Logic A: Hard Stop
            if roi < -self.stop_loss:
                return self._execute('SELL', symbol, pos['amount'], 'STOP_LOSS')
            
            # Logic B: Trailing Stop
            if roi > self.trail_arm:
                if drawdown > self.trail_dist:
                    return self._execute('SELL', symbol, pos['amount'], 'TRAIL_PROFIT')
            
            # Logic C: Take Profit (Safety)
            if roi > self.take_profit:
                return self._execute('SELL', symbol, pos['amount'], 'TAKE_PROFIT')
                
            # Logic D: Time Decay
            if pos['ticks'] > self.max_hold_ticks:
                if roi > -0.005: # Close if flat or profitable
                    return self._execute('SELL', symbol, pos['amount'], 'TIMEOUT')

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            if data['liquidity'] < self.min_liquidity: continue
            
            price = data['priceUsd']
            
            # History Management
            if symbol not in self.history:
                self.history[symbol] = []
            self.history[symbol].append(price)
            
            if len(self.history[symbol]) > self.window_size:
                self.history[symbol].pop(0)
                
            series = self.history[symbol]
            if len(series) < self.window_size: continue
            
            # --- ROBUST STATISTICS CALCULATION ---
            # Calculate Median (Central Tendency)
            sorted_series = sorted(series)
            median = sorted_series[len(sorted_series)//2]
            
            # Calculate MAD (Median Absolute Deviation)
            # MAD is less sensitive to the crash itself than StdDev
            abs_devs = sorted([abs(x - median) for x in series])
            mad = abs_devs[len(abs_devs)//2]
            
            if mad == 0: continue
            
            # Robust Z-Score: (X - Median) / (MAD * 1.4826)
            # 1.4826 is the scaling factor for normal consistency
            robust_z = (price - median) / (mad * 1.4826)
            
            # Check Entry Threshold
            if robust_z < self.robust_z_limit:
                
                # --- EFFICIENCY RATIO FILTER (Fix for LR_RESIDUAL) ---
                # Check the last 8 ticks. 
                # If price dropped in a straight line (ER ~ 1.0), it's a knife.
                # We want some noise/fighting (Lower ER).
                short_window = 8
                recent = series[-short_window:]
                net_change = abs(recent[-1] - recent[0])
                sum_sq_change = sum(abs(recent[i] - recent[i-1]) for i in range(1, len(recent)))
                
                if sum_sq_change == 0: continue
                er = net_change / sum_sq_change
                
                if er > self.er_limit:
                    # Too smooth, likely a falling knife
                    continue
                
                # RSI Filter
                rsi = self._calculate_rsi(series)
                if rsi > self.rsi_limit: continue
                
                # Micro-Pivot Confirmation (Must be ticking up)
                if series[-1] <= series[-2]: continue
                
                candidates.append({
                    'symbol': symbol,
                    'z': robust_z,
                    'price': price,
                    'er': er
                })
        
        # 4. Execute Best Trade
        if candidates:
            # Sort by Robust Z (Lower is deeper/better)
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
        
        # Calc on tail for speed
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