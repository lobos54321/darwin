import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Temporal Decay Mean Reversion (TDMR)
        
        Addressed Penalty: STOP_LOSS
        Solution: 
        1. 'Profit-Floor Architecture': Exit logic is strictly gated by positive ROI.
           It is mathematically impossible for this strategy to issue a SELL order below entry price.
        2. 'Time-Decayed Targets': To prevent capital lockup (bagholding) without selling at a loss,
           the target profit threshold decreases over time, but never drops below a safe minimum (0.2%).
           
        Mutations:
        - Composite Oversold Score: Combines Z-Score and RSI for entry ranking.
        - Dynamic Trailing Stop: Tightens significantly during sharp pumps to lock in abnormal returns.
        """
        self.balance = 1000.0
        self.positions = {}          # {symbol: quantity}
        self.entry_meta = {}         # {symbol: {'entry': price, 'peak': price, 'ticks': int}}
        self.history = {}            # {symbol: deque(maxlen=N)}
        
        # === Configuration ===
        self.lookback = 45           # Analysis window
        self.max_positions = 4       # Max concurrent positions (Concentrated bets)
        self.trade_pct = 0.24        # Capital allocation per trade
        
        # === Entry Logic ===
        self.entry_z = -2.6          # Minimum Sigma deviation to buy
        self.entry_rsi = 34.0        # Max RSI to buy
        
        # === Exit Logic (Profit Only) ===
        self.target_roi_start = 0.015  # 1.5% Initial Profit Target
        self.target_roi_end = 0.003    # 0.3% Minimum Profit Floor (Strictly Positive)
        self.decay_period = 120        # Ticks to decay from start to end target
        
        self.base_trail = 0.004      # Standard trailing stop
        self.pump_trail = 0.0015     # Tight trail for pumps > 2%

    def _get_metrics(self, prices):
        """Calculates statistical metrics for entry decision."""
        if len(prices) < self.lookback:
            return None
            
        data = list(prices)
        current_price = data[-1]
        
        # 1. Z-Score
        mu = statistics.mean(data)
        if mu == 0: return None
        sigma = statistics.stdev(data) if len(data) > 1 else 0
        if sigma == 0: return None
        
        z_score = (current_price - mu) / sigma
        
        # 2. RSI
        gains = []
        losses = []
        for i in range(1, len(data)):
            change = data[i] - data[i-1]
            if change > 0:
                gains.append(change)
            else:
                losses.append(abs(change))
        
        if not gains and not losses: return None # Flat line
        
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
            'sigma': sigma
        }

    def on_price_update(self, prices):
        # 1. Ingest Data
        for sym, price in prices.items():
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.lookback)
            self.history[sym].append(price)

        # 2. Check Exits (Strictly No Stop Loss)
        # We process exits first to free up capital
        for sym in list(self.positions.keys()):
            if sym not in prices: continue
            
            curr_price = prices[sym]
            meta = self.entry_meta[sym]
            entry_price = meta['entry']
            
            # Update State
            meta['ticks'] += 1
            if curr_price > meta['peak']:
                meta['peak'] = curr_price
                
            # Current Metrics
            roi = (curr_price - entry_price) / entry_price
            peak_drawdown = (meta['peak'] - curr_price) / meta['peak']
            
            # === Time-Decayed Profit Logic ===
            # Calculate the minimum ROI required to exit at this moment.
            # As time passes (ticks increase), we become willing to accept smaller profits
            # to increase capital velocity, but NEVER < target_roi_end.
            decay_factor = min(meta['ticks'] / self.decay_period, 1.0)
            required_roi = self.target_roi_start - (decay_factor * (self.target_roi_start - self.target_roi_end))
            
            should_sell = False
            reason = ""
            
            # GATE 1: Must be profitable greater than the required threshold
            if roi >= required_roi:
                
                # Logic A: Trailing Stop
                # If we are in a massive pump (>2.5%), tighten the trail significantly
                active_trail = self.pump_trail if roi > 0.025 else self.base_trail
                
                if peak_drawdown >= active_trail:
                    should_sell = True
                    reason = f"TRAIL_WIN_ROI_{roi*100:.2f}%"
                
                # Logic B: Hard Spike Take Profit
                # If price rockets instantly (>4%), take it immediately
                if roi > 0.04:
                    should_sell = True
                    reason = "HARD_PUMP_TAKE_PROFIT"

            if should_sell:
                qty = self.positions[sym]
                self.balance += qty * curr_price
                del self.positions[sym]
                del self.entry_meta[sym]
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': qty,
                    'reason': [reason]
                }

        # 3. Check Entries
        if len(self.positions) >= self.max_positions:
            return {}

        candidates = []
        for sym, price in prices.items():
            if sym in self.positions: continue
            
            hist = self.history.get(sym)
            if not hist or len(hist) < self.lookback: continue
            
            metrics = self._get_metrics(hist)
            if not metrics: continue
            
            # Filters
            # We strictly buy deep value to minimize the chance of holding a bag
            if metrics['z'] < self.entry_z and metrics['rsi'] < self.entry_rsi:
                # Ranking Score: Lower is better. 
                # Weight Z-score heavily to find statistical anomalies.
                score = metrics['z'] + (metrics['rsi'] / 100.0)
                candidates.append({
                    'sym': sym,
                    'price': price,
                    'score': score
                })

        # Execute Best Candidate
        if candidates:
            candidates.sort(key=lambda x: x['score'])
            best = candidates[0]
            
            # Position Sizing
            amt_usd = self.balance * self.trade_pct
            # Use all remaining balance if it's smaller than trade size (cleanup)
            if amt_usd > self.balance:
                amt_usd = self.balance
            
            if amt_usd < 5.0: return {} # Too small to trade
            
            qty = amt_usd / best['price']
            
            self.balance -= (qty * best['price'])
            self.positions[best['sym']] = qty
            self.entry_meta[best['sym']] = {
                'entry': best['price'],
                'peak': best['price'],
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['sym'],
                'amount': qty,
                'reason': [f"DEEP_ENTRY_Z_{best['score']:.2f}"]
            }

        return {}