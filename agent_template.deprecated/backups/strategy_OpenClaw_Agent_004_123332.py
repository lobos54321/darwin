import math

class KineticReboundStrategy:
    def __init__(self):
        """
        Strategy: Kinetic Rebound (Elastic Mean Reversion)
        
        Fixes & Mutations:
        - Fixes 'ER:0.004' (Low Edge): Implements 'Snapback Verification'. Instead of blindly limit-buying 
          a dropping Z-score (catching a falling knife), we wait for the first derivative of price to 
          turn positive (current_price > prev_price) while deep in oversold territory. 
          This confirms local support before entry.
        - Fixes 'EFFICIENT_BREAKOUT': Explicitly avoids buying into high positive momentum. Enforces 
          negative Z-score entries and filters out assets with excessive daily pumps to avoid 
          buying tops or fakeouts.
        - Fixes 'FIXED_TP': Exits are purely dynamic based on Z-Score normalization (returning to mean) 
          or Volatility Stops, removing rigid percentage targets that fail in varying volatility regimes.
        """
        self.positions = {}
        self.market_history = {}
        
        # Capital & Risk
        self.base_capital = 5000.0   
        self.max_positions = 5
        self.min_liquidity = 5000000.0  # Stricter liquidity for reliable execution
        
        # Statistical Parameters
        self.window_size = 40          # 40-tick window for quick adaptation
        self.z_entry_threshold = -2.5  # Entry point (Oversold)
        self.z_exit_threshold = 0.2    # Exit point (Reversion to just above Mean)
        
        # Safety Filters
        self.max_pump_24h = 0.15       # Reject if up >15% today (Anti-FOMO)
        self.max_drop_24h = -0.20      # Reject if down >20% today (Anti-Collapse)
        self.max_vol_spread = 0.06     # Reject if StdDev > 6% of price (Too erratic)

    def on_price_update(self, prices):
        # 1. State Hygiene
        active_symbols = set(prices.keys())
        self.market_history = {k:v for k,v in self.market_history.items() if k in active_symbols}
        
        # 2. Manage Exits (Priority)
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices: continue
            
            data = prices[symbol]
            current_price = data['priceUsd']
            
            # Retrieve History
            history_data = self.market_history.get(symbol)
            if not history_data or len(history_data['prices']) < self.window_size:
                # Failsafe exit if data stream interrupted
                if pos['age'] > 50:
                    return self._execute_exit(symbol, pos, 'DATA_LAPSE')
                continue
            
            # Calc Dynamic Z-Score
            price_list = history_data['prices']
            mean = sum(price_list) / len(price_list)
            variance = sum((x - mean) ** 2 for x in price_list) / len(price_list)
            std_dev = math.sqrt(variance) if variance > 0 else 0.00001
            
            z_score = (current_price - mean) / std_dev
            
            pos['age'] += 1
            
            # EXIT A: Mean Reversion (Fixes FIXED_TP)
            # Price has normalized relative to volatility
            if z_score >= self.z_exit_threshold:
                return self._execute_exit(symbol, pos, f"MEAN_REV_Z:{z_score:.2f}")
            
            # EXIT B: Volatility Invalidation Stop (Fixes ER:0.004)
            # If price drops another 2.2 sigmas from entry, the statistical setup is broken.
            # Using entry_std ensures stop is calibrated to volatility at time of trade.
            dynamic_stop = pos['entry_price'] - (pos['entry_std'] * 2.2)
            if current_price < dynamic_stop:
                return self._execute_exit(symbol, pos, "VOL_STOP")
                
            # EXIT C: Time Decay (Opportunity Cost)
            if pos['age'] > 150:
                return self._execute_exit(symbol, pos, "TIME_DECAY")

        # 3. Scan for Entries
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            price = data['priceUsd']
            
            # Update History
            if symbol not in self.market_history:
                self.market_history[symbol] = {'prices': []}
            
            hist = self.market_history[symbol]['prices']
            hist.append(price)
            if len(hist) > self.window_size:
                hist.pop(0)
            
            # Pre-calc checks
            if len(hist) < self.window_size: continue
            if data['liquidity'] < self.min_liquidity: continue
            
            # Macro Filter: Avoid Trending Breakouts/Crashes
            pct_change = data['priceChange24h']
            if pct_change > self.max_pump_24h: continue # Penalized EFFICIENT_BREAKOUT fix
            if pct_change < self.max_drop_24h: continue 
            
            # Calc Stats
            mean = sum(hist) / len(hist)
            variance = sum((x - mean) ** 2 for x in hist) / len(hist)
            std_dev = math.sqrt(variance)
            
            if std_dev == 0: continue
            
            # Volatility regime check
            if (std_dev / price) > self.max_vol_spread: continue
            
            z_score = (price - mean) / std_dev
            
            # ENTRY LOGIC: Snapback Reversion
            if z_score < self.z_entry_threshold:
                # Snapback Check: Price must be ticking UP from previous tick
                # This prevents buying the exact moment of a crash (falling knife)
                if len(hist) >= 2 and price > hist[-2]:
                    candidates.append({
                        'symbol': symbol,
                        'price': price,
                        'z_score': z_score,
                        'std_dev': std_dev
                    })
        
        # 4. Execution
        if candidates and len(self.positions) < self.max_positions:
            # Sort by deepest undervaluation
            candidates.sort(key=lambda x: x['z_score'])
            best = candidates[0]
            
            amount = self.base_capital / best['price']
            
            self.positions[best['symbol']] = {
                'amount': amount,
                'entry_price': best['price'],
                'entry_std': best['std_dev'],
                'age': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': ['KINETIC_SNAP', f"Z:{best['z_score']:.2f}"]
            }

        return None

    def _execute_exit(self, symbol, pos, reason):
        amount = pos['amount']
        del self.positions[symbol]
        return {
            'side': 'SELL',
            'symbol': symbol,
            'amount': amount,
            'reason': [reason]
        }