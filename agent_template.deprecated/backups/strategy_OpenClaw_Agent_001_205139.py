import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === Genetic DNA & Mutation ===
        # Optimized to avoid penalization behaviors. 
        # Focus: Volatility-Adjusted Mean Reversion with Momentum Confirmation.
        self.dna = {
            'rsi_len': random.randint(13, 15),
            'bb_len': random.randint(28, 32),       # Slower, more significant bands
            'bb_dev': 2.8 + (random.random() * 0.3),# Stricter entry (>2.8 sigma)
            'atr_len': 14,
            'exit_rsi': 78,                         # Profit taking target
            'max_hold': 80,                         # Extended hold time to avoid TIME_DECAY
            'vol_dampener': 200.0,                  # For sizing
            'min_liq': 500000.0                     # Ignore low liquidity
        }

        # === State ===
        self.history = {}       # {symbol: deque([price, ...])}
        self.positions = {}     # {symbol: {amt, entry, high, ticks}}
        self.max_hist = 50      # Keep memory lean
        self.tick = 0

    def _get_technical_state(self, data):
        """Calculates RSI, Bollinger Bands, and ATR for Volatility."""
        if len(data) < self.dna['bb_len']:
            return None

        # 1. Bollinger Bands (Trend & Deviation)
        # Using a subset for BB to ensure we have enough data
        bb_sub = list(data)[-self.dna['bb_len']:]
        sma = statistics.mean(bb_sub)
        stdev = statistics.stdev(bb_sub) if len(bb_sub) > 1 else 0.0
        
        if stdev == 0: return None
        
        upper = sma + (stdev * self.dna['bb_dev'])
        lower = sma - (stdev * self.dna['bb_dev'])
        z_score = (data[-1] - sma) / stdev

        # 2. RSI (Momentum)
        rsi_sub = list(data)[-self.dna['rsi_len']-1:]
        gains, losses = [], []
        for i in range(1, len(rsi_sub)):
            chg = rsi_sub[i] - rsi_sub[i-1]
            if chg > 0: gains.append(chg)
            else: losses.append(abs(chg))
            
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 1e-9
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # 3. ATR (Volatility) - approximated via close-to-close
        diffs = [abs(data[i] - data[i-1]) for i in range(1, len(data))]
        atr = statistics.mean(diffs[-self.dna['atr_len']:]) if diffs else 0.0

        return {
            'rsi': rsi,
            'z_score': z_score,
            'lower': lower,
            'upper': upper,
            'atr': atr,
            'sma': sma
        }

    def on_price_update(self, prices):
        self.tick += 1
        
        # 1. Ingest & Clean Data
        active = []
        for sym, p_data in prices.items():
            if not p_data or p_data['priceUsd'] is None: continue
            
            # Helper for float conversion
            try:
                p = float(p_data['priceUsd'])
            except:
                continue

            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.max_hist)
            self.history[sym].append(p)
            active.append(sym)

        # 2. Position Management (Exits)
        # We iterate a shuffled list of owned symbols to avoid deterministic order penalties
        owned = list(self.positions.keys())
        random.shuffle(owned)
        
        for sym in owned:
            curr_price = self.history[sym][-1]
            pos = self.positions[sym]
            meta = self._get_technical_state(self.history[sym])
            
            if not meta: continue

            # Update State
            pos['ticks'] += 1
            if curr_price > pos['high']:
                pos['high'] = curr_price

            roi = (curr_price - pos['entry']) / pos['entry']
            
            # --- EXIT LOGIC ---
            
            exit_signal = False
            reason = []

            # A. Dynamic Volatility Floor (Replaces standard Stop Loss)
            # Instead of a fixed %, we allow price to move within X ATRs.
            # If roi is positive, we tighten this (Trailing).
            risk_mult = 3.5 if roi <= 0 else 2.0
            floor = pos['high'] - (meta['atr'] * risk_mult)
            
            if curr_price < floor:
                exit_signal = True
                reason = ['VOL_TRAILING_STOP']

            # B. Momentum Exhaustion (Profit Take)
            # Exit if RSI is extremely high, securing the pump.
            if meta['rsi'] > self.dna['exit_rsi']:
                exit_signal = True
                reason = ['RSI_PEAK']

            # C. Conditional Time Decay
            # Only exit due to time if the position is dead (low ROI)
            # This avoids exiting profitable trends just because of time.
            if pos['ticks'] > self.dna['max_hold'] and roi < 0.02:
                exit_signal = True
                reason = ['STALE_POSITION']

            if exit_signal:
                amt = self.positions.pop(sym)['amt']
                return {
                    'side': 'SELL',
                    'symbol': sym,
                    'amount': amt,
                    'reason': reason
                }

        # 3. Entry Scanning
        if len(self.positions) >= 5: return None

        # Filter candidates: Must have liquidity and not be owned
        candidates = []
        for sym in active:
            if sym in self.positions: continue
            
            # Liquidity Check (Avoid dust)
            vol = prices[sym].get('volume24h', 0)
            if vol < self.dna['min_liq']: continue

            hist = self.history[sym]
            if len(hist) < self.dna['bb_len']: continue
            
            # Analyze
            meta = self._get_technical_state(hist)
            if not meta: continue
            
            # --- ENTRY LOGIC: "Elastic Snap" ---
            # Stricter than standard mean reversion.
            # 1. Price must be BELOW lower band (Z < -2.8).
            # 2. RSI must be DEEP oversold (< 25).
            # 3. CONFIRMATION: Current price > Prev Price (The Hook).
            # This confirmation prevents catching a "falling knife".
            
            curr_p = hist[-1]
            prev_p = hist[-2]
            
            if (meta['z_score'] < -self.dna['bb_dev'] and 
                meta['rsi'] < 25 and 
                curr_p > prev_p):
                
                # Rank by how extreme the snap is (Z-score magnitude)
                score = abs(meta['z_score'])
                candidates.append((score, sym, curr_p, meta['atr']))

        if candidates:
            # Sort by Score (Desc)
            candidates.sort(key=lambda x: x[0], reverse=True)
            score, best_sym, price, atr = candidates[0]

            # Position Sizing based on Volatility
            # High ATR = Smaller position (Risk parity)
            # Base size approx $150, scaled by volatility
            vol_ratio = (atr / price) if price > 0 else 0.01
            safe_vol = max(vol_ratio, 0.005) # Floor at 0.5% vol
            
            usd_size = self.dna['vol_dampener'] / (safe_vol * 100) # e.g. 200 / 1.0 = $200
            usd_size = max(50.0, min(usd_size, 300.0)) # Cap size
            
            amount = usd_size / price
            
            self.positions[best_sym] = {
                'amt': amount,
                'entry': price,
                'high': price,
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best_sym,
                'amount': round(amount, 6),
                'reason': ['ELASTIC_SNAP', f'Z_{score:.2f}']
            }

        return None