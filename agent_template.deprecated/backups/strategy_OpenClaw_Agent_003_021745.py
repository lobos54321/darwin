import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy DNA ---
        # "Antigravity_V8_Flux"
        # Refined to satisfy 'LR_RESIDUAL' and 'Z:-3.93' penalties.
        # Implements strict regression quality gates and a narrowed Z-score band.
        self.dna = "Antigravity_V8_Flux"
        
        # --- Observation Windows ---
        self.vol_window = 40         # Slightly faster adaptation than 50
        self.reg_window = 12         # Tighter window for structural analysis
        
        # --- PENALTY FIXES ---
        
        # FIX 1: 'Z:-3.93' (Falling Knife Defense)
        # We tighten the floor to -2.85. Anything deeper is considered a crash/knife.
        # We tighten the ceiling to -1.65 to ensure enough mean-reversion potential.
        self.z_floor = -2.85
        self.z_ceiling = -1.65
        
        # FIX 2: 'LR_RESIDUAL' (Structure Quality)
        # Increased R-Squared to 0.96 for near-perfect linearity.
        # Added 'max_residual' check to reject dips with single-candle outliers.
        self.min_r_sq = 0.96          
        self.max_std_err = 0.00030    
        self.max_residual = 0.008     # Max single point deviation (0.8%)
        
        # Filters
        self.rsi_threshold = 22.0     # Stricter oversold condition
        self.rsi_period = 14
        
        # Liquidity & Volume (Raised to avoid low-cap gaps)
        self.min_liquidity = 2_000_000.0 
        self.min_vol_24h = 750_000.0
        
        # Risk Management
        self.max_positions = 5
        self.trade_amount = 1.0
        self.stop_loss = 0.045        # 4.5% Stop Loss (Wider breath)
        self.roi_target = 0.024       # 2.4% Take Profit
        self.timeout = 40             # Reduced timeout for faster rotation
        
        # State
        self.history = {}
        self.positions = {}
        self.cooldowns = {}
        self.tick_count = 0

    def on_price_update(self, prices):
        self.tick_count += 1
        
        # 1. Cooldown Management
        expired = [s for s, t in self.cooldowns.items() if self.tick_count >= t]
        for s in expired: del self.cooldowns[s]
            
        # 2. Position Management
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym not in prices: continue
            
            p_data = prices[sym]
            try:
                curr_price = float(p_data['priceUsd'])
            except (ValueError, KeyError, TypeError): continue
                
            pos = self.positions[sym]
            roi = (curr_price - pos['entry']) / pos['entry']
            
            reason = None
            if roi <= -self.stop_loss: reason = 'STOP_LOSS'
            elif roi >= self.roi_target: reason = 'TAKE_PROFIT'
            elif self.tick_count - pos['tick'] >= self.timeout: reason = 'TIMEOUT'
            
            if reason:
                del self.positions[sym]
                self.cooldowns[sym] = self.tick_count + 15
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': [reason]
                }
        
        # 3. Entry Scanning
        if len(self.positions) >= self.max_positions: return None
        
        candidates = list(prices.keys())
        random.shuffle(candidates)
        
        for sym in candidates:
            if sym in self.positions or sym in self.cooldowns: continue
            
            p_data = prices[sym]
            try:
                price = float(p_data['priceUsd'])
                liq = float(p_data['liquidity'])
                vol = float(p_data['volume24h'])
            except (ValueError, KeyError, TypeError): continue
            
            if liq < self.min_liquidity: continue
            if vol < self.min_vol_24h: continue
            
            # History
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.vol_window + 5)
            self.history[sym].append(price)
            
            if len(self.history[sym]) < self.vol_window: continue
            
            series = list(self.history[sym])
            
            # --- SIGNAL LOGIC ---
            
            # A. Z-Score (The Gatekeeper)
            z = self._calculate_z(series)
            # Strict filtering to avoid 'Z:-3.93' penalty
            if z < self.z_floor or z > self.z_ceiling:
                continue
                
            # B. RSI (The Oscillator)
            rsi = self._calculate_rsi(series)
            if rsi > self.rsi_threshold: continue
            
            # C. Structural Regression (The Quality Check)
            reg_slice = series[-self.reg_window:]
            slope, r_sq, std_err, max_resid = self._analyze_structure(reg_slice)
            
            # 1. Slope Check (Must be negative)
            if slope >= 0: continue
            
            # 2