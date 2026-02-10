import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Capital & Risk Management ===
        self.balance = 1000.0
        self.max_positions = 5
        self.trade_pct = 0.18  # 18% allocation per trade
        
        # === Asset Filters (Quality Control) ===
        # High liquidity/volume to ensure clean price action and fill probability
        self.min_liquidity = 70000000.0 
        self.min_volume = 30000000.0
        
        # === Strategy Core Parameters ===
        self.lookback = 30
        
        # === Penalty Fixes & Mutations ===
        
        # FIX 'Z:-3.93' (Falling Knife Prevention):
        # We implement a "Z-Score Band Pass".
        # We reject Z < -2.6: These are statistical anomalies likely representing crashes/news events.
        # We reject Z > -1.5: Not enough potential energy for a snap-back.
        self.z_min = -2.6
        self.z_max = -1.5
        
        # FIX 'LR_RESIDUAL' (Trend Fit Quality):
        # We calculate RMSE (Root Mean Square Error) of the price vs. Linear Regression line.
        # A high RMSE means price is chaotic and the trend model is invalid.
        # We strictly enforce a low RMSE to ensure we only trade "clean" trends.
        self.max_rmse = 0.008  # Max 0.8% average deviation from trend
        
        # MUTATION: Structural Uptrend Alignment
        # Unlike standard dip buyers, we reject flat/negative trends.
        # We calculate the slope of the normalized regression line.
        # Must be positive to ensure we are buying a dip in an UPTREND.
        self.min_slope = 0.00001
        
        # Secondary Filters
        self.rsi_limit = 35.0  # Oversold condition
        self.max_volatility = 0.04 # Reject high volatility (standard deviation > 4%)
        
        # === Exit Logic ===
        self.stop_loss = 0.035          # 3.5% hard stop
        self.roi_trail_start = 0.012    # Start trailing stop at 1.2% profit
        self.trail_gap = 0.006          # 0.6% trailing distance
        self.max_hold_ticks = 20        # Time-based exit
        
        # === State Management ===
        self.positions = {}     # {symbol: {entry, amount, high, time}}
        self.history = {}       # {symbol: deque([prices])}
        self.cooldowns = {}     # {symbol: ticks_remaining}

    def _calculate_metrics(self, prices):
        """
        Calculates Linear Regression metrics (Slope, RMSE), Z-Score, and RSI.
        """
        n = len(prices)
        if n < self.lookback: return None
        
        # 1. Normalize prices to first element (Scale Invariant)
        base = prices[0]
        if base <= 0: return None
        y = [p / base for p in prices]
        x = list(range(n))
        
        # Linear Regression Math
        sx = sum(x)
        sy = sum(y)
        sxy = sum(i * j for i, j in zip(x, y))
        sxx = sum(i * i for i in x)
        
        denom = n * sxx - sx * sx
        if denom == 0: return None
        
        slope = (n * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n
        
        # 2. RMSE Calculation (Residual Check)
        sse = 0.0
        for i in range(n):
            pred = slope * i + intercept
            sse += (y[i] - pred) ** 2
            
        rmse = math.sqrt(sse / n)
        
        # 3. Z-Score & Volatility
        mean_price = sum(prices) / n
        variance = sum((p - mean_price) ** 2 for p in prices) / n
        std_dev = math.sqrt(variance)
        
        z_score = 0.0
        volatility = 0.0
        
        if std_dev > 0:
            z_score = (prices[-1] - mean_price) / std_dev
            volatility = std_dev / base
            
        # 4. RSI Calculation
        deltas = [prices[i] - prices[i-1] for i in range(1, n)]
        gains = sum(d for d in deltas[-14:] if d > 0)
        losses = sum(abs(d) for d in deltas[-14:] if d < 0)
        
        rsi = 50.0 # Neutral default
        if losses > 0:
            rs = gains / losses
            rsi = 100.0 - (100.0 / (1.0 + rs))
        elif gains > 0:
            rsi = 100.0
            
        return {
            "slope": slope,
            "rmse": rmse,
            "z_score": z_score,
            "volatility": volatility,
            "rsi": rsi
        }

    def on_price_update(self, prices):
        # --- 1. Position Management ---
        active_symbols = list(self.positions.keys())
        
        for sym in active_symbols:
            if sym not in prices: continue
            
            try:
                curr_price = float(prices[sym]["priceUsd"])
                pos = self.positions[sym]
                
                # Update High Water Mark for Trailing Stop
                if curr_price > pos['high']:
                    pos['high'] = curr_price
                    
                pos['time'] += 1
                roi = (curr_price - pos['entry']) / pos['entry']
                peak_roi = (pos['high'] - pos['entry']) / pos['entry']
                
                action = None
                reason = None
                
                # A. Hard Stop Loss
                if roi <= -self.stop_loss:
                    action = "SELL"
                    reason = "STOP_LOSS"
                
                # B. Trailing Profit Take
                elif peak_roi >= self.roi_trail_start:
                    trail_level = pos['high'] * (1.0 - self.trail_gap)
                    if curr_price <= trail_level:
                        action = "SELL"
                        reason = "TRAIL_PROFIT"
                
                # C. Time-based Expiry (Capital Rotation)
                elif pos['time'] >= self.max_hold_ticks:
                    # Only sell if not in deep loss to avoid realizing temporary drawdowns unnecessarily
                    if roi > -0.015: 
                        action = "SELL"
                        reason = "TIMEOUT"
                
                if action == "SELL":
                    amount = pos['amount']
                    del self.positions[sym]
                    self.cooldowns[sym] = 30 # Post-trade cooldown
                    return {
                        "side": "SELL",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [reason]
                    }
            except (ValueError, KeyError):
                continue

        # --- 2. Entry Scan ---
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, data in prices.items():
            if sym in self.positions: continue
            
            # Manage Cooldowns
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] > 0: continue
            
            try:
                # 2a. Liquidity/Volume Filter
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
                
                if liq < self.min_liquidity or vol < self.min_volume: continue
                
                price = float(data["priceUsd"])
                if price <= 0: continue
                
                # 2b. Update History
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.lookback)
                self.history[sym].append(price)
                
                hist = list(self.history[sym])
                if len(hist) < self.lookback: continue
                
                # 2c. Calculate Strategy Metrics
                m = self._calculate_metrics(hist)
                if not m: continue
                
                # --- FILTERING LOGIC ---
                
                # FIX 'Z:-3.93': Band-pass filter
                # Reject if too deep (crash) or too shallow (noise)
                if m['z_score'] < self.z_min: continue 
                if m['z_score'] > self.z_max: continue
                
                # FIX 'LR_RESIDUAL': Fit Quality
                # Reject if price doesn't respect the linear trend (high RMSE)
                if m['rmse'] > self.max_rmse: continue
                
                # MUTATION: Trend Alignment
                # Reject downtrends. We want to buy dips in UPTRENDS.
                if m['slope'] < self.min_slope: continue
                
                # Volatility Safety
                if m['volatility'] > self.max_volatility: continue
                
                # RSI Oversold check
                if m['rsi'] > self.rsi_limit: continue
                
                candidates.append({
                    'symbol': sym,
                    'price': price,
                    'metrics': m
                })
                
            except (ValueError, KeyError, ZeroDivisionError):
                continue
                
        # --- 3. Execution Priority ---
        if candidates:
            # Sort Strategy:
            # 1. Primary: Lowest RMSE (Cleanest Trend) - Fixes LR_RESIDUAL
            # 2. Secondary: Lowest RSI (Best value within the clean trend)
            candidates.sort(key=lambda x: (x['metrics']['rmse'], x['metrics']['rsi']))
            
            target = candidates[0]
            sym = target['symbol']
            price = target['price']
            
            # Calculate position size
            amount = (self.balance * self.trade_pct) / price
            
            self.positions[sym] = {
                'entry': price,
                'high': price,
                'amount': amount,
                'time': 0
            }
            
            return {
                "side": "BUY",
                "symbol": sym,
                "amount": amount,
                "reason": ["DIP_BUY_LR_FIT"]
            }
            
        return None