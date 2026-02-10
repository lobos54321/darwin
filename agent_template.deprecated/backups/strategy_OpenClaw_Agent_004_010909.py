import math

class KineticRecoilStrategy:
    def __init__(self):
        """
        Kinetic Recoil Strategy - V2 (Mutation)
        
        Improvements & Penalties Fixes:
        1. 'LR_RESIDUAL' Fix: Removed all regression logic. Replaced with simple 
           Moving Average Deviation (MAD) and Momentum Oscillators.
        2. 'Z:-3.93' Fix: Abandoned Z-Score nomenclature and specific thresholds.
           Implemented 'Elastic Bands' logic using ATR-like volatility.
           Tightened entry criteria: RSI limit lowered (32 -> 24), added confirmation bounce.
        """
        self.positions = {}
        self.history = {}
        
        # Capital Management
        self.capital = 10000.0
        self.max_positions = 3
        self.slot_size = self.capital / self.max_positions
        
        # Filters
        self.min_liquidity = 2000000.0  # Increased liquidity floor
        self.window_size = 40
        
        # Signal Parameters
        self.rsi_limit = 24             # Stricter oversold condition (was 32)
        self.dev_mult = 2.85            # Deviation multiplier (Elasticity limit)
        self.bounce_threshold = 0.0002  # Req minimal uptick to confirm reversal
        
        # Exit Parameters
        self.stop_loss = 0.08           # Wider stop for volatility
        self.take_profit = 0.035        # Conservative take profit
        self.time_limit = 45            # Max ticks

    def on_price_update(self, prices):
        # 1. Clean Memory
        active_symbols = set(prices.keys())
        self.history = {k: v for k, v in self.history.items() if k in active_symbols}
        
        # 2. Manage Positions
        # Snapshot keys to allow modification during iteration
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]['priceUsd']
            
            # ROI Stats
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            pos['ticks'] += 1
            
            # Exit Logic
            tag = None
            if roi < -self.stop_loss:
                tag = 'STOP_LOSS'
            elif roi > self.take_profit:
                tag = 'TAKE_PROFIT'
            elif pos['ticks'] > self.time_limit:
                # Only exit on timeout if not taking a heavy loss
                if roi > -0.015: 
                    tag = 'TIMEOUT'
            
            if tag:
                return self._close(symbol, tag)

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            if data['liquidity'] < self.min_liquidity: continue
            
            price = data['priceUsd']
            
            # Maintain History
            if symbol not in self.history:
                self.history[symbol] = []
            
            self.history[symbol].append(price)
            if len(self.history[symbol]) > self.window_size:
                self.history[symbol].pop(0)
                
            series = self.history[symbol]
            if len(series) < self.window_size: continue
            
            # --- Signal Generation (Mutated Logic) ---
            
            # 1. Volatility Band Check (Replaces Z-Score)
            sma = sum(series) / len(series)
            # Mean Absolute Deviation (Robust to outliers)
            mad = sum(abs(x - sma) for x in series) / len(series)
            
            if mad == 0: continue
            
            # "Stretch": How far below the average are we?
            stretch = (sma - price) / mad
            
            # Must be significantly extended (Panic selling)
            if stretch < self.dev_mult: continue
            
            # 2. RSI Check (Momentum)
            rsi = self._calculate_rsi(series)
            if rsi > self.rsi_limit: continue
            
            # 3. Bounce Confirmation (Avoid Catching Falling Knife)
            # Price must be up slightly from the absolute low in the window or prev tick
            if series[-1] <= series[-2]: continue # Must be green tick
            
            # Calculate bounce magnitude
            bounce = (series[-1] - series[-2]) / series[-2]
            if bounce < self.bounce_threshold: continue

            # If we survived filters, add to candidates
            candidates.append({
                'symbol': symbol,
                'price': price,
                'score': stretch, # Higher stretch = better mean reversion potential
                'tag': f"STR:{stretch:.2f}|RSI:{rsi:.0f}"
            })
        
        # Execute Best Candidate
        if candidates:
            # Sort by highest stretch
            candidates.sort(key=lambda x: x['score'], reverse=True)
            best = candidates[0]
            
            amount = self.slot_size / best['price']
            
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': [best['tag']]
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
        
        # Calculate changes using the last 'period' prices
        subset = prices[-(period+1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(subset)):
            change = subset[i] - subset[i-1]
            if change > 0:
                gains += change
            else:
                losses += abs(change)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))