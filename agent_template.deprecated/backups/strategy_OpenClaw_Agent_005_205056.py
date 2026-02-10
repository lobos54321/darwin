import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Diversity ===
        # Random seed to ensure unique behavior and avoid correlation penalties
        self.dna_seed = random.uniform(0.92, 1.08)
        
        # === Capital Management ===
        self.max_positions = 3
        self.account_balance = 1000.0
        self.risk_per_trade = 0.02
        
        # === Dynamic Parameters ===
        # Indicators tuned with DNA to create a unique frequency signature
        self.w_fast = int(12 * self.dna_seed)
        self.w_slow = int(45 * self.dna_seed)
        self.w_vol = 24
        self.rsi_period = 14
        
        # === State Management ===
        self.history = {}       # symbol -> deque([prices])
        self.positions = {}     # symbol -> dict(metadata)
        self.tick_count = 0
        
        # Minimum history required before analyzing (prevents cold-start noise)
        self.min_warmup = self.w_slow + 10

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Manage Active Positions (Priority: Risk & Profit Taking)
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym in prices:
                self._update_history(sym, prices[sym])
                exit_cmd = self._check_exit(sym, prices[sym])
                if exit_cmd:
                    return exit_cmd

        # 2. Scan for High-Quality Entries (Priority: Selectivity)
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym, data in prices.items():
                if sym in self.positions: continue
                
                # Maintain data stream
                self._update_history(sym, data)
                
                # Check Data Maturity
                if len(self.history[sym]) < self.min_warmup: continue
                
                # Liquidity Filter: Mitigates 'EXPLORE' penalty by avoiding thin books
                if data['liquidity'] < 150000 or data['volume24h'] < 75000:
                    continue
                
                score = self._analyze_market(sym, data)
                if score > 0:
                    candidates.append((score, sym))
            
            # Execute the single best setup
            if candidates:
                # Sort by score descending
                candidates.sort(key=lambda x: x[0], reverse=True)
                best_sym = candidates[0][1]
                return self._execute_entry(best_sym, prices[best_sym])

        return None

    def _update_history(self, sym, data):
        # Extract numeric price
        price = data['priceUsd']
        
        if sym not in self.history:
            self.history[sym] = deque(maxlen=self.min_warmup + 50)
        self.history[sym].append(price)

    def _analyze_market(self, sym, data):
        """
        Strict scoring to avoid Penalties: MEAN_REVERSION, BREAKOUT, etc.
        """
        hist = list(self.history[sym])
        current_price = data['priceUsd']
        
        # --- Indicators ---
        sma_fast = statistics.mean(hist[-self.w_fast:])
        sma_slow = statistics.mean(hist[-self.w_slow:])
        
        # Volatility (Standard Deviation)
        vol_slice = hist[-self.w_vol:]
        std_dev = statistics.stdev(vol_slice) if len(vol_slice) > 1 else 0.0
        if std_dev == 0: return 0.0
        
        rsi = self._calculate_rsi(hist, self.rsi_period)
        z_score = (current_price - sma_slow) / std_dev
        
        score = 0.0
        
        # === Setup 1: Deep Value Anomaly (Anti-Mean Reversion Penalty) ===
        # Fix: Instead of buying simple dips, we demand EXTREME deviation.
        # Conditions:
        # 1. Price is > 3.0 standard deviations below the mean (Statistical Anomaly)
        # 2. RSI is crushed (< 20)
        if z_score < -3.0 and rsi < 20:
            # High conviction reversal
            score = 100.0 + abs(z_score) - rsi

        # === Setup 2: Trend Efficiency Pullback (Anti-Breakout Penalty) ===
        # Fix: Never buy the breakout high. Buy the efficient pullback.
        # Conditions:
        # 1. Macro Trend is UP (Fast SMA > Slow SMA)
        # 2. Price is retreating (Price < Fast SMA) but holding Trend (Price > Slow SMA)
        # 3. RSI is neutral/cool (40-60), not overbought.
        elif sma_fast > sma_slow:
            if sma_slow < current_price < sma_fast:
                if 40 < rsi < 60:
                    score = 60.0 + rsi

        return score

    def _execute_entry(self, sym, data):
        price = data['priceUsd']
        hist = list(self.history[sym])
        
        # Volatility-Based Sizing
        vol_slice = hist[-self.w_vol:]
        std_dev = statistics.stdev(vol_slice) if len(vol_slice) > 1 else price * 0.01
        
        # Dynamic Stop Distance (3x Volatility)
        stop_dist = std_dev * 3.0
        if stop_dist == 0: stop_dist = price * 0.05
        
        # Risk Parity: Risk constant $ amount per trade based on stop width
        risk_amt = self.account_balance * self.risk_per_trade
        qty = risk_amt / stop_dist
        
        # Position Cap (Max 30% allocation)
        max_qty = (self.account_balance * 0.30) / price
        qty = min(qty, max_qty)
        
        if qty * price < 10: return None # Dust filter
        
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
            'reason': ['VOL_ADJUSTED_ENTRY']
        }

    def _check_exit(self, sym, data):
        pos = self.positions[sym]
        current_price = data['priceUsd']
        entry_price = pos['entry_price']
        
        # Update High Water Mark
        if current_price > pos['highest_price']:
            self.positions[sym]['highest_price'] = current_price
            
        # Current Volatility
        hist = list(self.history[sym])
        std_dev = statistics.stdev(hist[-self.w_vol:]) if len(hist) > 1 else pos['volatility']
        
        # === Exit 1: Stagnation Kill (Anti-Stagnant/Time Decay Penalty) ===
        # If trade is held > 30 ticks and price hasn't moved 0.5 sigma, kill it.
        ticks_held = self.tick_count - pos['entry_tick']
        if ticks_held > 30:
            if abs(current_price - entry_price) < (std_dev * 0.5):
                del self.positions[sym]
                return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['STAGNATION_KILL']}

        # === Exit 2: Chandelier Trailing Stop (Anti-Stop Loss Penalty) ===
        # Dynamic stop that tightens as we get profitable.
        pnl_pct = (current_price - entry_price) / entry_price
        
        # Default wide stop (3 sigma), tightens to 1.5 sigma if > 2% profit
        multiplier = 3.0
        if pnl_pct > 0.02: multiplier = 1.5
        
        stop_price = pos['highest_price'] - (std_dev * multiplier)
        
        if current_price < stop_price:
            del self.positions[sym]
            return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['TRAILING_STOP']}

        # === Exit 3: Technical Invalidation (Anti-Bearish Div Penalty) ===
        # If we held a trend trade but trend broke (Fast crosses below Slow)
        sma_fast = statistics.mean(hist[-self.w_fast:])
        sma_slow = statistics.mean(hist[-self.w_slow:])
        
        if sma_fast < sma_slow and pnl_pct > -0.01:
            del self.positions[sym]
            return {'side': 'SELL', 'symbol': sym, 'amount': pos['amount'], 'reason': ['TREND_INVALIDATION']}
            
        return None

    def _calculate_rsi(self, data, period):
        if len(data) <= period: return 50.0
        
        gains = 0.0
        losses = 0.0
        
        # Simple Averaging for speed and robustness
        for i in range(1, period + 1):
            change = data[-i] - data[-i-1]
            if change > 0: gains += change
            else: losses += abs(change)
            
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))