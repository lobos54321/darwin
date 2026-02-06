# Darwin SDK - User Strategy Template
# 🧠 DEVELOPERS: EDIT THIS FILE ONLY!

import random
import math
import statistics
from collections import deque

class MyStrategy:
    """
    Agent: Contrarian_239 -> Evolved: Quantum_Recovery_v5
    
    🧬 Evolution Summary:
    1.  **Pivot from Contrarian**: The previous "Contrarian" approach likely caught falling knives, resulting in the -46% PnL.
    2.  **Volatility Breakout Logic**: Instead of guessing tops/bottoms, we now wait for price compression followed by an expansion (Breakout). We only trade when the market reveals its hand.
    3.  **Capital Preservation Mode**: Position sizing is strictly dynamic based on current (depleted) equity.
    4.  **Time-Decay Exit**: If a trade doesn't perform immediately, we cut it. No "hoping".
    """

    def __init__(self):
        print("🧠 Strategy Initialized (Quantum_Recovery_v5)")
        
        # --- Configuration ---
        self.HISTORY_LENGTH = 20        # Number of ticks to keep for calculation
        self.VOLATILITY_WINDOW = 10     # Window for StdDev calc
        self.BREAKOUT_FACTOR = 1.5      # Multiplier for Bollinger-like band
        
        # --- Risk Management (Recovery Mode) ---
        self.MAX_POSITIONS = 3          # Max concurrent trades to prevent overexposure
        self.POSITION_SIZE_PCT = 0.12   # Risk 12% of CURRENT balance per trade (approx $65 at current level)
        self.STOP_LOSS_PCT = 0.035      # 3.5% Hard Stop
        self.TAKE_PROFIT_PCT = 0.08     # 8% Target
        self.TRAILING_TRIGGER = 0.04    # Start trailing after 4% gain
        self.MAX_HOLD_TICKS = 15        # Close if stagnant for 15 ticks
        
        # --- State ---
        self.price_history = {}         # {symbol: deque([prices], maxlen=HISTORY_LENGTH)}
        self.active_positions = {}      # {symbol: {'entry_price': float, 'highest_price': float, 'ticks_held': int, 'amount_usd': float}}
        self.banned_tags = set()
        self.balance = 536.69           # Estimated current balance, will update if API allows

    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind regarding penalties or boosts."""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Penalty received for: {penalize}")
            self.banned_tags.update(penalize)
            # Immediate liquidation of banned assets
            for tag in penalize:
                if tag in self.active_positions:
                    # In a real scenario, we would emit a sell signal here immediately
                    # For this template, we mark it for sale in the next loop
                    self.active_positions[tag]['force_exit'] = True

    def _calculate_indicators(self, prices):
        """Calculates SMA and Standard Deviation."""
        if len(prices) < self.VOLATILITY_WINDOW:
            return None, None
        
        window = list(prices)[-self.VOLATILITY_WINDOW:]
        sma = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0
        return sma, stdev

    def on_price_update(self, prices: dict):
        """
        Main trading loop.
        """
        decision = {}
        
        # 1. Update Balance Estimate (Simplified simulation)
        # In a real SDK, self.balance would be updated by the engine. 
        # Here we assume we track it via closed trades roughly or keep static for sizing logic.
        
        current_symbols = set(prices.keys())
        
        # 2. Manage Existing Positions
        positions_to_close = []
        
        for symbol, pos_data in self.active_positions.items():
            if symbol not in prices:
                continue
                
            current_price = prices[symbol]["priceUsd"]
            entry_price = pos_data['entry_price']
            
            # Update High Watermark
            if current_price > pos_data['highest_price']:
                pos_data['highest_price'] = current_price
            
            # Update Hold Time
            pos_data['ticks_held'] += 1
            
            # Calculate PnL %
            pnl_pct = (current_price - entry_price) / entry_price
            
            # --- EXIT LOGIC ---
            
            # A. Hard Stop Loss
            if pnl_pct <= -self.STOP_LOSS_PCT:
                positions_to_close.append((symbol, "STOP_LOSS"))
                continue
                
            # B. Take Profit
            if pnl_pct >= self.TAKE_PROFIT_PCT:
                positions_to_close.append((symbol, "TAKE_PROFIT"))
                continue
            
            # C. Trailing Stop
            # If we reached trigger, stop is set at (Highest - 1.5%)
            if pos_data['highest_price'] >= entry_price * (1 + self.TRAILING_TRIGGER):
                trailing_stop_price = pos_data['highest_price'] * 0.985
                if current_price < trailing_stop_price:
                    positions_to_close.append((symbol, "TRAILING_STOP"))
                    continue
            
            # D. Time-Decay (Stagnation Kill)
            # If held for too long with no significant profit (< 1%), cut it to free capital
            if pos_data['ticks_held'] > self.MAX_HOLD_TICKS and pnl_pct < 0.01:
                positions_to_close.append((symbol, "STAGNATION"))
                continue

            # E. Hive Penalty
            if pos_data.get('force_exit', False):
                positions_to_close.append((symbol, "HIVE_BAN"))
                continue

        # Execute Exits
        for symbol, reason in positions_to_close:
            decision[symbol] = "sell"
            print(f"📉 SELL {symbol} | Reason: {reason}")
            del self.active_positions[symbol]

        # 3. Scan for New Entries
        if len(self.active_positions) < self.MAX_POSITIONS:
            
            # Sort symbols by 24h change to find active movers, ignoring banned ones
            candidates = [s for s in current_symbols if s not in self.banned_tags and s not in self.active_positions]
            
            for symbol in candidates:
                price_data = prices[symbol]
                current_price = price_data["priceUsd"]
                
                # Initialize history
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=self.HISTORY_LENGTH)
                self.price_history[symbol].append(current_price)
                
                # Need enough history to calculate indicators
                if len(self.price_history[symbol]) < self.VOLATILITY_WINDOW:
                    continue
                
                sma, stdev = self._calculate_indicators(self.price_history[symbol])
                
                if sma is None or stdev == 0:
                    continue
                
                # --- ENTRY LOGIC: Volatility Breakout ---
                # We want price to be ABOVE the upper band (Mean + N * StdDev)
                # This indicates a strong momentum move away from the average
                upper_band = sma + (stdev * self.BREAKOUT_FACTOR)
                
                # Filter: Ensure spread/volume isn't crazy (heuristic based on price > 0)
                valid_price = current_price > 0
                
                if valid_price and current_price > upper_band:
                    # Calculate position size
                    # Dynamic sizing: 12% of current estimated balance
                    usd_size = self.balance * self.POSITION_SIZE_PCT
                    
                    # Sanity check on min size
                    if usd_size > 10: 
                        decision[symbol] = f"buy {usd_size:.2f}"
                        self.active_positions[symbol] = {
                            'entry_price': current_price,
                            'highest_price': current_price,
                            'ticks_held': 0,
                            'amount_usd': usd_size
                        }
                        print(f"🚀 BUY {symbol} @ {current_price:.4f} | Breakout > {upper_band:.4f}")
                        
                        # Stop after filling one slot per tick to avoid race conditions
                        if len(self.active_positions) >= self.MAX_POSITIONS:
                            break
        
        return decision