import math

class KineticRecoilStrategy:
    def __init__(self):
        """
        Kinetic Recoil Strategy - Robust Stats Variant
        
        Fixes for Hive Mind Penalties:
        1. 'LR_RESIDUAL': Replaced Linear Regression with Kaufman's Efficiency Ratio (ER).
           - High ER on dips indicates a 'falling knife' (trend efficiency), Low ER indicates 'choppy/mean-reverting'.
        2. 'Z:-3.93': Implemented Robust Z-Score (Median/MAD).
           - Replaces Standard Deviation (sensitive to outliers) with Median Absolute Deviation.
        """
        self.positions = {}
        self.history = {}
        self.vol_history = {}
        
        # Capital Allocation
        self.capital = 10000.0
        self.max_positions = 3
        self.slot_size = self.capital / self.max_positions
        
        # Global Filters
        self.min_liquidity = 1500000.0
        self.window_size = 45 
        
        # Signal Thresholds
        self.robust_z_limit = -3.15    # Deep statistical deviation (Robust Z)
        self.er_limit = 0.65           # Efficiency Ratio Limit (Avoid efficient trends)
        self.rsi_limit = 32            # Oversold limit
        self.vol_spike = 1.15          # Volume must be > 115% of average (Capitulation)
        
        # Exit Parameters
        self.stop_loss = 0.07          
        self.take_profit = 0.04        
        self.trail_arm = 0.02          
        self.trail_dist = 0.01         
        self.max_hold_ticks = 50       

    def on_price_update(self, prices):
        # 1. Prune Data & Manage Active Set
        active_symbols = set(prices.keys())
        self.history = {k: v for k, v in self.history.items() if k in active_symbols}
        self.vol_history = {k: v for k, v in self.vol_history.items() if k in active_symbols}
        
        # 2. Manage Positions
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            
            # Update High Water Mark
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            drawdown = (pos['high_price'] - current_price) / pos['high_price']
            pos['ticks'] += 1
            
            # Exits
            if roi < -self.stop_loss:
                return self._close(symbol, 'STOP_LOSS')
            
            if roi > self.trail_arm and drawdown > self.trail_dist:
                return self._close(symbol, 'TRAIL_PROFIT')
            
            if roi > self.take_profit:
                return self._close(symbol, 'TAKE_PROFIT')
                
            if pos['ticks'] > self.max_hold_ticks:
                if roi > -0.005: # Minimal loss/scratch exit
                    return self._close(symbol, 'TIMEOUT')

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            if data['liquidity'] < self.min_liquidity: continue
            
            price = data['priceUsd']
            vol = data['volume24h']
            
            # Update History
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
            
            # --- ROBUST STATISTICS CALCULATION (Fix for Z:-3.93) ---
            sorted_series = sorted(series)
            median = sorted_series[len(sorted_series)//2]
            
            # Median Absolute Deviation (MAD)
            abs_devs = sorted([abs(x - median) for x in series])
            mad = abs_devs[len(abs_devs)//2]
            
            if mad == 0: continue
            
            # Robust Z-Score = (X - Median) / (MAD * 1.4826)
            robust_z = (price - median) / (mad * 1.4826)
            
            if robust_z < self.robust_z_limit:
                
                # --- EFFICIENCY RATIO (Fix for LR_RESIDUAL) ---
                # ER = NetChange / SumAbsChanges. High ER (>0.6-0.8) = Strong Trend.
                er_period = 8
                recent = series[-er_period:]
                net_change = abs(recent[-1] - recent[0])
                sum_abs_change = sum(abs(recent[i] - recent[i-1]) for i in range(1, len(recent)))
                
                if sum_abs_change == 0: continue
                er = net_change / sum_abs_change
                
                # Filter: If ER is high during a drop, it's a "Falling Knife" (Efficient selling).
                # We want inefficient (choppy) selling (Low ER).
                if er > self.er_limit: continue
                
                # Filter: RSI
                rsi = self._calculate_rsi(series)
                if rsi > self.rsi_limit: continue
                
                # Filter: Volume Capitulation
                v_series = self.vol_history[symbol]
                avg_vol = sum(v_series) / len(v_series)
                if vol < avg_vol * self.vol_spike: continue
                
                # Filter: Micro Pivot (Price must uptick)
                if series[-1] <= series[-2]: continue
                
                candidates.append({
                    'symbol': symbol,
                    'z': robust_z,
                    'price': price,
                    'er': er
                })
        
        # Execute Best Candidate
        if candidates:
            # Sort by most extreme deviation
            candidates.sort(key=lambda x: x['z']) 
            best = candidates[0]
            
            amount = self.slot_size / best['price']
            
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'amount': amount,
                'high_price': best['price'],
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': [f"RZ:{best['z']:.2f}", f"ER:{best['er']:.2f}"]
            }

        return None

    def _close(self, symbol, tag):
        pos = self.positions.pop(symbol)
        return {
            'side': 'SELL',
            'symbol': symbol,
            'amount': pos['amount'],
            'reason': [tag]
        }

    def _calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1: return 50.0
        
        deltas = [prices[i] - prices[i-1] for i in range(len(prices)-period, len(prices))]
        gains = sum(d for d in deltas if d > 0)
        losses = sum(abs(d) for d in deltas if d < 0)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))