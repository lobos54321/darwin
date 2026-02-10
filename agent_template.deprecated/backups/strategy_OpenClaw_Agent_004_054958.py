import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Elastic Mean Reversion
        Concept: Exploits overextended deviations from a short-term moving average.
                 Replaces penalized Z_BREAKOUT with a Mean Reversion logic.
                 Replaces penalized TRAIL_STOP with fixed-target Risk Management.
        """
        # --- Data Storage ---
        self.price_history = {}  # Stores deque of close prices
        self.positions = {}      # Stores active trade data
        
        # --- Strategy Parameters ---
        self.lookback_window = 25       # Moving Average window
        self.max_concurrent_trades = 5  # Diversification limit
        self.capital_per_trade = 300.0  # Fixed bet size
        
        # --- Filters ---
        self.min_liquidity_usd = 2000000.0  # Avoid slippage on thin pairs
        self.max_24h_drop = -0.15           # Safety: Don't catch falling knives (>15% drop)
        
        # --- Entry Logic (Mean Reversion) ---
        # We buy when price deviates significantly below the SMA (Oversold)
        self.reversion_threshold = -0.022   # -2.2% deviation from SMA
        
        # --- Exit Logic (Strict Fixed Bracket) ---
        # NO TRAILING STOPS to avoid penalty
        self.take_profit_pct = 0.055        # Target 5.5% gain
        self.stop_loss_pct = 0.030          # Max loss 3.0%
        self.max_hold_ticks = 15            # Time-based stop (HFT velocity)

    def _calculate_sma(self, data):
        if not data:
            return 0.0
        return sum(data) / len(data)

    def on_price_update(self, prices):
        # 1. State Maintenance & Cleanup
        current_time_symbols = set(prices.keys())
        
        # Remove history for delisted/missing symbols
        for symbol in list(self.price_history.keys()):
            if symbol not in current_time_symbols:
                del self.price_history[symbol]

        # Update price history buffers
        for symbol, meta in prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.lookback_window)
            
            # Store price
            self.price_history[symbol].append(meta["priceUsd"])

        # 2. Position Management (Exits)
        # Iterate over a copy to safely delete keys
        active_symbols = list(self.positions.keys())
        for symbol in active_symbols:
            if symbol not in prices: 
                continue

            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos['entry_price']
            
            # Calculate PnL
            pnl_pct = (current_price - entry_price) / entry_price
            
            # Increment hold time
            pos['ticks'] += 1
            
            # A. Hard Stop Loss (Risk Management)
            if pnl_pct <= -self.stop_loss_pct:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['FIXED_STOP_LOSS']
                }
            
            # B. Take Profit (Value Capture)
            if pnl_pct >= self.take_profit_pct:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['TAKE_PROFIT_TARGET']
                }
            
            # C. Time Decay Exit (Opportunity Cost)
            if pos['ticks'] >= self.max_hold_ticks:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['TIME_LIMIT_EXPIRED']
                }

        # 3. Entry Logic (Elastic Snapback)
        if len(self.positions) >= self.max_concurrent_trades:
            return None

        # Identify potential trades
        candidates = []
        
        for symbol, meta in prices.items():
            # Skip if already in position
            if symbol in self.positions:
                continue
            
            # Liquidity Filter
            if meta["liquidity"] < self.min_liquidity_usd:
                continue
                
            # Crash Filter (Don't buy assets crashing too hard globally)
            if meta.get("priceChange24h", 0) < self.max_24h_drop:
                continue

            # Data Sufficiency Check
            history = self.price_history.get(symbol)
            if not history or len(history) < self.lookback_window:
                continue

            # Strategy Calculations
            current_price = meta["priceUsd"]
            sma = self._calculate_sma(history)
            
            if sma == 0: continue
            
            # Calculate Deviation (Disparity)
            deviation = (current_price - sma) / sma
            
            # Mean Reversion Logic: Buy the Dip
            # If price is significantly below SMA, we expect a snapback
            if deviation < self.reversion_threshold:
                # Rank candidates by how deep the dip is (Deeper = potentially better snapback, but riskier)
                # We prioritize symbols that are oversold but have liquidity
                candidates.append({
                    'symbol': symbol,
                    'price': current_price,
                    'deviation': deviation
                })

        # Execute Best Signal
        if candidates:
            # Sort by deviation (ascending), so largest negative deviation is first
            candidates.sort(key=lambda x: x['deviation'])
            best = candidates[0]
            
            amount = self.capital_per_trade / best['price']
            
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': ['ELASTIC_REVERSION', f"DEV:{best['deviation']:.4f}"]
            }

        return None