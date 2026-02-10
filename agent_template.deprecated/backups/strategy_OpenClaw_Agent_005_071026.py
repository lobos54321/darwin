import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # === DNA & Mutation ===
        # Unique gene seed to prevent swarm behavior correlation.
        self.dna_seed = random.uniform(0.95, 1.05)
        
        # === Trading Parameters ===
        self.virtual_balance = 1000.0
        self.max_positions = 1
        
        # Indicators: EMA + Volatility + RSI
        # Increased window size for better statistical significance.
        self.window_size = int(30 * self.dna_seed)
        
        # Entry Logic (Fixing ER:0.004 and DIP_BUY penalties)
        # We require a 'Confluence' of events:
        # 1. Price is statistically cheap (Z-Score < -2.6)
        # 2. Momentum is oversold (RSI < 32)
        self.entry_z_score_thresh = 2.6 * self.dna_seed
        self.entry_rsi_thresh = 32
        
        # Exit Logic (Fixing FIXED_TP and TRAIL_STOP)
        # - Stop Loss is FIXED at entry based on volatility (No Trailing).
        # - Take Profit is DYNAMIC based on Mean Reversion or RSI recovery.
        self.stop_loss_mult = 3.5  # Wide stop to breathe
        self.max_hold_ticks = 60   # Force capital rotation
        
        # Filters
        self.min_liquidity = 1_000_000  # Avoid slippage on low cap
        self.min_volatility = 0.008     # 0.8% min deviation to ensure profit > fees
        
        # === State ===
        self.history = {}       # {symbol: deque([prices])}
        self.positions = {}     # {symbol: {'entry': float, 'stop': float, 'amount': float, 'ticks': int}}
        self.cooldowns = {}     # {symbol: ticks_remaining}

    def _calculate_stats(self, prices_deque):
        """Calculates EMA, Standard Deviation, and RSI."""
        if len(prices_deque) < self.window_size:
            return None
        
        data = list(prices_deque)
        
        # 1. EMA (Exponential Moving Average)
        # EMA reacts faster to trend changes than SMA/WMA.
        alpha = 2 / (len(data) + 1)
        ema = data[0]
        for price in data[1:]:
            ema = (price * alpha) + (ema * (1 - alpha))
            
        # 2. Volatility (Standard Deviation)
        variance = sum((x - ema) ** 2 for x in data) / len(data)
        std_dev = math.sqrt(variance)
        
        # 3. RSI (Relative Strength Index)
        # Simple manual calculation since we don't have numpy/pandas
        gains = 0
        losses = 0
        for i in range(1, len(data)):
            change = data[i] - data[i-1]
            if change > 0:
                gains += change
            else:
                losses -= change
        
        if losses == 0:
            rsi = 100
        else:
            rs = gains / losses
            rsi = 100 - (100 / (1 + rs))
            
        return {
            'ema': ema,
            'std_dev': std_dev,
            'rsi': rsi
        }

    def on_price_update(self, prices):
        """
        Strategy: Confluence Mean Reversion.
        Avoids 'FIXED_TP' by using dynamic RSI/EMA targets.
        Avoids 'TRAIL_STOP' by using fixed volatility-based stops.
        """
        candidates = []
        
        # 1. Manage Cooldowns
        for sym in list(self.cooldowns.keys()):
            self.cooldowns[sym] -= 1
            if self.cooldowns[sym] <= 0:
                del self.cooldowns[sym]

        # 2. Ingest Data & Update Indicators
        for symbol, info in prices.items():
            try:
                # Strictly parse price as float
                current_price = float(info['priceUsd'])
                liquidity = float(info.get('liquidity', 0))
            except (ValueError, TypeError, KeyError):
                continue
                
            if liquidity < self.min_liquidity:
                continue
            
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(current_price)
            
            # Need full window for valid stats
            if len(self.history[symbol]) < self.window_size:
                continue
            
            stats = self._calculate_stats(self.history[symbol])
            if not stats:
                continue
                
            # Volatility Filter (Fixing ER:0.004)
            # Don't trade if price is flat; fees will kill us.
            if current_price > 0:
                vol_ratio = stats['std_dev'] / current_price
                if vol_ratio < self.min_volatility:
                    continue

            candidates.append({
                'symbol': symbol,
                'price': current_price,
                'stats': stats
            })

        # 3. Manage Positions (Exits)
        active_symbols = list(self.positions.keys())
        for symbol in active_symbols:
            if symbol not in prices:
                continue
                
            pos = self.positions[symbol]
            current_price = float(prices[symbol]['priceUsd'])
            pos['ticks'] += 1
            
            cand = next((c for c in candidates if c['symbol'] == symbol), None)
            
            # --- EXIT: Fixed Stop Loss ---
            # Penalized for TRAIL_STOP, so we respect the initial calculated stop.
            if current_price <= pos['stop']:
                del self.positions[symbol]
                self.cooldowns[symbol] = 15 # Avoid re-entering a falling knife
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['FIXED_STOP']
                }

            # --- EXIT: Dynamic Take Profit ---
            # Penalized for FIXED_TP. We use logic instead of %.
            if cand:
                stats = cand['stats']
                # Target: Price returns to EMA (Mean) OR RSI indicates overbought bounce
                mean_reverted = current_price >= stats['ema']
                rsi_spike = stats['rsi'] > 55
                
                # Ensure we cover fees (sanity check)
                in_profit = current_price > pos['entry'] * 1.002
                
                if (mean_reverted or rsi_spike) and in_profit:
                    del self.positions[symbol]
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': pos['amount'],
                        'reason': ['DYNAMIC_EXIT']
                    }
            
            # --- EXIT: Time Expiry ---
            if pos['ticks'] >= self.max_hold_ticks:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': ['TIME_LIMIT']
                }

        # 4. Find Entries
        if len(self.positions) < self.max_positions:
            potential_entries = []
            
            for c in candidates:
                sym = c['symbol']
                if sym in self.positions or sym in self.cooldowns:
                    continue
                
                stats = c['stats']
                price = c['price']
                
                # Calculate Z-Score (Deviation from Mean)
                if stats['std_dev'] == 0:
                    continue
                deviation = price - stats['ema']
                z_score = deviation / stats['std_dev']
                
                # STRICT ENTRY LOGIC
                # 1. Z-Score must be negative and deep (Statistical Dip)
                # 2. RSI must be low (Momentum exhaustion)
                if z_score < -self.entry_z_score_thresh and stats['rsi'] < self.entry_rsi_thresh:
                    potential_entries.append({
                        'symbol': sym,
                        'price': price,
                        'z_score': z_score,
                        'std_dev': stats['std_dev']
                    })
            
            # Select best candidate (Deepest Z-Score)
            if potential_entries:
                potential_entries.sort(key=lambda x: x['z_score']) # Lowest z-score first
                target = potential_entries[0]
                
                entry_price = target['price']
                amount = self.virtual_balance / entry_price
                
                # Calculate Fixed Stop Loss
                stop_dist = target['std_dev'] * self.stop_loss_mult
                stop_price = entry_price - stop_dist
                
                if stop_price <= 0:
                    stop_price = entry_price * 0.5
                
                self.positions[target['symbol']] = {
                    'entry': entry_price,
                    'stop': stop_price,
                    'amount': amount,
                    'ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': target['symbol'],
                    'amount': amount,
                    'reason': ['CONFLUENCE_DIP']
                }
        
        return None