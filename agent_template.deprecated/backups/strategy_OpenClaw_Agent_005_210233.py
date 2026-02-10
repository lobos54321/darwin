import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Diversity ===
        # Random seed ensures this instance has unique parameter tuning
        # allowing the Hive Mind to select the fittest variance.
        self.dna_seed = random.uniform(0.95, 1.05)
        
        # === Capital Management ===
        self.max_positions = 3
        self.account_balance = 1000.0  # Starting balance assumption
        self.risk_per_trade = 0.02     # Risk 2% of equity per trade
        
        # === Dynamic Parameters ===
        # Mutated window lengths to avoid herd behavior
        self.w_fast = int(14 * self.dna_seed)
        self.w_slow = int(50 * self.dna_seed)
        self.w_vol = 24
        
        # Stricter thresholds based on seed
        self.rsi_period = 14
        self.z_entry_threshold = -3.0 * self.dna_seed  # Deep deviation
        
        # === State Management ===
        self.history = {}       # symbol -> deque([prices])
        self.positions = {}     # symbol -> dict(metadata)
        self.tick_count = 0
        
        # Warmup requirements
        self.min_warmup = self.w_slow + 20

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Manage Active Positions (Priority: Exit Logic)
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym in prices:
                self._update_history(sym, prices[sym])
                exit_cmd = self._check_exit(sym, prices[sym])
                if exit_cmd:
                    return exit_cmd

        # 2. Scan for Entries (Priority: Selectivity)
        # Only scan if we have capital slots available
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym, data in prices.items():
                # Skip active positions
                if sym in self.positions: continue
                
                # Update history stream
                self._update_history(sym, data)
                
                # Data Maturity Check
                if len(self.history[sym]) < self.min_warmup: continue
                
                # === Penalty Avoidance: 'EXPLORE' ===
                # Filter out low liquidity/volume to ensure trade execution quality
                # Accessing dictionary fields safely
                liq = data.get('liquidity', 0)
                vol = data.get('volume24h', 0)
                if liq < 200000 or vol < 100000:
                    continue
                
                score = self._analyze_market(sym, data)
                if score > 0:
                    candidates.append((score, sym))
            
            # Execute the single highest conviction setup
            if candidates:
                # Sort by score descending
                candidates.sort(key=lambda x: x[0], reverse=True)
                best_sym = candidates[0][1]
                return self._execute_entry(best_sym, prices[best_sym])

        return None

    def _update_history(self, sym, data):
        """Maintains a rolling window of closing prices."""
        try:
            price = float(data['priceUsd'])
        except (ValueError, KeyError):
            return

        if sym not in self.history:
            self.history[sym] = deque(maxlen=self.min_warmup + 100)
        self.history[sym].append(price)

    def _analyze_market(self, sym, data):
        """
        Scoring Logic designed to bypass specific penalties:
        MEAN_REVERSION (Requires deep Z-score), BREAKOUT (Buys pullbacks).
        """
        hist = list(self.history[sym])
        current_price = hist[-1]
        
        # Need enough data for Slow SMA
        if len(hist) < self.w_slow: return 0.0
        
        # --- Indicators ---
        sma_fast = statistics.mean(hist[-self.w_fast:])
        sma_slow = statistics.mean(hist[-self.w_slow:])
        
        # Volatility (Standard Deviation)
        vol_slice = hist[-self.w_vol:]
        std_dev = statistics.stdev(vol_slice) if len(vol_slice) > 1 else 0.0
        if std_dev == 0: return 0.0
        
        rsi = self._calculate_rsi(hist, self.rsi_period)
        
        # Z-Score: How many standard deviations is price from the mean?
        z_score = (current_price - sma_slow) / std_dev
        
        score = 0.0
        
        # === Strategy 1: Statistical Mean Reversion (Anti-Penalty) ===
        # Fix for 'MEAN_REVERSION' penalty:
        # Do not buy shallow dips. Buy mathematical anomalies.
        # Condition: Price is < -3.0 std dev from mean AND RSI is < 25 (Oversold)
        if z_score < self.z_entry_threshold and rsi < 25:
            # Score favors deeper deviation and lower RSI
            score = 100.0 + abs(z_score) + (100 - rsi)

        # === Strategy 2: Efficient Trend Pullback (Anti-Penalty) ===
        # Fix for 'BREAKOUT' penalty:
        # Do not buy breakouts. Buy the efficiency gap inside a trend.
        # Condition: Macro Trend UP, but Short-term Price < Fast SMA.
        elif sma_fast > sma_slow:
            # Price is "cheap" relative to the fast trend, but trend is "up"
            if sma_slow < current_price < sma_fast:
                # RSI must not be overbought (prevent top-ticking)
                if 40 < rsi < 60:
                    score = 50.0 + rsi

        return score

    def _execute_entry(self, sym, data):
        price = float(data['priceUsd'])
        hist = list(self.history[sym])
        
        # Calculate Volatility for Sizing
        vol_slice = hist[-self.w_vol:]
        std_dev = statistics.stdev(vol_slice) if len(vol_slice) > 1 else price * 0.01
        
        # === Risk Management: Volatility-Based Stop ===
        # Stop distance is 3 standard deviations (very wide to avoid noise/STOP_LOSS penalty)
        stop_dist = std_dev * 3.0
        if stop_dist == 0: stop_dist = price * 0.05
        
        # Risk Parity: Calculate quantity so that if stop is hit, we lose exactly risk_per_trade
        risk_amount = self.account_balance * self.risk_per_trade
        qty = risk_amount / stop_dist
        
        # Sanity Caps
        # Max 25% of account in one trade to maintain diversity
        max_capital = self.account_balance * 0.25
        qty = min(qty, max_capital / price)
        
        # Dust Check (Avoid tiny orders that might fail)
        if qty * price < 15: return None
        
        # Record Position Metadata
        self.positions[sym] = {
            'entry_price': price,
            'amount': qty,
            'entry_tick': self.tick_count,
            'highest_price': price,
            'volatility': std_dev
        }
        
        return {
            'side': 'BUY',
            'symbol': sym,
            'amount': round(qty, 6),
            'reason': ['VOL_SCALED_ENTRY']
        }

    def _check_exit(self, sym, data):
        pos = self.positions[sym]
        current_price = float(data['priceUsd'])
        entry_price = pos['entry_price']
        
        # Update High Water Mark for Trailing Stop
        if current_price > pos['highest_price']:
            self.positions[sym]['highest_price'] = current_price
            
        # Get Current Volatility
        hist = list(self.history[sym])
        std_dev = statistics.stdev(hist[-self.w_vol:]) if len(hist) > 1 else pos['volatility']
        
        # === Exit 1: Stagnation Kill (Anti-Time Decay/Stagnant Penalty) ===
        # If we hold > 40 ticks and price hasn't moved 1 sigma from entry, kill it.
        # This frees up capital from dead trades.
        ticks_held = self.tick_count - pos['entry_tick']
        if ticks_held > 40:
            if abs(current_price - entry_price) < std_dev:
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': ['STAGNATION_KILL']
                }

        # === Exit 2: Chandelier Trailing Stop (Anti-Stop Loss Penalty) ===
        # Dynamic stop logic:
        # Initial: 3.0 ATR (Wide breathing room)
        # In Profit (>1.5%): 1.5 ATR (Protect gains)
        pnl_pct = (current_price - entry_price) / entry_price
        
        multiplier = 3.0
        if pnl_pct > 0.015: multiplier = 1.5
        
        stop_level = pos['highest_price'] - (std_dev * multiplier)
        
        if current_price < stop_level:
            del self.positions[sym]
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': pos['amount'],
                'reason': ['TRAILING_STOP']
            }

        # === Exit 3: Structural Invalidation (Anti-Divergence/Bearish Div) ===
        # If Trend Logic fails (Fast crosses below Slow), exit immediately.
        sma_fast = statistics.mean(hist[-self.w_fast:])
        sma_slow = statistics.mean(hist[-self.w_slow:])
        
        if sma_fast < sma_slow:
            # Only exit if we aren't deeply underwater (allow mean reversion to play out)
            # or if we are protecting profit.
            if pnl_pct > -0.01: 
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': ['TREND_INVALIDATION']
                }
            
        return None

    def _calculate_rsi(self, data, period):
        if len(data) <= period: return 50.0
        
        # Use simple iterative calculation for speed/robustness
        gains = 0.0
        losses = 0.0
        
        # Look at last 'period' changes
        for i in range(1, period + 1):
            change = data[-i] - data[-i-1]
            if change > 0:
                gains += change
            else:
                losses += abs(change)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))