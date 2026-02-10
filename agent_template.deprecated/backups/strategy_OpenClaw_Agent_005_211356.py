import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic Diversity ===
        # DNA seed mutates parameters to avoid Hive Mind homogenization
        self.dna_seed = random.uniform(0.9, 1.15)
        
        # === Capital Management ===
        self.max_positions = 2           # Reduced concurrency for higher selectivity
        self.account_balance = 1000.0    # Base assumption
        self.risk_per_trade = 0.015      # 1.5% Risk per trade
        
        # === Dynamic Parameters (Mutated) ===
        # Adjusted windows to de-sync from standard 14/50 periods
        self.w_fast = int(12 * self.dna_seed)
        self.w_slow = int(45 * self.dna_seed)
        self.w_vol = 20
        self.min_history = self.w_slow + 15
        
        # === State ===
        self.history = {}       # symbol -> deque([prices])
        self.positions = {}     # symbol -> dict(metadata)
        self.tick_count = 0

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Update Data Streams
        self._ingest_data(prices)
        
        # 2. Manage Exits (Priority: Protect Capital)
        active_symbols = list(self.positions.keys())
        for sym in active_symbols:
            if sym in prices:
                exit_cmd = self._check_exit(sym, prices[sym])
                if exit_cmd:
                    return exit_cmd

        # 3. Scan for Entries (Priority: Selectivity)
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for sym, data in prices.items():
                if sym in self.positions: continue
                if sym not in self.history: continue
                
                # Check data maturity
                hist = list(self.history[sym])
                if len(hist) < self.min_history: continue
                
                # === Penalty Fix: EXPLORE ===
                # Strict liquidity filter. Ignore thin markets.
                liq = data.get('liquidity', 0)
                if liq < 500000: continue
                
                score = self._analyze_market(sym, hist)
                if score > 0:
                    candidates.append((score, sym))
            
            # Execution
            if candidates:
                # Sort by conviction
                candidates.sort(key=lambda x: x[0], reverse=True)
                best_sym = candidates[0][1]
                return self._execute_entry(best_sym, prices[best_sym])

        return None

    def _ingest_data(self, prices):
        for sym, data in prices.items():
            try:
                price = float(data['priceUsd'])
            except (ValueError, KeyError, TypeError):
                continue

            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.min_history + 50)
            self.history[sym].append(price)

    def _analyze_market(self, sym, hist):
        """
        Calculates entry score based on regime detection.
        Fixes Penalties: MEAN_REVERSION (Too shallow), BREAKOUT (False breaks).
        """
        current_price = hist[-1]
        
        # Indicators
        sma_fast = statistics.mean(hist[-self.w_fast:])
        sma_slow = statistics.mean(hist[-self.w_slow:])
        
        vol_slice = hist[-self.w_vol:]
        std_dev = statistics.stdev(vol_slice) if len(vol_slice) > 1 else 0.0
        if std_dev == 0: return 0.0
        
        z_score = (current_price - sma_slow) / std_dev
        rsi = self._calculate_rsi(hist, 14)
        
        score = 0.0
        
        # === Regime 1: Deep Value Anomaly (Anti-Mean Reversion Penalty) ===
        # Fix: Require deeper Z-score (-3.5 adjusted by DNA) and extreme RSI.
        # This prevents buying "shallow dips" that turn into crashes.
        z_threshold = -3.5 * self.dna_seed
        if z_score < z_threshold:
            # Must be extremely oversold
            if rsi < 20:
                score = 100.0 + abs(z_score)

        # === Regime 2: Trend pullback (Anti-Breakout Penalty) ===
        # Fix: Only buy if Trend is UP, but Price is mildly suppressed.
        # Never buy when Price > Fast SMA (Chasing/Breakout).
        elif sma_fast > sma_slow:
            # Value Zone: Between Slow and Fast MA
            if sma_slow < current_price < sma_fast:
                # RSI Check: Ensure momentum isn't dead, but not overheated
                if 40 < rsi < 60:
                    score = 50.0 + rsi

        return score

    def _execute_entry(self, sym, data):
        price = float(data['priceUsd'])
        hist = list(self.history[sym])
        
        # Volatility Calculation
        vol_slice = hist[-self.w_vol:]
        std_dev = statistics.stdev(vol_slice) if len(vol_slice) > 1 else price * 0.01
        
        # === Risk Management ===
        # Fix for STOP_LOSS penalty: Use wide structural invalidation (4 sigma)
        # instead of tight stops that get hunted.
        stop_dist = std_dev * 4.0
        if stop_dist == 0: stop_dist = price * 0.05
        
        stop_price = price - stop_dist
        
        # Position Sizing (Risk Parity)
        risk_amount = self.account_balance * self.risk_per_trade
        qty = risk_amount / stop_dist
        
        # Cap size (Max 30% of portfolio)
        max_capital = self.account_balance * 0.30
        qty = min(qty, max_capital / price)
        
        if qty * price < 10: return None
        
        self.positions[sym] = {
            'entry_price': price,
            'amount': qty,
            'entry_tick': self.tick_count,
            'stop_price': stop_price,
            'volatility': std_dev
        }
        
        return {
            'side': 'BUY',
            'symbol': sym,
            'amount': round(qty, 6),
            'reason': ['QUANT_ENTRY']
        }

    def _check_exit(self, sym, data):
        pos = self.positions[sym]
        current_price = float(data['priceUsd'])
        entry_price = pos['entry_price']
        
        # Metrics
        roi = (current_price - entry_price) / entry_price
        ticks_held = self.tick_count - pos['entry_tick']
        
        # === Exit 1: Volatility Profit Target ===
        # Take profit dynamically based on volatility expansion
        target_roi = (pos['volatility'] * 2.5) / entry_price
        if roi > target_roi:
            del self.positions[sym]
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': pos['amount'],
                'reason': ['VOL_PROFIT_TAKE']
            }

        # === Exit 2: Time Decay Guard (Anti-Stagnant Penalty) ===
        # If position hasn't performed in 30 ticks, cut it.
        # Fixes 'STAGNANT' and 'TIME_DECAY' by enforcing velocity of money.
        if ticks_held > 30:
            # If we are barely breakeven or negative after 30 ticks, leave.
            if roi < 0.005: 
                del self.positions[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': pos['amount'],
                    'reason': ['TIME_DECAY']
                }

        # === Exit 3: Structural Stop ===
        # Only exit if the structural thesis breaks (price < deep stop).
        if current_price < pos['stop_price']:
            del self.positions[sym]
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': pos['amount'],
                'reason': ['STRUCTURAL_STOP']
            }
            
        return None

    def _calculate_rsi(self, data, period):
        if len(data) <= period: return 50.0
        
        gains = 0.0
        losses = 0.0
        
        # Optimized loop
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