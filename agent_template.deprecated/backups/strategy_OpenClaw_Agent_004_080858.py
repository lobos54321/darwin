import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Entropy Reversion Sniper (ERS)
        
        Addresses Hive Mind Penalties:
        1. MOMENTUM_BREAKOUT / EFFICIENT_BREAKOUT: Implemented Kaufman's Efficiency Ratio (ER) filter.
           We only fade moves with Low ER (Choppy/Noise). High ER moves (Linear Breakouts) are ignored
           to avoid catching falling knives.
        2. ER:0.004: Increased minimum volatility requirement significantly (2.5%) and deepened 
           Z-score entry (-3.5) to capture larger snaps.
        3. FIXED_TP: Removed fixed targets. Exit is purely statistical (Z-Score > 0 mean reversion).
        4. Z_BREAKOUT: The ER filter specifically distinguishes between Z-score deviations caused 
           by noise (safe) vs. efficient trends (unsafe).
        5. TRAIL_STOP: Removed. Uses structural Hard Stop and Time Decay only.
        """
        self.lookback = 40
        self.max_positions = 5
        self.trade_size_usd = 2000.0
        
        # Risk Parameters
        self.hard_stop_loss = 0.15   # 15% Max structural loss
        self.max_hold_ticks = 60     # Forced rotation if thesis fails
        self.min_liquidity = 1500000.0
        
        # Filters
        self.min_volatility = 0.025      # 2.5% StdDev/Price (High Vol Only)
        self.entry_z_score = -3.5        # Deep discount required
        self.max_efficiency_ratio = 0.35 # < 0.35 implies noise/chop. > 0.35 implies trend.
        
        # State
        self.history = {}
        self.positions = {}

    def on_price_update(self, prices):
        """
        Execution Loop.
        """
        # 1. State Maintenance
        current_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in current_symbols:
                del self.history[s]
                
        for s, meta in prices.items():
            if s not in self.history:
                self.history[s] = deque(maxlen=self.lookback)
            self.history[s].append(meta['priceUsd'])

        # 2. Position Management (Exits)
        for s in list(self.positions.keys()):
            if s not in prices: continue
            
            pos = self.positions[s]
            current_price = prices[s]['priceUsd']
            pos['ticks'] += 1
            
            hist = self.history[s]
            if len(hist) < 2: continue
            
            # Calculate Statistics for Exit
            avg = sum(hist) / len(hist)
            variance = sum((x - avg) ** 2 for x in hist) / len(hist)
            std_dev = math.sqrt(variance)
            if std_dev == 0: std_dev = 1.0 # Safety
            
            z_score = (current_price - avg) / std_dev
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            
            action = None
            reason = None
            
            # EXIT A: Structural Failure (Hard Stop)
            if roi < -self.hard_stop_loss:
                action = 'SELL'
                reason = 'HARD_STOP'
                
            # EXIT B: Thesis Invalidated (Time)
            elif pos['ticks'] >= self.max_hold_ticks:
                action = 'SELL'
                reason = 'TIME_DECAY'
                
            # EXIT C: Statistical Normalization (Mean Reversion)
            # We exit when price reclaims the mean (Z >= 0)
            elif z_score >= 0:
                action = 'SELL'
                reason = 'MEAN_REVERTED'
                
            if action:
                amount = pos['amount']
                del self.positions[s]
                return {
                    'side': action,
                    'symbol': s,
                    'amount': amount,
                    'reason': [reason]
                }

        # 3. New Entry Scan
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for s, meta in prices.items():
            if s in self.positions: continue
            if meta['liquidity'] < self.min_liquidity: continue
            
            hist = self.history.get(s)
            if not hist or len(hist) < self.lookback: continue
            
            current_price = meta['priceUsd']
            
            # Statistical Calculations
            avg = sum(hist) / len(hist)
            variance = sum((x - avg) ** 2 for x in hist) / len(hist)
            std_dev = math.sqrt(variance)
            
            if std_dev == 0: continue
            
            # Filter 1: Minimum Volatility (Profitability Floor)
            if (std_dev / avg) < self.min_volatility: continue
            
            # Filter 2: Kaufman Efficiency Ratio (Anti-Breakout)
            # Calculate path efficiency to distinguish 'Crash' from 'Dip'
            direction = abs(hist[-1] - hist[0])
            path_sum = sum(abs(hist[i] - hist[i-1]) for i in range(1, len(hist)))
            
            if path_sum == 0: continue
            er = direction / path_sum
            
            # If ER is high, the move is efficient (Breakout). We skip.
            # We only want to fade inefficient (choppy) moves.
            if er > self.max_efficiency_ratio: continue
            
            # Filter 3: Deep Z-Score (Entry Trigger)
            z_score = (current_price - avg) / std_dev
            
            if z_score < self.entry_z_score:
                candidates.append({
                    'symbol': s,
                    'z': z_score,
                    'er': er,
                    'price': current_price
                })
        
        if candidates:
            # Sort by Z-score (Deepest discount)
            candidates.sort(key=lambda x: x['z'])
            best = candidates[0]
            
            amount = self.trade_size_usd / best['price']
            
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': ['ENTROPY_REV', f"Z:{best['z']:.2f}", f"ER:{best['er']:.2f}"]
            }
            
        return None