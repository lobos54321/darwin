import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Adaptive Volatility Mean Reversion (AVMR)
        
        Mutations from standard approach:
        1. Dynamic Z-Score Threshold: Scaling entry strictness based on asset volatility.
           - High Volatility -> Requires deeper dip (Lower Z-Score) to enter.
           - Low Volatility -> Standard entry.
        2. Ratchet Profit-Only Exit:
           - Explicitly prevents STOP_LOSS behaviors.
           - Only exits when strict minimum profit is secured AND price trails from peak.
        """
        self.balance = 1000.0
        self.positions = {}          # {symbol: quantity}
        self.entry_meta = {}         # {symbol: {'entry': price, 'peak': price}}
        self.history = {}            # {symbol: deque(maxlen=N)}
        
        # === Configuration ===
        self.lookback = 40           # Window for stats
        self.max_positions = 5       # Max concurrent trades
        self.trade_pct = 0.19        # Percent of capital per trade
        
        # === Adaptive Entry Logic ===
        self.base_z = -2.8           # Base Sigma requirement
        self.max_rsi = 32.0          # Max RSI to buy
        
        # === Exit Logic (Profit Locking) ===
        self.min_roi = 0.006         # 0.6% Absolute Min Profit (No exit below this)
        self.base_trail = 0.003      # 0.3% Trailing Drop triggers sell
        self.pump_roi = 0.02         # 2% Pump threshold
        self.pump_trail = 0.001      # Tighten trail to 0.1% during pumps

    def _get_stats(self, prices):
        """Calculates Z-Score, RSI, and Volatility."""
        if len(prices) < self.lookback:
            return None
            
        data = list(prices)
        current_price = data[-1]
        
        # 1. Basic Stats
        mu = statistics.mean(data)
        if mu == 0: return None
        
        sigma = statistics.stdev(data) if len(data) > 1 else 0
        if sigma == 0: return None
        
        z_score = (current_price - mu) / sigma
        volatility = sigma / mu  # Coefficient of Variation
        
        # 2. RSI Calculation
        gains = []
        losses = []
        for i in range(1, len(data)):
            delta = data[i] - data[i-1]
            if delta > 0:
                gains.append(delta)
            else:
                losses.append(abs(delta))
        
        avg_gain = sum(gains) / len(data)
        avg_loss = sum(losses) / len(data)
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        return {
            'z': z_score,
            'rsi': rsi,
            'vol': volatility,
            'price': current_price
        }

    def on_price_update(self, prices):
        # 1. Ingest Data
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Check Exits (Profit Taking Only)
        # We iterate existing positions to check for trailing stop triggers
        # STRICT RULE: ROI must be > min_roi. No Stop Loss allowed.
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]
            meta = self.entry_meta[sym]
            entry_price = meta['entry']
            
            # Update High Water Mark (Peak price since entry)
            if curr_price > meta['peak']:
                self.entry_meta[sym]['peak'] = curr_price
            
            peak_price = self.entry_meta[sym]['peak']
            
            # Metrics
            roi = (curr_price - entry_price) / entry_price
            drawdown = (peak_price - curr_price) / peak_price
            
            should_sell = False
            reason_tag = ""
            
            # Only analyze exit if we are strictly profitable
            if roi >= self.min_roi:
                # Dynamic Trail: If we are deep in profit (pump), tighten the leash
                active_trail = self.pump_trail if roi > self.pump_roi else self.base_trail
                
                if drawdown >= active_trail:
                    should_sell = True
                    reason_tag = f"RATCHET_PROFIT_{roi*100:.2f}%"

            if should_sell:
                qty = self.positions[sym]
                self.balance += qty * curr_price
                del self.positions[sym]
                del self.entry_meta[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': [reason_tag]
                }

        # 3. Check Entries
        if len(self.positions) >= self.max_positions:
            return {}

        candidates = []
        for sym, price in prices.items():
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.lookback: continue
            
            stats = self._get_stats(hist)
            if not stats: continue
            
            # === Mutation: Adaptive Z-Threshold ===
            # If market is volatile, we demand a safer (lower) entry price.
            # Volatility adjustment: -2.8 - (Volatility * 100)
            # e.g., Vol 1% (0.01) -> Threshold becomes -3.8
            adj_z_threshold = self.base_z - (stats['vol'] * 80.0)
            
            # Hard cap to prevent impossible entries
            if adj_z_threshold < -4.5: adj_z_threshold = -4.5

            # Filters
            if stats['z'] < adj_z_threshold and stats['rsi'] < self.max_rsi:
                # Score combines Z-score depth and RSI (Lower is better)
                score = stats['z'] + (stats['rsi'] / 100.0)
                candidates.append({
                    'sym': sym,
                    'price': price,
                    'score': score
                })

        # Execute Best Trade
        if candidates:
            candidates.sort(key=lambda x: x['score'])
            best = candidates[0]
            
            cost = best['price']
            # Position Sizing
            amt_usd = self.balance * self.trade_pct
            if amt_usd > self.balance:
                amt_usd = self.balance
            
            qty = amt_usd / cost
            
            if qty > 0:
                self.balance -= (qty * cost)
                self.positions[best['sym']] = qty
                self.entry_meta[best['sym']] = {
                    'entry': cost,
                    'peak': cost
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best['sym'],
                    'amount': qty,
                    'reason': [f"ADAPTIVE_Z_{best['score']:.2f}"]
                }

        return {}