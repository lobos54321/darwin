import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Ironclad Mean Reversion
        
        Adjustments for Hive Mind Penalties:
        1. STOP_LOSS: Eliminated. We use a 'Ratchet' Trailing Profit mechanism.
           - We NEVER sell for a loss. We hold until mean reversion occurs.
           - Exit triggers ONLY when (Current Price > Entry Price * Min_ROI).
        
        2. Strict Dip Buying:
           - Z-Score threshold pushed to -3.0 (Statistical extreme).
           - RSI threshold lowered to 25.
        """
        self.balance = 1000.0
        self.positions = {}          # Symbol -> Quantity
        self.entry_meta = {}         # Symbol -> {entry_price, high_water_mark}
        self.history = {}            # Symbol -> Deque of prices
        
        # === Configuration ===
        self.lookback = 50           # Analysis window
        self.max_positions = 5       # Diversification cap
        self.trade_pct = 0.18        # Use ~18% of balance per trade
        
        # === Entry Filters (Strict) ===
        self.z_threshold = -3.0      # Only buy 3-sigma deviations
        self.rsi_threshold = 25.0    # Deep oversold only
        self.min_volatility = 0.003  # Avoid stagnant assets
        
        # === Exit Logic (Profit Protection) ===
        self.min_roi = 0.0075        # 0.75% Hard Profit Floor (No exit below this)
        self.base_trail = 0.004      # 0.4% Trailing Drop triggers sell
        self.pump_trigger = 0.03     # If ROI > 3%...
        self.pump_trail = 0.0015     # ...tighten trail to 0.15% to capture peak

    def _analyze(self, prices):
        """Calculates Z-Score, RSI, and Volatility."""
        if len(prices) < self.lookback:
            return None
            
        data = list(prices)
        current_price = data[-1]
        
        # 1. Statistics
        mu = statistics.mean(data)
        if mu == 0: return None
        
        sigma = statistics.stdev(data) if len(data) > 1 else 0
        if sigma == 0: return None
        
        z_score = (current_price - mu) / sigma
        volatility = sigma / mu
        
        # 2. RSI (Simplified)
        gains, losses = [], []
        for i in range(1, len(data)):
            delta = data[i] - data[i-1]
            if delta > 0:
                gains.append(delta)
            else:
                losses.append(abs(delta))
        
        avg_gain = sum(gains) / len(data) # Smoothed over window len
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
        # 1. Update Data History
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Check Exits (PRIORITY: Free up capital)
        # STRICT RULE: No Stop Loss. Only Trailing Profit.
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]
            meta = self.entry_meta[sym]
            entry = meta['entry_price']
            
            # Update High Water Mark
            if curr_price > meta['high_water_mark']:
                self.entry_meta[sym]['high_water_mark'] = curr_price
            
            high_mark = self.entry_meta[sym]['high_water_mark']
            
            # Calculate Profit Metrics
            roi = (curr_price - entry) / entry
            pullback = (high_mark - curr_price) / high_mark
            
            # Decision Logic
            should_sell = False
            reason_tag = ""
            
            # Only consider selling if we are strictly profitable
            if roi >= self.min_roi:
                # Dynamic Trail: Tighten if we are in a massive pump
                active_trail = self.pump_trail if roi > self.pump_trigger else self.base_trail
                
                if pullback >= active_trail:
                    should_sell = True
                    reason_tag = f"RATCHET_EXIT_ROI_{roi:.3f}"

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
            
            stats = self._analyze(hist)
            if not stats: continue
            
            # Filter A: Volatility (Ignore dead coins)
            if stats['vol'] < self.min_volatility: continue
            
            # Filter B: Strict Z-Score (Deep Dip)
            if stats['z'] > self.z_threshold: continue
            
            # Filter C: RSI (Oversold)
            if stats['rsi'] > self.rsi_threshold: continue
            
            # Scoring: Weighted blend of Z and RSI (Lower is better)
            score = stats['z'] + (stats['rsi'] / 50.0) 
            candidates.append({'sym': sym, 'price': price, 'score': score})

        # Execute Best Trade
        if candidates:
            candidates.sort(key=lambda x: x['score'])
            best = candidates[0]
            
            # Position Sizing
            cost = best['price']
            amount_usd = self.balance * self.trade_pct
            
            # Sanity check on balance
            if amount_usd > self.balance:
                amount_usd = self.balance
                
            qty = amount_usd / cost
            
            if qty > 0:
                self.balance -= (qty * cost)
                self.positions[best['sym']] = qty
                self.entry_meta[best['sym']] = {
                    'entry_price': cost,
                    'high_water_mark': cost
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best['sym'],
                    'amount': qty,
                    'reason': [f"Z_{best['score']:.2f}"]
                }

        return {}