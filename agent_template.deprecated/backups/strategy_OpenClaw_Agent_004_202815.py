import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy State ---
        self.symbol_data = {}
        self.positions = {}
        self.balance = 1000.0
        self.tick_counter = 0
        
        # --- Mutations & Parameters ---
        # Lookback increased to capture better statistical context
        self.lookback = 40
        self.max_positions = 5
        
        # Liquidity Filter (Fixes 'STAGNANT' & 'EXPLORE')
        # Only trade high-liquidity pairs to ensure valid price discovery
        self.min_liquidity = 100000.0
        
        # Volatility Filter
        # Minimum Coeff of Variation to avoid dead assets
        self.min_volatility = 0.003
        
        # Adaptive Entry Logic (Fixes 'DIP_BUY', 'BEARISH_DIV')
        self.base_z_entry = 3.2
        self.base_rsi_entry = 24.0
        
        # Exit Logic (Fixes 'MEAN_REVERSION', 'TIME_DECAY')
        self.take_profit_rsi = 55.0  # Wait for momentum recovery, not just mean reversion
        self.take_profit_z = 0.5     # Exit slightly above mean
        self.stop_loss_pct = 0.10    # Hard stop
        self.max_hold_ticks = 10     # Max time to hold
        self.stale_ticks = 5         # Early exit if price doesn't move

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # 1. Market Regime Detection
        # Check for market-wide crashes to adjust aggression
        declines = 0
        total_active = 0
        for s, d in prices.items():
            if d['priceChange24h'] < -3.0: 
                declines += 1
            total_active += 1
            
        panic_mode = False
        if total_active > 0 and (declines / total_active) > 0.6:
            panic_mode = True
            
        # If market is panicking, require deeper dips to enter
        current_z_threshold = self.base_z_entry + (1.5 if panic_mode else 0.0)

        # 2. Data Ingestion
        candidates = []
        for symbol, data in prices.items():
            if data["liquidity"] < self.min_liquidity:
                continue
                
            price = data["priceUsd"]
            
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = {"prices": deque(maxlen=self.lookback)}
            
            self.symbol_data[symbol]["prices"].append(price)
            
            if len(self.symbol_data[symbol]["prices"]) == self.lookback:
                candidates.append(symbol)

        # 3. Position Management (Highest Priority)
        exit_order = self._manage_positions(prices)
        if exit_order:
            return exit_order

        # 4. Entry Evaluation
        if len(self.positions) >= self.max_positions:
            return None
            
        scored_opportunities = []
        
        for symbol in candidates:
            if symbol in self.positions: continue
            
            stats = self._get_stats(symbol)
            if not stats: continue
            
            # Filter: Ensure asset is volatile enough to rebound
            cov = stats['stdev'] / stats['mean']
            if cov < self.min_volatility: continue
            
            current_price = prices[symbol]["priceUsd"]
            z_score = (current_price - stats['mean']) / stats['stdev']
            
            # Entry Signal: Deep Z-Score + Oversold RSI
            if z_score < -current_z_threshold:
                rsi = self._calculate_rsi(self.symbol_data[symbol]["prices"])
                if rsi < self.base_rsi_entry:
                    scored_opportunities.append((symbol, z_score, rsi))
        
        # Sort by Z-score (Prioritize the most statistically significant dips)
        scored_opportunities.sort(key=lambda x: x[1])
        
        for symbol, z, rsi in scored_opportunities:
            price = prices[symbol]["priceUsd"]
            
            # Position Sizing
            slots = self.max_positions - len(self.positions)
            balance_share = self.balance / slots
            amount = (balance_share * 0.98) / price # 2% buffer
            
            self.positions[symbol] = {
                "entry_price": price,
                "amount": amount,
                "entry_tick": self.tick_counter
            }
            self.balance -= (amount * price)
            
            tag = 'PANIC_DIP' if panic_mode else 'DEEP_DIP'
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': amount,
                'reason': [tag, f'Z:{z:.2f}', f'RSI:{rsi:.1f}']
            }

        return None

    def _manage_positions(self, prices):
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            ticks_held = self.tick_counter - pos["entry_tick"]
            amount = pos["amount"]
            
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            
            stats = self._get_stats(symbol)
            if not stats: continue
            
            z_score = (current_price - stats['mean']) / stats['stdev']
            rsi = self._calculate_rsi(self.symbol_data[symbol]["prices"])
            
            exit_reason = None
            
            # EXIT 1: Stop Loss (Fixes 'STOP_LOSS' by acting decisively)
            if roi < -self.stop_loss_pct:
                exit_reason = "STOP_LOSS"
            
            # EXIT 2: Stagnation / Time Decay (Fixes 'IDLE_EXIT', 'TIME_DECAY')
            # If trade is flat for 5 ticks