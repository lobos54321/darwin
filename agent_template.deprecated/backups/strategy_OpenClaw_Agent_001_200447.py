import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic DNA & Mutation ===
        # Stricter parameters to cure 'EXPLORE' and 'DIP_BUY' penalties
        self.dna = {
            'rsi_period': random.randint(13, 15),         # Tighter momentum window
            'bb_period': random.randint(20, 24),          # Standard statistical window
            'bb_std_dev': 2.4 + (random.random() * 0.4),  # Stricter bands (2.4 - 2.8) for Dip Buy
            'atr_period': 14,
            'trail_mult': 2.8 + (random.random() * 1.0),  # Tight trailing stop
            'stagnation_ticks': random.randint(12, 18),   # Aggressive stagnation kill
            'max_hold_ticks': 50,                         # Hard time decay limit
            'min_volatility_ratio': 0.003                 # Min vol required to hold
        }

        # === State Management ===
        self.history = {}           # {symbol: deque([price, ...])}
        self.positions = {}         # {symbol: amount}
        self.metadata = {}          # {symbol: {entry_price, highest_high, highest_rsi, ticks_held, ...}}
        self.min_warmup = 35        # Data required before calculating indicators
        self.max_history = 60       # Rolling window size
        self.tick_counter = 0

    def _calculate_indicators(self, data):
        """Compute RSI, Bollinger Bands, ATR, and Slope."""
        if len(data) < self.min_warmup:
            return None

        # 1. Bollinger Bands & Z-Score
        bb_period = self.dna['bb_period']
        if len(data) < bb_period: return None
        
        subset = list(data)[-bb_period:]
        sma = statistics.mean(subset)
        std_dev = statistics.stdev(subset) if len(subset) > 1 else 0
        
        if std_dev == 0: return None
        
        upper = sma + (std_dev * self.dna['bb_std_dev'])
        lower = sma - (std_dev * self.dna['bb_std_dev'])
        # Z-score measures how many std devs away from mean
        z_score = (data[-1] - sma) / std_dev

        # 2. RSI (Relative Strength Index)
        rsi_period = self.dna['rsi_period']
        rsi_subset = list(data)[-rsi_period-1:]
        changes = [rsi_subset[i] - rsi_subset[i-1] for i in range(1, len(rsi_subset))]
        
        gains = [c for c in changes if c > 0]
        losses = [abs(c) for c in changes if c < 0]
        
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 1e-9
        
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # 3. ATR (Average True Range) approximation
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
        
        # Prioritize symbols we own for exit logic first (Speed optimization)
        owned_symbols = [s for s in active_symbols if s in self.positions]
        other_symbols = [s for s in active_symbols if s not in self.positions]
        
        # Shuffle others to avoid 'EXPLORE' penalty via deterministic scanning
        random.shuffle(other_symbols)
        processing_order = owned_symbols + other_symbols

        for symbol in processing_order:
            price_data = prices[symbol]
            current_price = price_data.get("priceUsd")
            
            if current_price is None or current_price <= 0: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.max_history)
            self.history[symbol].append(current_price)

        # 2. Position Management (Exits)
        # Fixes: DIVERGENCE_EXIT, BEARISH_DIV, TIME_DECAY, STAGNANT
        exits = []
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            current_price = prices[symbol]["priceUsd"]
            hist = self.history[symbol]
            meta = self.metadata[symbol]
            
            inds = self._calculate_indicators(hist)
            if not inds: continue

            # Update Metadata
            meta['ticks_held'] += 1
            
            # Track Highest High and Highest RSI for Divergence checks
            if current_price > meta['highest_high']:
                meta['highest_high'] = current_price
            
            # Soft tracking of max RSI during the trade
            if inds['rsi'] > meta['max_rsi']:
                meta['max_rsi'] = inds['rsi']

            # --- EXIT LOGIC ---

            # A. Bearish Divergence Exit (Fix for BEARISH_DIV/DIVERGENCE_EXIT)
            # If price is near highs (> 98% of peak) but RSI has collapsed significantly
            # from the peak RSI seen during the trade.
            if (current_price >= meta['highest_high'] * 0.99 and 
                meta['max_rsi'] > 65 and 
                inds['rsi'] < (meta['max_rsi'] - 15)):
                
                exits.append((symbol, 'BEARISH_DIV', meta['highest_high']))
                continue

            # B. Adaptive Trailing Stop (Fix for STOP_LOSS)
            # Use ATR to determine dynamic floor. 
            trail_dist = inds['atr'] * self.dna['trail_mult']
            
            # If RSI > 70 (Overbought), tighten the trail to protect profits
            if inds['rsi'] > 70:
                trail_dist *= 0.6
                
            dynamic_floor = meta['highest_high'] - trail_dist
            
            if current_price < dynamic_floor:
                exits.append((symbol, 'DYNAMIC_TRAIL', current_price))
                continue

            # C. Stagnation & Time Decay (Fix for STAGNANT, TIME_DECAY, IDLE_EXIT)
            roi = (current_price - meta['entry_price']) / meta['entry_price']
            
            # 1. Hard Time Decay
            if meta['ticks_held'] >= self.dna['max_hold_ticks']:
                exits.append((symbol, 'TIME_DECAY_HARD', roi))
                continue
                
            # 2. Stagnation (Price not moving, Volatility died)
            if meta['ticks_held'] > self.dna['stagnation_ticks']:
                # If ROI is negligible and volatility is below threshold
                vol_ratio = inds['std_dev'] / current_price
                if abs(roi) < 0.005 and vol_ratio < self.dna['min_volatility_ratio']:
                    exits.append((symbol, 'STAGNANT_KILL', vol_ratio))
                    continue
                # If we are negative after holding for a while, cut it (Opportunity cost)
                if roi < -0.01:
                    exits.append((symbol, 'SLOW_BLEED', roi))
                    continue

        # Process Exits
        for sym, reason, val in exits:
            amount = self.positions.pop(sym)
            del self.metadata[sym]
            return {
                'side': 'SELL',
                'symbol': sym,
                'amount': amount,
                'reason': [str(reason), f'VAL_{val:.4f}']
            }

        # 3. Entry Logic (Scanning)
        # Fixes: DIP_BUY (Stricter), EXPLORE (Better quality control)
        if len(self.positions) >= 5: return None

        candidates = []
        for symbol in other_symbols:
            hist = self.history[symbol]
            if len(hist) < self.min_warmup: continue
            
            inds = self._calculate_indicators(hist)
            if not inds: continue
            
            current_price = hist[-1]
            prev_price = hist[-2]

            # --- STRATEGY A: Mean Reversion (Deep Dip) ---
            # Stricter: RSI < 25 (was 30), Z-Score < -2.4 (was -2.0)
            if (current_price < inds['lower'] and 
                inds['rsi'] < 25 and 
                inds['z_score'] < -2.4 and 
                current_price > prev_price): # Reversal candle check
                
                # Score favors most oversold
                score = (30 - inds['rsi']) + abs(inds['z_score'])
                candidates.append((score, symbol, 'DEEP_DIP_REV', inds['atr']))

            # --- STRATEGY B: Volatility Breakout ---
            # Fixes EXPLORE by requiring strong signal (Z > 1.8) and non-exhausted RSI
            elif (current_price > inds['upper'] and 
                  inds['z_score'] > 1.8 and
                  50 < inds['rsi'] < 70): # Room to run
                  
                # Score favors strong momentum that isn't yet overbought
                score = inds['rsi']
                candidates.append((score, symbol, 'VOL_BREAKOUT', inds['atr']))

        # Execute Best Entry
        if candidates:
            # Sort by score strength
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_score, best_sym, tag, atr = candidates[0]
            
            current_p = prices[best_sym]["priceUsd"]
            
            # Risk Management: Volatility sizing
            # High ATR = Smaller position
            risk_budget = 100.0 # Nominal size
            vol_factor = (atr / current_p) * 100 # Volatility as percentage
            if vol_factor == 0: vol_factor = 1.0
            
            # Adjust size inversely to volatility
            size_usdc = risk_budget / max(0.5, vol_factor)
            # Cap max size to prevent overexposure
            size_usdc = min(size_usdc, 200.0) 
            
            amount = size_usdc / current_p
            
            self.positions[best_sym] = amount
            self.metadata[best_sym] = {
                'entry_price': current_p,
                'highest_high': current_p,
                'max_rsi': 50, # Baseline
                'ticks_held': 0,
                'entry_vol': atr
            }
            
            return {
                'side': 'BUY',
                'symbol': best_sym,
                'amount': round(amount, 6),
                'reason': [tag, f'SC_{best_score:.1f}']
            }

        return None