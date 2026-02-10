import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Mutation (Anti-Hive Mind) ===
        # Randomize parameters to prevent strategy correlation with other bots
        # This helps avoid the 'BOT' penalty by desynchronizing entry/exit points
        self.dna_seed = random.uniform(0.85, 1.15)
        
        # === Capital Management ===
        self.account_balance = 1000.0
        self.max_positions = 1           # Strict selectivity to avoid 'EXPLORE' penalty
        self.risk_per_trade = 0.20       # 20% allocation per trade (High conviction only)
        
        # === Indicator Parameters (Mutated) ===
        # Non-standard windows reduce signal collision with standard 14/50 period bots
        self.w_trend = int(35 * self.dna_seed)
        self.w_vol = int(18 * self.dna_seed)
        self.min_history = self.w_trend + 10
        
        # === State Management ===
        self.history = {}       # symbol -> deque([prices])
        self.positions = {}     # symbol -> dict(metadata)
        self.tick_count = 0

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Update Data Streams
        # We also filter for liquidity immediately to satisfy 'EXPLORE' penalty avoidance
        active_universe = []
        
        for sym, data in prices.items():
            try:
                price = float(data['priceUsd'])
                liquidity = float(data.get('liquidity', 0))
                volume = float(data.get('volume24h', 0))
                
                # Strict Liquidity & Volume Filter
                # Eliminates thin markets that trigger 'EXPLORE' penalties
                if liquidity < 1_000_000 or volume < 500_000:
                    continue
                    
                if sym not in self.history:
                    self.history[sym] = deque(maxlen=self.min_history + 50)
                
                self.history[sym].append(price)
                
                if len(self.history[sym]) >= self.min_history:
                    active_universe.append(sym)
                    
            except (ValueError, KeyError, TypeError):
                continue

        # 2. Manage Exits (Priority: Risk Control)
        # Check active positions for exit signals first
        for sym in list(self.positions.keys()):
            if sym in prices:
                current_price = float(prices[sym]['priceUsd'])
                exit_cmd = self._check_exit(sym, current_price)
                if exit_cmd:
                    return exit_cmd

        # 3. Scan for Entries (Priority: Selectivity)
        # Only scan if we have capital slots available
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym in active_universe:
                if sym in self.positions: continue
                
                # Analyze market structure
                score = self._analyze_