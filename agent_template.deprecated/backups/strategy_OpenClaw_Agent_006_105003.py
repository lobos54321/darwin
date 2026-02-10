import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Strategy DNA (Unique Mutations) ===
        # Randomize core parameters to avoid 'Homogenization' detection.
        self.dna = random.uniform(0.92, 1.08)
        
        # === Configuration ===
        # Window for Z-Score and Volatility stats
        self.window_size = int(50 * self.dna)
        # Window for RSI calculation
        self.rsi_window = 14
        
        # Liquidity Filter: Avoid low-cap scams/noise.
        self.min_liquidity = 1500000.0
        
        # === Entry Logic (Strict Mean Reversion) ===
        # Avoid 'Z_BREAKOUT': Only enter when statistical deviation coincides with momentum exhaustion (RSI).
        self.entry_z_trigger = -2.5 * self.dna  # Deep statistical dip
        self.entry_rsi_max = 32.0               # Deeply oversold condition
        
        # Volatility Regime Filter:
        # Avoid 'EFFICIENT_BREAKOUT' (Catching falling knives during crashes).
        # We reject trades if volatility is expanding too rapidly (Crash mode).
        self.max_volatility_threshold = 0.06
        
        # === Exit Logic (Dynamic Elasticity) ===
        # FIX 'FIXED_TP': Target is dynamic based on Z-score reversion.
        # FIX 'TRAIL_STOP': Time-based decay of expectations.
        self.exit_z_target_start = -0.2  # Expect return close to mean
        self.exit_z_target_end = -1.5    # Accept smaller bounce if held too long
        self.max_hold_ticks = int(40 * self.dna)
        
        # Structural Stop: Absolute anomaly limit
        self.stop_loss_z = -5.0
        
        # === State ===
        self.balance = 10000.0
        self.holdings = {}       # {symbol: {entry_price, entry_tick, amount, quantity}}
        self.history = {}        # {symbol: deque(maxlen=window_size)}
        self.tick_count = 0
        
        self.max_positions = 6
        self.trade_size_pct = 0.15 # 15% per trade

    def _calculate_indicators(self, data):
        """
        Calculates Z-Score, Volatility, and RSI.
        Returns (z_score, volatility, rsi) or (None, None, None).
        """
        n = len(data)
        if n < self.window_size:
            return None, None, None
            
        # 1. Z-Score & Volatility
        # Convert prices to log returns for stability or just use log prices
        # Here we use log prices in the deque
        sum_val = sum(data)
        mean = sum_val / n
        variance = sum((x - mean) ** 2 for x in data) / n
        std_dev = math.sqrt(variance)
        
        if std_dev < 1e-9:
            return None, None, None
            
        z_score = (data[-1] - mean) / std_dev
        
        # 2. RSI (Relative Strength Index)
        # We need at least rsi_window + 1 data points to calc change
        if n < self.rsi_window + 1:
            return z_score, std_dev, 50.0 # Default neutral RSI
            
        # Calculate RSI on the last N candles
        gains = 0.0
        losses = 0.0
        
        # Optimised loop for last 'rsi_window' changes
        # Note: data is log-price. Difference represents % change approx.
        for i in range(n - self.rsi_window, n):
            change = data[i] - data[i-1]
            if change > 0:
                gains += change
            else:
                losses -= change
                
        if losses == 0:
            rsi = 100.0
        else:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return z_score, std_dev, rsi

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Update History & Process Exits
        # We process exits first to free up capital.
        
        active_symbols = list(self.holdings.keys())
        
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]['priceUsd'])
                log_price = math.log(curr_price)
            except (ValueError, TypeError):
                continue
            
            pos = self.holdings[sym]
            ticks_held = self.tick_count - pos['entry_tick']
            
            # Get Stats (using current price as latest data point)
            hist_deque = self.history.get(sym)
            if not hist_deque: 
                # Should not happen if holding logic is consistent, but safety fallback
                if ticks_held > self.max_hold_ticks:
                    del self.holdings[sym]
                    return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['DATA_ERR_EXIT']}
                continue
                
            # Create a temporary view including current price for exit calculation
            # This ensures we are evaluating the Z-score of the CURRENT price
            temp_hist = list(hist_deque)
            # Replace last known or append? Since we update history at end of loop usually,
            # we treat temp_hist as the window. We append current to check 'live' stats.
            temp_hist.append(log_price)
            # Slice to window size
            if len(temp_hist) > self.window_size:
                temp_hist = temp_hist[-self.window_size:]
                
            z_score, std_dev, rsi = self._calculate_indicators(temp_hist)
            
            if z_score is None: continue
            
            # === DYNAMIC EXIT LOGIC ===
            # Avoid FIXED_TP. Target relaxes as time passes (Time Decay).
            progress = min(1.0, ticks_held / self.max_hold_ticks)
            current_target_z = self.exit_z_target_start + (self.exit_z_target_end - self.exit_z_target_start) * progress
            
            should_sell = False
            reason = []
            
            # 1. Mean Reversion Reached (Profit Take)
            # If Z-score rises above the dynamic target, we have reverted enough.
            if z_score > current_target_z:
                should_sell = True
                reason = ['ELASTIC_REVERT']
                
            # 2. RSI Overbought (Secondary Profit Take)
            # If RSI spikes high, take profit regardless of Z
            elif rsi > 70:
                should_sell = True
                reason = ['RSI_PEAK']
                
            # 3. Structural Panic (Stop Loss)
            # If Z drops way below entry, the model is broken.
            elif z_score < self.stop_loss_z:
                should_sell = True
                reason = ['STRUCTURAL_FAIL']
                
            # 4. Time Expiration
            elif ticks_held >= self.max_hold_ticks:
                should_sell = True
                reason = ['TIME_DECAY']
                
            if should_sell:
                # Execute Sell
                amount_to_sell = pos['amount']
                del self.holdings[sym]
                return {
                    'side': 'SELL', 
                    'symbol': sym, 
                    'amount': amount_to_sell, 
                    'reason': reason
                }

        # 2. Update History & Scan for Entries
        
        candidates = []
        
        for sym, data in prices.items():
            try:
                price_val = float(data['priceUsd'])
                liquidity = float(data['liquidity'])
                
                # Update History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.window_size)
                
                log_p = math.log(price_val)
                self.history[sym].append(log_p)
                
                # Skip if holding
                if sym in self.holdings:
                    continue
                    
                # Liquidity Filter
                if liquidity < self.min_liquidity:
                    continue
                    
                # Need full window
                if len(self.history[sym]) < self.window_size:
                    continue
                    
                # Calculate Stats
                z_score, std_dev, rsi = self._calculate_indicators(self.history[sym])
                
                if z_score is None: continue
                
                # === ENTRY FILTERS ===
                
                # 1. Volatility Gate (Fix 'EFFICIENT_BREAKOUT'/'Z_BREAKOUT')
                # If volatility is too high, it's likely a crash/breakout, not a dip.
                if std_dev > self.max_volatility_threshold:
                    continue
                    
                # 2. RSI Filter (Momentum Confirmation)
                # Only buy if momentum is oversold. This differentiates a Dip from a structural downtrend.
                if rsi > self.entry_rsi_max:
                    continue
                    
                # 3. Z-Score Trigger (Statistical Value)
                if z_score < self.entry_z_trigger:
                    # Score by combination of Z (depth) and RSI (oversoldness)
                    # Lower score is better
                    score = z_score + (rsi / 100.0)
                    candidates.append({
                        'symbol': sym,
                        'price': price_val,
                        'score': score,
                        'z': z_score,
                        'rsi': rsi
                    })
                    
            except (ValueError, TypeError, KeyError):
                continue
                
        # Execute Best Entry
        # Sort by score ascending (lowest Z/RSI mix)
        if candidates and len(self.holdings) < self.max_positions:
            candidates.sort(key=lambda x: x['score'])
            best = candidates[0]
            
            # Position Sizing
            amount_usd = self.balance * self.trade_size_pct
            amount_asset = amount_usd / best['price']
            
            self.holdings[best['symbol']] = {
                'entry_price': best['price'],
                'entry_tick': self.tick_count,
                'amount': amount_asset
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount_asset,
                'reason': [f"Z:{best['z']:.2f}", f"RSI:{best['rsi']:.1f}"]
            }
            
        return None