import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Deep Sigma Liquidity Provider (Time-decay Exit)
        
        Improvements:
        1. STRICTER_ENTRIES: Z-Score threshold lowered to -3.8 (was -3.5) and RSI to < 25.
           This ensures we only buy significant liquidity voids, reducing false positives.
        2. NO_STOP_LOSS: Explicitly removed any price-based stop logic. 
           We rely solely on 'Alpha Decay' (Time Limit) and 'Mean Reversion' (Take Profit).
        3. ANTI_HOMOGENIZATION: Randomized lookback windows and thresholds to avoid 
           clustering with other bots on the same ticks.
        """
        
        self.dna = {
            # Entry Logic: High Sigma + Low RSI (Stricter than before)
            'z_entry_threshold': -3.8 - (random.random() * 0.4), # Entry around -3.8 to -4.2
            'rsi_limit': 22.0 + (random.random() * 5.0),         # RSI max 22-27
            'volatility_window': 50 + int(random.random() * 10), # Lookback 50-60 ticks
            
            # Exit Logic: Time & Reversion
            'max_hold_ticks': 200 + int(random.random() * 100),  # Hold for ~200-300 ticks (Alpha Decay)
            'tp_z_threshold': 0.0,                               # Exit when price hits mean (Z=0)
            'min_roi_trigger': 0.02,                             # Secondary TP: 2% instant profit
            
            # Risk Management
            'risk_per_trade': 0.06,                              # 6% per trade
            'max_positions': 5,
            'cooldown_base': 15
        }

        self.history = {}       # symbol -> deque
        self.positions = {}     # symbol -> dict state
        self.cooldowns = {}     # symbol -> int ticks
        self.balance = 1000.0   # Virtual balance
        
        # Buffer safety
        self.min_req_history = self.dna['volatility_window'] + 5

    def on_price_update(self, prices):
        """
        Core logic loop called on every tick.
        """
        active_symbols = list(prices.keys())
        current_prices_map = {}
        
        # 1. Ingest Data
        for symbol in active_symbols:
            p_data = prices[symbol]
            # robust price parsing
            price = p_data if isinstance(p_data, (int, float)) else p_data.get("priceUsd", 0)
            price = float(price)
            
            if price <= 0: continue
            current_prices_map[symbol] = price
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.dna['volatility_window'] + 20)
            self.history[symbol].append(price)
            
            # Manage Cooldowns
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]

        # 2. Manage Exits (Priority over Entries)
        # Check positions for Mean Reversion (Profit) or Alpha Decay (Time)
        # Randomize iteration order
        open_positions = list(self.positions.keys())
        random.shuffle(open_positions)
        
        for symbol in open_positions:
            if symbol not in current_prices_map: continue
            
            pos = self.positions[symbol]
            current_price = current_prices_map[symbol]
            pos['ticks'] += 1
            
            # Calc current Z-score relative to entry mean
            # This tells us if price has reverted to the mean we identified at entry
            dist = current_price - pos['entry_mean']
            current_z = dist / pos['entry_std'] if pos['entry_std'] > 0 else 0
            
            roi = (current_price - pos['entry_price']) / pos['entry_price']
            
            # EXIT A: Mean Reversion (Take Profit)
            if current_z >= self.dna['tp_z_threshold']:
                self._close_position(symbol, self.dna['cooldown_base'])
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['MEAN_REV', f"Z:{current_z:.2f}"]
                }
                
            # EXIT B: Hard ROI Target (Take Profit)
            if roi >= self.dna['min_roi_trigger']:
                self._close_position(symbol, self.dna['cooldown_base'])
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['ROI_TARGET', f"{roi*100:.1f}%"]
                }
            
            # EXIT C: Alpha Decay (Time Expiry)
            # We assume the signal is invalid if it hasn't worked by now.
            # STRICTLY TIME BASED. NO PRICE BASED STOP LOSS.
            if pos['ticks'] > self.dna['max_hold_ticks']:
                # Longer cooldown if we failed to capture value
                self._close_position(symbol, self.dna['cooldown_base'] * 3)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['TIME_EXPIRY', f"Ticks:{pos['ticks']}"]
                }

        # 3. Scan for Entries
        if len(self.positions) >= self.dna['max_positions']:
            return None

        random.shuffle(active_symbols)
        best_setup = None
        best_score = 0.0

        for symbol in active_symbols:
            if symbol in self.positions: continue
            if symbol in self.cooldowns: continue
            if len(self.history.get(symbol, [])) < self.min_req_history: continue
            
            score, stats = self._analyze_market(symbol)
            
            # Score > 0 indicates valid entry criteria met
            if score > 0 and score > best_score:
                best_score = score
                best_setup = (symbol, stats)

        if best_setup:
            symbol, stats = best_setup
            current_price = current_prices_map[symbol]
            
            # Position Sizing
            usd_size = self.balance * self.dna['risk_per_trade']
            # Cap at 20% of balance max
            usd_size = min(usd_size, self.balance * 0.2)
            amount = usd_size / current_price
            
            self.positions[symbol] = {
                'entry_price': current_price,
                'amount': amount,
                'entry_mean': stats['mean'],
                'entry_std': stats['std'],
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': symbol,
                'amount': round(amount, 8),
                'reason': ['DEEP_SIGMA', f"Z:{stats['z']:.2f}", f"RSI:{int(stats['rsi'])}"]
            }

        return None

    def _analyze_market(self, symbol):
        """
        Returns (score, stats). Score > 0 if valid.
        """
        data = self.history[symbol]
        window = self.dna['volatility_window']
        subset = list(data)[-window:]
        
        current_price = subset[-1]
        avg_price = sum(subset) / len(subset)
        variance = sum((x - avg_price) ** 2 for x in subset) / len(subset)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0: return 0.0, None
        
        z_score = (current_price - avg_price) / std_dev
        
        # 1. Z-Score Filter (Stricter)
        if z_score > self.dna['z_entry_threshold']:
            return 0.0, None
            
        # 2. RSI Filter (Stricter)
        rsi = self._calculate_rsi(data, 14)
        if rsi > self.dna['rsi_limit']:
            return 0.0, None
            
        # Score is purely based on depth of anomaly
        score = abs(z_score) + (100 - rsi) / 20.0
        
        return score, {
            'z': z_score,
            'std': std_dev,
            'mean': avg_price,
            'rsi': rsi
        }

    def _close_position(self, symbol, cooldown):
        if symbol in self.positions:
            del self.positions[symbol]
        self.cooldowns[symbol] = cooldown

    def _calculate_rsi(self, history, period):
        if len(history) < period + 1:
            return 50.0
        
        # Simple fast RSI
        prices = list(history)[-(period+1):]
        gains = 0.0
        losses = 0.0
        
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i-1]
            if diff > 0:
                gains += diff
            else:
                losses += abs(diff)
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))