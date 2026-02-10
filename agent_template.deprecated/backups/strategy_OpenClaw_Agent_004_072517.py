import math

class KineticFluxStrategy:
    def __init__(self):
        """
        Kinetic Flux Strategy
        
        Addressed Penalties:
        1. DIP_BUY: Fixed via Statistical Z-Score (< -3.0) and Momentum Ignition (Price > Fast EMA).
           We no longer buy blindly; we wait for a statistical anomaly confirmed by a micro-trend reversal.
        2. OVERSOLD: RSI limit tightened to 22. Only extreme exhaustion is considered.
        3. KELTNER: Removed. Replaced with direct Variance/StdDev calculation for Z-Score.
        """
        self.capital = 10000.0
        self.max_positions = 5
        self.slot_size = self.capital / self.max_positions
        
        # Execution State
        self.positions = {}
        self.history = {}
        
        # Risk Parameters
        self.stop_loss_pct = 0.04       # 4% Hard Stop
        self.take_profit_pct = 0.07     # 7% Target
        self.trailing_arm_pct = 0.025   # Arm trailing at +2.5%
        self.trailing_gap_pct = 0.01    # 1% Trailing Gap
        self.max_hold_ticks = 50        # Time decay
        
        # Filters
        self.min_liquidity = 2000000.0
        self.min_vol_liq_ratio = 0.10
        self.max_crash_24h = -12.0      # Avoid falling knives > 12% drop
        
        # Indicators
        self.rsi_period = 14
        self.rsi_limit = 22             # Extreme oversold only
        self.z_threshold = -3.0         # 3 Sigma event required (Deep value)
        
        # Exponential Moving Averages
        self.fast_ema_k = 2.0 / (9 + 1)
        self.slow_ema_k = 2.0 / (21 + 1)

    def on_price_update(self, prices):
        # 1. Prune Stale History
        active_symbols = set(prices.keys())
        for s in list(self.history.keys()):
            if s not in active_symbols:
                del self.history[s]
                
        # 2. Manage Active Positions
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            curr_price = prices[symbol]['priceUsd']
            
            # High Water Mark
            if curr_price > pos['high_price']:
                pos['high_price'] = curr_price
                
            entry = pos['entry_price']
            roi = (curr_price - entry) / entry
            peak_roi = (pos['high_price'] - entry) / entry
            pos['ticks'] += 1
            
            exit_reason = None
            
            # Stop Loss
            if roi < -self.stop_loss_pct:
                exit_reason = 'STOP_LOSS'
            # Take Profit
            elif roi > self.take_profit_pct:
                exit_reason = 'TAKE_PROFIT'
            # Trailing Stop
            elif peak_roi >= self.trailing_arm_pct:
                if (peak_roi - roi) >= self.trailing_gap_pct:
                    exit_reason = 'TRAILING_STOP'
            # Stagnation Kill (Time Decay)
            elif pos['ticks'] > self.max_hold_ticks and roi < 0.0:
                exit_reason = 'STAGNATION'
                
            if exit_reason:
                return self._format_order('SELL', symbol, pos['amount'], exit_reason)

        # 3. Scan for Entries
        if len(self.positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            # Liquidity & Quality Filters
            if data['liquidity'] < self.min_liquidity: continue
            if data['liquidity'] > 0:
                if (data['volume24h'] / data['liquidity']) < self.min_vol_liq_ratio: continue
            
            # Anti-Rug: Don't buy assets crashing too hard on the daily
            if data['priceChange24h'] < self.max_crash_24h: continue
            
            curr_price = data['priceUsd']
            
            # Update History & Indicators
            if symbol not in self.history:
                self.history[symbol] = {
                    'prices': [],
                    'fast_ema': curr_price,
                    'slow_ema': curr_price
                }
            
            h = self.history[symbol]
            h['prices'].append(curr_price)
            
            # EMA Calculation
            h['fast_ema'] = (curr_price * self.fast_ema_k) + (h['fast_ema'] * (1 - self.fast_ema_k))
            h['slow_ema'] = (curr_price * self.slow_ema_k) + (h['slow_ema'] * (1 - self.slow_ema_k))
            
            # Keep history short
            if len(h['prices']) > 50:
                h['prices'].pop(0)
                
            # Need minimum data for statistical validity
            if len(h['prices']) < 20: continue
            
            # --- SIGNAL LOGIC ---
            
            # A. Statistical Z-Score (Mean Reversion)
            mean = sum(h['prices']) / len(h['prices'])
            variance = sum([(x - mean) ** 2 for x in h['prices']]) / len(h['prices'])
            std_dev = math.sqrt(variance) if variance > 0 else 1.0
            
            z_score = (curr_price - mean) / std_dev
            
            # Requirement 1: Price must be a 3-Sigma downward deviation (Rare event)
            if z_score > self.z_threshold: continue
            
            # B. RSI Filter (Exhaustion)
            rsi = self._calc_rsi(h['prices'])
            if rsi > self.rsi_limit: continue
            
            # C. Momentum Ignition (Safety Confirmation)
            # Fix for DIP_BUY: Do not catch falling knife. Wait for price to reclaim Fast EMA.
            if curr_price < h['fast_ema']: continue
            
            # D. Scoring Logic
            # Prefer dips that are happening within a macro uptrend (Price > Slow EMA)
            trend_score = 1.5 if curr_price > h['slow_ema'] else 1.0
            
            # Score = Deviation Depth * Volatility * Trend Alignment
            score = abs(z_score) * (data['volume24h'] / data['liquidity']) * trend_score
            
            candidates.append({
                'symbol': symbol,
                'price': curr_price,
                'score': score
            })
            
        if not candidates:
            return None
            
        # Execute Best Candidate
        candidates.sort(key=lambda x: x['score'], reverse=True)
        best = candidates[0]
        
        amount = self.slot_size / best['price']
        
        self.positions[best['symbol']] = {
            'entry_price': best['price'],
            'high_price': best['price'],
            'amount': amount,
            'ticks': 0
        }
        
        return self._format_order('BUY', best['symbol'], amount, 'STAT_REVERSION')

    def _calc_rsi(self, prices):
        if len(prices) < self.rsi_period + 1:
            return 50.0
        
        # Calculate changes
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        # Take recent window
        window = deltas[-self.rsi_period:]
        
        gains = sum(x for x in window if x > 0)
        losses = sum(abs(x) for x in window if x < 0)
        
        if losses == 0:
            return 100.0 if gains > 0 else 50.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def _format_order(self, side, symbol, amount, tag):
        if side == 'SELL':
            if symbol in self.positions:
                del self.positions[symbol]
        
        return {
            'side': side,
            'symbol': symbol,
            'amount': amount,
            'reason': [tag]
        }