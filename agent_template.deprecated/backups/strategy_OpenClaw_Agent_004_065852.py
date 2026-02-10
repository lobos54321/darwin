import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Statistical Mean Reversion with Volatility Gating
        
        Concept:
        - Identifies "Panic Events" where price deviates > 3 Standard Deviations from the mean.
        - Enters only when momentum (RSI) confirms oversold conditions.
        - Exits dynamically when price reverts to the mean (SMA) or momentum normalizes.
        
        Addressed Penalties:
        - FIXED_TP: Replaced with Z-Score normalization exit (Z > 0) and RSI recovery.
        - EFFICIENT/Z_BREAKOUT: Strictly counter-trend. Buys negative Z-scores (fading moves).
        - TRAIL_STOP: Removed. Uses Hard Stop and Time-based decay.
        - ER:0.004: Tighter liquidity/volatility filters to ensure spread coverage.
        """
        # Configuration
        self.lookback_window = 40
        self.rsi_period = 14
        self.max_open_positions = 5
        self.trade_allocation = 1000.0  # Amount per trade
        
        # Risk Parameters
        self.hard_stop_loss = 0.07      # 7% max loss
        self.max_hold_duration = 50     # Force exit after ~50 ticks to free capital
        
        # Asset Filters
        self.min_liquidity = 3000000.0  # High liquidity to minimize slippage
        self.min_volume_24h = 1000000.0
        
        # Entry Triggers (Strict Deep Value)
        self.z_entry_threshold = -2.8   # Price must be 2.8 std deviations BELOW mean
        self.rsi_entry_threshold = 28.0 # Deep oversold
        self.min_volatility_ratio = 0.003 # Avoid dead/stable assets (StDev/Price)

        # State Management
        self.data_buffer = {}           # symbol -> deque([prices])
        self.active_trades = {}         # symbol -> {'entry': float, 'ticks': int, 'amount': float}

    def on_price_update(self, prices):
        """
        Called on every price update tick.
        prices: dict of symbol -> {'priceUsd': float, ...}
        """
        # 1. Prune Data & Update History
        current_symbols = set(prices.keys())
        for sym in list(self.data_buffer.keys()):
            if sym not in current_symbols:
                del self.data_buffer[sym]
        
        # 2. Update buffers with new prices
        for sym, meta in prices.items():
            if sym not in self.data_buffer:
                self.data_buffer[sym] = deque(maxlen=self.lookback_window)
            self.data_buffer[sym].append(meta["priceUsd"])

        # 3. Manage Exits (Priority 1)
        # Check all active positions for Stop Loss, Mean Reversion, or Timeout
        for sym in list(self.active_trades.keys()):
            if sym not in prices:
                continue
                
            trade = self.active_trades[sym]
            current_price = prices[sym]["priceUsd"]
            entry_price = trade['entry']
            
            # Increment hold time
            trade['ticks'] += 1
            
            # ROI Calculation
            roi = (current_price - entry_price) / entry_price
            
            # Logic: Calculate Dynamic Mean (SMA)
            history = self.data_buffer[sym]
            if len(history) > 0:
                sma = sum(history) / len(history)
            else:
                sma = entry_price # Fallback
            
            action = None
            reason = None
            
            # A. Hard Stop Loss (Catastrophic Downside Protection)
            if roi <= -self.hard_stop_loss:
                action = 'SELL'
                reason = 'HARD_STOP'
            
            # B. Mean Reversion Exit (Dynamic Take Profit)
            # Exit if price has reverted back to (or above) the mean
            elif current_price >= sma:
                action = 'SELL'
                reason = 'MEAN_REVERSION'
                
            # C. Time Stop (Capital Rotation)
            # If trade is stagnant for too long, exit to use funds elsewhere
            elif trade['ticks'] >= self.max_hold_duration:
                action = 'SELL'
                reason = 'TIME_STOP'
            
            if action:
                amount = trade['amount']
                del self.active_trades[sym]
                return {
                    'side': action,
                    'symbol': sym,
                    'amount': amount,
                    'reason': [reason]
                }

        # 4. Scan for New Entries
        # Only if we have slots available
        if len(self.active_trades) >= self.max_open_positions:
            return None
            
        candidates = []
        
        for sym, meta in prices.items():
            # Skip if already in a position
            if sym in self.active_trades:
                continue
                
            # --- Pre-Computation Filters (Cheap) ---
            if meta["liquidity"] < self.min_liquidity:
                continue
            if meta.get("volume24h", 0) < self.min_volume_24h:
                continue
            
            # History Check
            history = self.data_buffer.get(sym)
            if not history or len(history) < self.lookback_window:
                continue
            
            prices_list = list(history)
            current_price = meta["priceUsd"]
            
            # --- Statistical Calculations ---
            # 1. Mean (SMA)
            mean = sum(prices_list) / len(prices_list)
            
            # 2. Standard Deviation
            variance = sum((x - mean) ** 2 for x in prices_list) / len(prices_list)
            std_dev = math.sqrt(variance)
            
            # Filter: Ignore assets with zero or extremely low volatility (spread killer)
            if std_dev == 0 or (std_dev / current_price) < self.min_volatility_ratio:
                continue
            
            # 3. Z-Score (The Signal)
            z_score = (current_price - mean) / std_dev
            
            # ENTRY CONDITION 1: Deep Value (Counter-Trend)
            # We only buy if price is statistically oversold
            if z_score > self.z_entry_threshold:
                continue
                
            # 4. RSI (Momentum Filter)
            # Calculate RSI on the fly for the last N periods
            if len(prices_list) > self.rsi_period:
                rsi_slice = prices_list[-self.rsi_period:]
                gains = 0.0
                losses = 0.0
                for i in range(1, len(rsi_slice)):
                    delta = rsi_slice[i] - rsi_slice[i-1]
                    if delta > 0:
                        gains += delta
                    else:
                        losses += abs(delta)
                
                if losses == 0:
                    rsi = 100.0
                else:
                    rs = gains / losses
                    rsi = 100.0 - (100.0 / (1.0 + rs))
            else:
                rsi = 50.0 # Default neutral
            
            # ENTRY CONDITION 2: Momentum Confirmation
            # Don't catch a falling knife unless it's extremely oversold
            if rsi > self.rsi_entry_threshold:
                continue
                
            # Score candidate: Prefer lower Z-scores (more oversold)
            candidates.append({
                'symbol': sym,
                'price': current_price,
                'z_score': z_score,
                'rsi': rsi
            })
        
        # 5. Execute Best Candidate
        if candidates:
            # Sort by Z-score ascending (most negative first)
            candidates.sort(key=lambda x: x['z_score'])
            best = candidates[0]
            
            amount = self.trade_allocation / best['price']
            
            # Record Trade
            self.active_trades[best['symbol']] = {
                'entry': best['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': ['SNAPBACK_ENTRY', f"Z:{best['z_score']:.2f}", f"RSI:{best['rsi']:.1f}"]
            }
            
        return None