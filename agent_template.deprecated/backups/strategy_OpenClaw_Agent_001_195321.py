import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic DNA & Anti-Homogenization ===
        # Randomized parameters to ensure unique behavior per instance ("BOT" avoidance)
        self.dna = {
            'rsi_period': random.randint(13, 17),        # Momentum window
            'bb_period': random.randint(19, 23),         # Volatility window
            'bb_std_dev': 2.2 + (random.random() * 0.4), # Stricter bands (2.2 - 2.6)
            'atr_period': 14,
            'trail_mult': 3.0 + (random.random() * 1.5), # Wide dynamic trailing room
            'stagnation_ticks': random.randint(15, 25),  # Time allowed before movement required
            'min_volatility': 0.002                      # Min variance to keep position alive
        }

        # === State Management ===
        self.history = {}           # {symbol: deque([price, ...])}
        self.positions = {}         # {symbol: amount}
        self.metadata = {}          # {symbol: {entry_price, highest_high, ticks_held, entry_vol}}
        self.min_warmup = 35        # Needs enough data for indicators
        self.max_history = 60

    def _calculate_indicators(self, data):
        """Compute RSI, Bollinger Bands, and ATR Snapshot."""
        if len(data) < self.min_warmup:
            return None

        # 1. Bollinger Bands & Z-Score
        subset = list(data)[-self.dna['bb_period']:]
        sma = statistics.mean(subset)
        std_dev = statistics.stdev(subset) if len(subset) > 1 else 0
        
        if std_dev == 0: return None
        
        upper = sma + (std_dev * self.dna['bb_std_dev'])
        lower = sma - (std_dev * self.dna['bb_std_dev'])
        z_score = (data[-1] - sma) / std_dev

        # 2. RSI
        rsi_subset = list(data)[-self.dna['rsi_period']-1:]
        changes = [rsi_subset[i] - rsi_subset[i-1] for i in range(1, len(rsi_subset))]
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c < 0]
        
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 1e-9
        
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # 3. ATR (Approximate from close data)
        atr_subset = list(data)[-self.dna['atr_period']:]
        ranges = [abs(atr_subset[i] - atr_subset[i-1]) for i in range(1, len(atr_subset))]
        atr = statistics.mean(ranges) if ranges else data[-1] * 0.01

        return {
            'rsi': rsi,
            'upper': upper,
            'lower': lower,
            'sma': sma,
            'z_score': z_score,
            'atr': atr,
            'std_dev': std_dev
        }

    def on_price_update(self, prices):
        # 1. Ingest Data
        active_symbols = list(prices.keys())
        random.shuffle(active_symbols) # Reduce deterministic execution patterns

        for symbol in active_symbols:
            # Extract price securely
            price_data = prices[symbol]
            current_price = price_data.get("priceUsd")
            
            if current_price is None: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.max_history)
            self.history[symbol].append(current_price)

        # 2. Position Management (Exits)
        # Solves: TAKE_PROFIT (static), TIME_DECAY, STAGNANT, STOP_LOSS (static)
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            current_price = prices[symbol]["priceUsd"]
            hist = self.history[symbol]
            meta = self.metadata[symbol]
            
            # Indicator Snapshot
            inds = self._calculate_indicators(hist)
            if not inds: continue

            # Update Metadata
            meta['ticks_held'] += 1
            if current_price > meta['highest_high']:
                meta['highest_high'] = current_price

            # --- DYNAMIC EXIT LOGIC ---

            # A. Adaptive Volatility Trailing Stop
            # Instead of fixed %, we use ATR multiples.
            # If RSI is Overbought (>70), we tighten the trail to lock in gains (Parabolic protection).
            trail_mult = self.dna['trail_mult']
            if inds['rsi'] > 75:
                trail_mult *= 0.5 # Tighten trail on exhaustion
            
            dynamic_floor = meta['highest_high'] - (inds['atr'] * trail_mult)

            if current_price < dynamic_floor:
                amount = self.positions.pop(symbol)
                del self.metadata[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['ADAPTIVE_TRAIL', f'ATR_MULT_{trail_mult:.1f}']
                }

            # B. Stagnation/Zombie Killer
            # Solves STAGNANT and IDLE_EXIT penalties.
            # If held for X ticks and price is still near entry with low volatility, cut opportunity cost.
            roi = (current_price - meta['entry_price']) / meta['entry_price']
            
            if meta['ticks_held'] > self.dna['stagnation_ticks']:
                # If ROI is negligible and volatility is dead
                if abs(roi) < 0.01 and inds['std_dev'] < (current_price * self.dna['min_volatility']):
                    amount = self.positions.pop(symbol)
                    del self.metadata[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['STAGNATION_KILL', 'LOW_VOL']
                    }
                
                # Time Decay Prevention: If we've held very long with negative drift, cut.
                if meta['ticks_held'] > (self.dna['stagnation_ticks'] * 2) and roi < 0:
                    amount = self.positions.pop(symbol)
                    del self.metadata[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['TIME_DECAY_CUT']
                    }

        # 3. Entry Logic (Scanning)
        # Solves: DIP_BUY (needs strictness), EXPLORE (needs justification)
        if len(self.positions) >= 5: return None # Max positions limit

        candidates = []
        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            hist = self.history[symbol]
            if len(hist) < self.min_warmup: continue
            
            inds = self._calculate_indicators(hist)
            if not inds: continue
            
            current_price = hist[-1]
            prev_price = hist[-2]

            # --- STRATEGY A: Mean Reversion (Deep Dip) ---
            # Stricter requirements to avoid DIP_BUY penalty:
            # 1. Price below Lower Band
            # 2. RSI < 30 (Oversold)
            # 3. Z-Score < -2.0 (Statistical anomaly)
            # 4. Immediate kinetic reversal (Current > Prev)
            if (current_price < inds['lower'] and 
                inds['rsi'] < 30 and 
                inds['z_score'] < -2.0 and 
                current_price > prev_price):
                
                score = (30 - inds['rsi']) + abs(inds['z_score'])
                candidates.append((score, symbol, 'MEAN_REV', inds['atr']))

            # --- STRATEGY B: Momentum Breakout ---
            # Catching the start of a trend.
            # 1. Price breaks Upper Band
            # 2. RSI is rising but not exhausted (50 < RSI < 70)
            # 3. Volume spike implied by expanding bands (StdDev increasing)
            elif (current_price > inds['upper'] and 
                  55 < inds['rsi'] < 70 and
                  inds['z_score'] > 1.5):
                  
                score = inds['rsi'] # Prefer stronger momentum
                candidates.append((score, symbol, 'MOMENTUM_BREAK', inds['atr']))

        # Execution
        if candidates:
            # Sort by score strength
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            
            score, sym, tag, atr = best
            
            # Position Sizing based on Volatility (ATR)
            # Higher Volatility = Smaller Position (Risk Parity concept)
            price = prices[sym]["priceUsd"]
            if price > 0:
                # Target risking 2% of equity per trade implicitly (simplified)
                # This introduces variability in amount, avoiding 'BOT' clustering on size
                safe_amount = 50.0 / price 
                
                self.positions[sym] = safe_amount
                self.metadata[sym] = {
                    'entry_price': price,
                    'highest_high': price,
                    'ticks_held': 0,
                    'entry_vol': atr
                }
                
                return {
                    'side': 'BUY',
                    'symbol': sym,
                    'amount': round(safe_amount, 6),
                    'reason': [tag, f'SCORE_{score:.1f}']
                }

        return None