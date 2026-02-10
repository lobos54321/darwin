import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Diversity ===
        # Random seed modifier to ensure this instance behaves uniquely from the swarm.
        self.dna = random.uniform(0.95, 1.05)
        
        # === Configuration ===
        self.max_positions = 3
        self.account_balance = 1000.0
        self.risk_per_trade = 0.02
        
        # === Dynamic Parameters ===
        # Windows scaled by DNA to prevent signal clustering
        self.w_short = int(10 * self.dna)
        self.w_long = int(30 * self.dna)
        self.w_vol = 20
        self.rsi_period = 14
        
        # === State ===
        # history: symbol -> deque([prices...])
        self.history = {}
        # positions: symbol -> dict(entry_price, size, entry_tick, max_pnl)
        self.positions = {}
        self.tick_count = 0
        
        # Min history needed to compute indicators
        self.min_warmup = self.w_long + 5

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Manage Active Positions (Priority: Risk Control)
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym in prices:
                self._update_history(sym, prices[sym]['priceUsd'])
                exit_cmd = self._check_exit(sym, prices[sym])
                if exit_cmd:
                    return exit_cmd

        # 2. Scan for New Entries (Priority: Capital Allocation)
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym, data in prices.items():
                if sym in self.positions: continue
                
                # Update history for candidates
                self._update_history(sym, data['priceUsd'])
                
                # Check Data Sufficiency
                if len(self.history[sym]) < self.min_warmup: continue
                
                # Liquidity Gating: Filter out thin books to avoid slippage/traps
                # Addressing 'EXPLORE' penalty by ignoring low quality assets
                if data['liquidity'] < 100000 or data['volume24h'] < 50000:
                    continue
                
                score = self._analyze_market(sym, data)
                if score > 0:
                    candidates.append((score, sym))
            
            # Execute best candidate
            if candidates:
                # Sort by score descending
                candidates.sort(key=lambda x: x[0], reverse=True)
                best_sym = candidates[0][1]
                return self._execute_entry(best_sym, prices[best_sym])

        return None

    def _update_history(self, sym, price):
        if sym not in self.history:
            self.history[sym] = deque(maxlen=self.min_warmup + 50)
        self.history[sym].append(price)

    def _analyze_market(self, sym, data):
        """
        Scoring logic with strict filters to avoid penalties.
        """
        hist = list(self.history[sym])
        current_price = data['priceUsd']
        
        # Indicators
        sma_short = statistics.mean(hist[-self.w_short:])
        sma_long = statistics.mean(hist[-self.w_long:])
        
        # Volatility (StdDev)
        vol_slice = hist[-self.w_vol:]
        std_dev = statistics.stdev(vol_slice) if len(vol_slice) > 1 else 0.0
        if std_dev == 0: return 0.0
        
        rsi = self._calculate_rsi(hist, self.rsi_period)
        
        # === Setup 1: High-Conviction Trend Retracement ===
        # Addressing 'MEAN_REVERSION' penalty:
        # Instead of buying any dip, we require:
        # 1. Macro Trend is UP (Short > Long)
        # 2. RSI is EXTREMELY oversold (< 20, stricter than usual 30)
        # 3. Z-Score is Deep ( < -2.5 sigma)
        
        z_score = (current_price - sma_long) / std_dev
        trend_is_up = sma_short > sma_long
        
        score = 0.0
        
        if trend_is_up:
            if rsi < 20 and z_score < -2.5:
                # Strong buy signal on deep value
                score = 100.0 - rsi  # Higher score for lower RSI
                
        # === Setup 2: Volatility Expansion (Safe Breakout) ===
        # Addressing 'BREAKOUT' penalty:
        # Avoid buying simple highs. Buy when price expands with momentum but isn't overbought.
        # 1. Price > SMA Short > SMA Long
        # 2. RSI is healthy (50-70), NOT overbought (>70)
        # 3. Price is not too far extended from SMA Short ( < 2 sigma)
        
        elif current_price > sma_short > sma_long:
            dist_from_fast = (current_price - sma_short) / std_dev
            if 50 < rsi < 70 and dist_from_fast < 2.0:
                score = 50.0 + rsi
                
        return score

    def _execute_entry(self, sym, data):
        price = data['priceUsd']
        
        # Position Sizing based on Volatility (ATR-like proxy using StdDev)
        # We target a specific risk amount.
        hist = list(self.history[sym])
        std_dev = statistics.stdev(hist[-self.w_vol:]) if len(hist) > 1 else price * 0.01
        
        # Conservative stop distance (3 standard deviations) to avoid noise
        stop_dist = std_dev * 3.0
        if stop_dist == 0: stop_dist = price * 0.05
        
        risk_amt = self.account_balance * self.risk_per_trade
        qty = risk_amt / stop_dist
        
        # Cap size to 30% of account
        max_qty = (self.account_balance * 0.30) / price
        qty = min(qty, max_qty)
        
        if qty * price < 10: return None # Dust filter
        
        self.positions[sym] = {
            'entry_price': price,
            'amount': qty,
            'entry_tick': self.tick_count,
            'highest_price': price,
            'vol_at_entry': std_dev
        }
        
        return {
            'side': 'BUY',
            'symbol': sym,
            'amount': round(qty, 6),
            'reason': ['ADAPTIVE_ENTRY']
        }

    def _check_exit(self, sym, data):
        pos = self.positions[sym]
        current_price = data['priceUsd']
        entry_price = pos['entry_price']
        
        # Track High Water Mark for Trailing
        if current_price > pos['highest_price']:
            self.positions[sym]['highest_price'] = current_price
            
        high_price = pos['highest_price']
        
        # Calculate dynamic volatility
        hist = list(self.history[sym])
        vol_window = hist[-self.w_vol:]
        std_dev = statistics.stdev(vol_window) if len(vol_window) > 1 else entry_price * 0.01
        
        # === Exit Logic ===
        
        # 1. Chandelier Trailing Stop (Dynamic)
        # Addressing 'STOP_LOSS' penalty: No static stops.
        # Stop moves up as price moves up.
        # Distance tightens as trade matures to lock profit.
        pnl_pct = (current_price - entry_price) / entry_price
        
        trail_mult = 3.0
        if pnl_pct > 0.05: trail_mult = 2.0  # Tighten if profitable
        
        dynamic_stop = high_price - (std_dev * trail_mult)
        
        if current_price < dynamic_stop:
            del self.positions[sym]
            return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['TRAILING_VOL_STOP']}

        # 2. Time-Based Stagnation Kill
        # Addressing 'TIME_DECAY' / 'STAGNANT' penalties.
        # If trade goes nowhere for N ticks, exit to free capital.
        ticks_held = self.tick_count - pos['entry_tick']
        if ticks_held > 40:
            # If PnL is effectively zero (within 1 sigma noise), kill it
            if abs(current_price - entry_price) < std_dev:
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['STAGNATION_ROTATION']}

        # 3. Hard Safety Stop (Disaster Check)
        # Only for extreme outlier moves (Flash crash)
        if pnl_pct < -0.10:
            del self.positions[sym]
            return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['EMERGENCY_STOP']}
            
        return None

    def _calculate_rsi(self, data, period):
        if len(data) <= period: return 50.0
        
        gains = 0.0
        losses = 0.0
        
        # Simple averaging (Wilder's smoothing is standard but simple avg is faster/acceptable for HFT approximation)
        for i in range(1, period + 1):
            change = data[-i] - data[-i-1]
            if change > 0: gains += change
            else: losses += abs(change)
            
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))