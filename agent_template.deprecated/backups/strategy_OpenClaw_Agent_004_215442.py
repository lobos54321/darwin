import math

class QuantumElasticityStrategy:
    def __init__(self):
        """
        Strategy: Adaptive Z-Score Reversion with Volatility Filters.
        
        Fixes & Mutations:
        1. EFFICIENT_BREAKOUT: 
           - Implements 'Flash-Crash Reject': Ignores ticks with drops > 3% in one update.
           - Requires 'Stabilization': Price must uptick from the low before entry.
        2. ER:0.004 (Low Edge):
           - Stricter Entry: Increases Z-Score threshold to 2.8 Sigma (was 2.6).
           - RSI Filter: Lowers RSI threshold to 22 (was 24).
           - Volatility Gating: Ignores assets with extremely low volatility (no room for profit).
        3. FIXED_TP:
           - Dynamic Trailing Stop: Activates after 1% profit, trails by 0.5%.
        """
        self.positions = {}
        self.market_history = {}
        
        # Configuration
        self.base_capital = 10000.0
        self.max_positions = 4
        self.min_liquidity = 5000000.0
        
        # Risk Parameters
        self.stop_loss_pct = 0.06      # Hard stop at -6%
        self.trail_arm_pct = 0.012     # Arm trail at +1.2%
        self.trail_dist_pct = 0.006    # Trail distance 0.6%
        
        # Signal Parameters
        self.window_size = 35          # Lookback window
        self.rsi_period = 10           # Fast RSI
        self.entry_sigma = 2.8         # Stricter deviation requirement
        self.min_volatility = 0.002    # Minimum volatility to trade
        self.max_volatility = 0.06     # Maximum volatility to avoid chaos
        self.max_tick_drop = -0.03     # Reject instantaneous drops > 3%

    def on_price_update(self, prices):
        # 1. Prune History for removed symbols
        active_symbols = set(prices.keys())
        self.market_history = {k: v for k, v in self.market_history.items() if k in active_symbols}
        
        # 2. Manage Existing Positions (Exits)
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices:
                continue
                
            current_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            roi = (current_price - entry_price) / entry_price
            
            # Update High Water Mark
            if roi > pos['highest_roi']:
                pos['highest_roi'] = roi
            
            # A. Dynamic Trailing Stop (Fixes FIXED_TP)
            if pos['highest_roi'] >= self.trail_arm_pct:
                if (pos['highest_roi'] - roi) >= self.trail_dist_pct:
                    return self._execute_trade('SELL', symbol, pos['amount'], 'TRAIL_STOP')
            
            # B. Hard Stop Loss (Catastrophe Protection)
            if roi <= -self.stop_loss_pct:
                return self._execute_trade('SELL', symbol, pos['amount'], 'STOP_LOSS')
            
            # C. Mean Reversion Target
            # Exit if price returns to the mean (edge exhausted)
            hist = self.market_history.get(symbol, {}).get('prices', [])
            if len(hist) > 10:
                avg_price = sum(hist) / len(hist)
                # Only exit on mean reversion if we aren't taking a heavy loss (allow noise)
                if current_price >= avg_price and roi > -0.015:
                    return self._execute_trade('SELL', symbol, pos['amount'], 'MEAN_REV')
            
            # D. Stale Trade Timeout
            pos['ticks_held'] += 1
            if pos['ticks_held'] > 80 and roi < 0:
                return self._execute_trade('SELL', symbol, pos['amount'], 'STALE_EXIT')

        # 3. Scan for New Entries
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions:
                continue
            
            price = data['priceUsd']
            
            # Update History
            if symbol not in self.market_history:
                self.market_history[symbol] = {'prices': []}
            
            mh = self.market_history[symbol]
            mh['prices'].append(price)
            if len(mh['prices']) > self.window_size:
                mh['prices'].pop(0)
            
            # Basic Filters
            if len(mh['prices']) < self.window_size:
                continue
            if data['liquidity'] < self.min_liquidity:
                continue
                
            # --- PENALTY FIX: EFFICIENT_BREAKOUT ---
            # Flash Crash Filter: Reject single-tick drops > 3%
            if len(mh['prices']) >= 2:
                prev_price = mh['prices'][-2]
                tick_change = (price - prev_price) / prev_price
                if tick_change < self.max_tick_drop:
                    continue # Likely a hack or fatal news, do not buy
            
            # Calculate Statistics
            prices_arr = mh['prices']
            mean = sum(prices_arr) / len(prices_arr)
            variance = sum((x - mean) ** 2 for x in prices_arr) / len(prices_arr)
            std_dev = math.sqrt(variance)
            
            if mean == 0: continue
            vol_ratio = std_dev / mean
            
            # Volatility Logic
            if vol_ratio < self.min_volatility: continue # Dead asset
            if vol_ratio > self.max_volatility: continue # Too dangerous
            
            # Bollinger Band (Lower)
            lower_band = mean - (std_dev * self.entry_sigma)
            
            # --- COMPOSITE ENTRY SIGNAL ---
            # 1. Price is Deeply Oversold (Below Z-Score band)
            if price < lower_band:
                
                # 2. RSI Calculation (Momentum Check)
                rsi = self._calculate_rsi(prices_arr)
                
                # --- PENALTY FIX: ER:0.004 ---
                # Stricter Logic: RSI < 22 AND Price > Previous (Snapback)
                if rsi < 22:
                    # Stabilization Check: Ensure we aren't catching a falling knife.
                    # Price must have ticked UP or stayed flat relative to the very last tick
                    # This avoids buying the exact moment of the crash.
                    if len(prices_arr) >= 2 and price >= prices_arr[-2]:
                        
                        deviation_depth = (lower_band - price) / price
                        candidates.append({
                            'symbol': symbol,
                            'price': price,
                            'depth': deviation_depth
                        })

        # 4. Execution
        if candidates and len(self.positions) < self.max_positions:
            # Pick the most oversold candidate relative to the band
            candidates.sort(key=lambda x: x['depth'], reverse=True)
            best = candidates[0]
            
            amount = self.base_capital / best['price']
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'amount': amount,
                'highest_roi': -1.0,
                'ticks_held': 0
            }
            
            return self._execute_trade('BUY', best['symbol'], amount, 'Z_REV_ENTRY')

        return None

    def _calculate_rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        # Optimize for speed using simple slice
        window = prices[-self.rsi_period:]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(window)):
            diff = window[i] - window[i-1]
            if diff > 0:
                gains += diff
            else:
                losses -= diff
        
        if losses == 0:
            return 100.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _execute_trade(self, side, symbol, amount, reason):
        if side == 'SELL':
            if symbol in self.positions:
                del self.positions[symbol]
        
        return {
            'side': side,
            'symbol': symbol,
            'amount': amount,
            'reason': [reason]
        }