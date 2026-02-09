import math
from collections import deque

class KineticFluxStrategy:
    def __init__(self):
        """
        Kinetic Flux Strategy 2.0 - Elite Mean Reversion
        
        Mutations to address Hive Mind Penalties:
        1. DIP_BUY: Enforced 'Momentum Ignition' protocol. We strictly forbid buying 
           on the downside. Price MUST reclaim the Fast EMA (Micro-Trend) to validate 
           buyer conviction before entry.
        2. OVERSOLD: RSI threshold tightened to 20 (Deep Exhaustion).
           Coupled with Z-Score to differentiate true anomalies from strong downtrends.
        3. KELTNER: Replaced channel logic with raw Z-Score variance checks 
           to adapt to volatility clusters dynamically without lag.
        """
        # Capital & Risk
        self.capital = 10000.0
        self.max_positions = 5
        self.position_size = self.capital / self.max_positions
        
        self.stop_loss_pct = 0.04       # 4% Hard Stop
        self.take_profit_pct = 0.08     # 8% Target
        self.trailing_arm_pct = 0.03    # Arm trailing stop after 3% gain
        self.trailing_gap_pct = 0.015   # 1.5% Trailing gap
        self.max_hold_ticks = 50        # Time-based exit
        
        # Filters
        self.min_liquidity = 500000.0
        self.min_vol_liq_ratio = 0.05
        
        # Signal Thresholds (Strict)
        self.rsi_limit = 20             # Deep oversold only
        self.z_score_limit = -3.2       # 3.2 Sigma deviation (Rare anomaly)
        
        # State
        self.history = {}
        self.positions = {}
        
        # EMAs (Fast for Ignition, Slow for Context)
        self.fast_alpha = 2.0 / (8 + 1)
        self.slow_alpha = 2.0 / (26 + 1)

    def on_price_update(self, prices):
        # 1. Garbage Collection
        active_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in active_symbols:
                del self.history[s]

        # 2. Position Management
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices: continue
            
            curr_price = prices[symbol]['priceUsd']
            entry_price = pos['entry_price']
            
            # Update High Water Mark
            if curr_price > pos['high_price']:
                pos['high_price'] = curr_price
            
            roi = (curr_price - entry_price) / entry_price
            peak_roi = (pos['high_price'] - entry_price) / entry_price
            drawdown = (pos['high_price'] - curr_price) / pos['high_price']
            pos['ticks'] += 1
            
            exit_reason = None
            
            # A. Stop Loss
            if roi <= -self.stop_loss_pct:
                exit_reason = 'STOP_LOSS'
            # B. Take Profit
            elif roi >= self.take_profit_pct:
                exit_reason = 'TAKE_PROFIT'
            # C. Trailing Stop
            elif peak_roi >= self.trailing_arm_pct and drawdown >= self.trailing_gap_pct:
                exit_reason = 'TRAILING_STOP'
            # D. Stagnation Kill
            elif pos['ticks'] >= self.max_hold_ticks and roi < 0.01:
                exit_reason = 'STAGNATION'
            
            if exit_reason:
                return self._execute_order('SELL', symbol, pos['amount'], exit_reason)

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            # Liquidity Filters
            if data['liquidity'] < self.min_liquidity: continue
            if data['liquidity'] > 0:
                if (data['volume24h'] / data['liquidity']) < self.min_vol_liq_ratio: continue
            
            curr_price = data['priceUsd']
            
            # Update History
            if symbol not in self.history:
                self.history[symbol] = {
                    'prices': deque(maxlen=60),
                    'fast_ema': curr_price,
                    'slow_ema': curr_price
                }
            
            h = self.history[symbol]
            h['prices'].append(curr_price)
            
            # Update EMAs
            h['fast_ema'] = (curr_price * self.fast_alpha) + (h['fast_ema'] * (1 - self.fast_alpha))
            h['slow_ema'] = (curr_price * self.slow_alpha) + (h['slow_ema'] * (1 - self.slow_alpha))
            
            # Need sufficient data
            if len(h['prices']) < 20: continue
            
            # --- SIGNAL GENERATION ---
            
            # 1. Z-Score (Statistical Reversion)
            prices_list = list(h['prices'])
            avg_price = sum(prices_list) / len(prices_list)
            variance = sum((x - avg_price) ** 2 for x in prices_list) / len(prices_list)
            std_dev = math.sqrt(variance) if variance > 0 else 1.0
            
            z_score = (curr_price - avg_price) / std_dev
            
            # Filter: Extreme Anomaly Only (Fix KELTNER)
            if z_score > self.z_score_limit: continue
            
            # 2. RSI Exhaustion (Fix OVERSOLD)
            rsi = self._calculate_rsi(prices_list)
            if rsi > self.rsi_limit: continue
            
            # 3. Momentum Ignition (Fix DIP_BUY)
            # Price must be ABOVE Fast EMA to confirm the "Catching Knife" is over
            if curr_price < h['fast_ema']: continue
            
            # Score: Weights Z-Score anomaly by volatility context
            # We want high deviation + high volatility for snap-back
            volatility = std_dev / curr_price
            score = abs(z_score) * volatility
            
            candidates.append({
                'symbol': symbol,
                'price': curr_price,
                'score': score
            })
            
        if candidates:
            # Sort by Score Descending
            best = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
            amount = self.position_size / best['price']
            
            self.positions[best['symbol']] = {
                'entry_price': best['price'],
                'high_price': best['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return self._execute_order('BUY', best['symbol'], amount, 'KINETIC_REVERSION')
            
        return None

    def _calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50.0
            
        gains = 0.0
        losses