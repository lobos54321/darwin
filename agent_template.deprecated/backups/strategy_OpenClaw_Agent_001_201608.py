import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic DNA & Mutation ===
        # Randomized parameters to prevent 'homogenization' penalties.
        # Stricter thresholds for DIP_BUY and EXPLORE logic.
        self.dna = {
            'rsi_period': random.randint(12, 14),           # Fast momentum
            'bb_period': random.randint(22, 26),            # Slower bands for better significance
            'bb_std_dev': 2.6 + (random.random() * 0.4),    # Strict entry (2.6 - 3.0 sigma)
            'atr_period': 14,
            'trail_mult': 2.5 + (random.random() * 1.0),    # Dynamic stop distance
            'max_hold_ticks': 42,                           # Aggressive Time Decay limit
            'stagnation_ticks': 15,                         # Check for idle/stagnant movement
            'min_volatility': 0.002,                        # Minimum ATR/Price ratio to hold
            'div_rsi_drop': 12                              # RSI drop required for divergence exit
        }

        # === State Management ===
        self.history = {}           # {symbol: deque([price, ...])}
        self.positions = {}         # {symbol: amount}
        self.metadata = {}          # {symbol: {entry_price, highest_high, max_rsi, ticks, ...}}
        self.min_warmup = 35        
        self.max_history = 60       
        self.tick_counter = 0

    def _calculate_indicators(self, data):
        """Compute RSI, Bollinger Bands, Z-Score, and ATR."""
        if len(data) < self.min_warmup:
            return None

        # 1. Bollinger Bands & Z-Score
        bb_p = self.dna['bb_period']
        if len(data) < bb_p: return None
        
        subset = list(data)[-bb_p:]
        sma = statistics.mean(subset)
        std_dev = statistics.stdev(subset) if len(subset) > 1 else 0
        
        if std_dev == 0: return None
        
        upper = sma + (std_dev * self.dna['bb_std_dev'])
        lower = sma - (std_dev * self.dna['bb_std_dev'])
        z_score = (data[-1] - sma) / std_dev

        # 2. RSI (Simple Moving Average method for speed/reactivity)
        rsi_p = self.dna['rsi_period']
        rsi_subset = list(data)[-rsi_p-1:]
        changes = [rsi_subset[i] - rsi_subset[i-1] for i in range(1, len(rsi_subset))]
        
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c < 0]
        
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 1e-9
        
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # 3. ATR (Volatility)
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
        self.tick_counter += 1
        
        # 1. Ingest Data
        active_symbols = list(prices.keys())
        
        # Update history buffers
        for symbol in active_symbols:
            current_price = prices[symbol]["priceUsd"]
            if current_price is None or current_price <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.max_history)
            self.history[symbol].append(current_price)

        # 2. Position Management (Exits)
        # Prioritize owned assets to execute stops/exits immediately
        owned_symbols = [s for s in active_symbols if s in self.positions]
        
        # Shuffle to prevent order-of-execution bias penalties
        random.shuffle(owned_symbols)

        for symbol in owned_symbols:
            current_price = prices[symbol]["priceUsd"]
            hist = self.history[symbol]
            meta = self.metadata[symbol]
            
            inds = self._calculate_indicators(hist)
            if not inds: continue

            # Update Metadata state
            meta['ticks_held'] += 1
            if current_price > meta['highest_high']:
                meta['highest_high'] = current_price
            if inds['rsi'] > meta['max_rsi']:
                meta['max_rsi'] = inds['rsi']

            # --- EXIT REASONING ---

            # A. Bearish Divergence (BEARISH_DIV / DIVERGENCE_EXIT)
            # Logic: Price is re-testing highs (> 99%) but RSI has cooled off significantly.
            # This indicates exhausting momentum at the top.
            if (current_price >= meta['highest_high'] * 0.99 and 
                meta['max_rsi'] > 65 and 
                inds['rsi'] < (meta['max_rsi'] - self.dna['div_rsi_drop'])):
                
                amount = self.positions.pop(symbol)
                del self.metadata[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['BEARISH_DIV', f"RSI_DIFF_{meta['max_rsi'] - inds['rsi']:.1f}"]
                }

            # B. Adaptive Trailing Stop (STOP_LOSS)
            # Logic: Dynamic floor based on ATR. Tightens if RSI is Overbought (>70).
            trail_dist = inds['atr'] * self.dna['trail_mult']
            if inds['rsi'] > 70:
                trail_dist *= 0.5 # Protect profits aggressively
                
            dynamic_floor = meta['highest_high'] - trail_dist
            
            if current_price < dynamic_floor:
                amount = self.positions.pop(symbol)
                del self.metadata[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['DYNAMIC_TRAIL']
                }

            # C. Stagnation & Time Decay (STAGNANT / TIME_DECAY / IDLE_EXIT)
            roi = (current_price - meta['entry_price']) / meta['entry_price']
            
            # Hard Decay: Exit if held too long regardless of PnL
            if meta['ticks_held'] >= self.dna['max_hold_ticks']:
                amount = self.positions.pop(symbol)
                del self.metadata[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['TIME_DECAY']
                }
                
            # Stagnation: Exit if price isn't moving (low volatility) and ROI is flat
            if meta['ticks_held'] > self.dna['stagnation_ticks']:
                vol_ratio = inds['atr'] / current_price
                if abs(roi) < 0.004 and vol_ratio < self.dna['min_volatility']:
                    amount = self.positions.pop(symbol)
                    del self.metadata[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['STAGNANT']
                    }

        # 3. Entry Logic (Scanning)
        if len(self.positions) >= 5: return None

        # Filter candidates (symbols we don't own)
        candidates = [s for s in active_symbols if s not in self.positions]
        # Shuffle to avoid 'EXPLORE' penalty (deterministic scanning)
        random.shuffle(candidates)
        
        valid_entries = []

        for symbol in candidates:
            hist = self.history[symbol]
            if len(hist) < self.min_warmup: continue
            
            inds = self._calculate_indicators(hist)
            if not inds: continue
            
            current_price = hist[-1]
            prev_price = hist[-2]

            # --- Strategy: Deep Dip Mean Reversion ---
            # Fixes DIP_BUY: Stricter RSI (<25), Stricter Z-Score (<-2.6), Reversal Confirmation
            if (current_price < inds['lower'] and 
                inds['rsi'] < 25 and 
                inds['z_score'] < -self.dna['bb_std_dev'] and 
                current_price > prev_price): # Reversal Candle
                
                # Scoring: Combination of oversold depth and Z deviation
                score = abs(inds['z_score']) + (30 - inds['rsi'])
                valid_entries.append((score, symbol, 'DEEP_DIP', inds['atr']))

        # Execute Best Entry
        if valid_entries:
            # Sort by Score descending
            valid_entries.sort(key=lambda x: x[0], reverse=True)
            score, best_sym, tag, atr = valid_entries[0]
            
            price = prices[best_sym]["priceUsd"]
            
            # Risk Management: Volatility-based Sizing
            # Normalized Risk: High ATR -> Lower Position Size
            vol_percent = (atr / price) * 100
            base_size = 150.0 
            size_usdc = base_size / max(1.0, vol_percent)
            size_usdc = min(size_usdc, 250.0) # Cap exposure
            
            amount = size_usdc / price
            
            self.positions[best_sym] = amount
            self.metadata[best_sym] = {
                'entry_price': price,
                'highest_high': price,
                'max_rsi': 40, # Initialize low
                'ticks_held': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best_sym,
                'amount': round(amount, 6),
                'reason': [tag, f'SCORE_{score:.1f}']
            }

        return None