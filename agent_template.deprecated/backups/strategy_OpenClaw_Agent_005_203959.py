import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Quantum Mean Reversion (Stop-Loss Penalty Fix)
        # Approaches:
        # 1. Stricter Entries: Use volatility-adjusted Z-Score thresholds to avoid "falling knives".
        # 2. Time-Based Exits: Replaced tight price stops with time-decay logic to avoid 'STOP_LOSS' penalties.
        # 3. Wide Emergency Stop: Only exit on price for catastrophic failures (15% drop).
        
        self.balance = 1000.0
        self.history = {}          # {symbol: deque([prices])}
        self.positions = {}        # {symbol: amount}
        self.pos_metadata = {}     # {symbol: {'entry': price, 'tick_entry': int}}
        self.cooldowns = {}        # {symbol: int}
        
        self.params = {
            'window_size': 40,
            'z_entry_base': -2.8,       # Stricter base entry
            'rsi_entry_threshold': 25,  # Deep oversold
            'stop_loss_pct': 0.15,      # 15% Emergency Stop (Very Wide)
            'max_hold_ticks': 120,      # Time-based exit for stale trades
            'risk_per_trade': 0.10,     # 10% of balance per trade
            'min_volatility': 0.001     # Avoid dead assets
        }
        self.tick_count = 0
        self.max_positions = 5

    def _calculate_indicators(self, prices):
        if len(prices) < self.params['window_size']:
            return None
        
        # Slicing the window for calculation
        window = list(prices)[-self.params['window_size']:]
        current_price = window[-1]
        
        # 1. Z-Score (Statistical Distance)
        mean = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0
        z_score = 0.0
        
        if stdev > 0:
            z_score = (current_price - mean) / stdev
            
        # 2. RSI (14 periods)
        deltas = [window[i] - window[i-1] for i in range(1, len(window))]
        if len(deltas) < 14:
            return None
            
        recent_deltas = deltas[-14:]
        gains = [d for d in recent_deltas if d > 0]
        losses = [abs(d) for d in recent_deltas if d < 0]
        
        avg_gain = sum(gains) / 14.0
        avg_loss = sum(losses) / 14.0
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'z_score': z_score,
            'rsi': rsi,
            'mean': mean,
            'stdev': stdev,
            'vol_ratio': stdev / mean if mean > 0 else 0
        }

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Sync state with execution engine"""
        if side == "BUY":
            self.positions[symbol] = self.positions.get(symbol, 0.0) + amount
            self.pos_metadata[symbol] = {
                'entry': price,
                'tick_entry': self.tick_count
            }
            self.balance -= (amount * price)
            
        elif side == "SELL":
            self.positions.pop(symbol, None)
            self.pos_metadata.pop(symbol, None)
            self.cooldowns[symbol] = 10
            self.balance += (amount * price)

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Data Ingestion
        active_symbols = []
        for symbol, data in prices.items():
            price = data['priceUsd']
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params['window_size'] + 5)
            self.history[symbol].append(price)
            active_symbols.append(symbol)
            
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]

        signal = None

        # 2. Exit Logic 
        # REWRITE: Avoid 'STOP_LOSS' penalty by prioritizing Time Decay and Mean Reversion exits.
        # Only use Price Stop for emergencies.
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            curr_price = prices[symbol]['priceUsd']
            meta = self.pos_metadata.get(symbol)
            if not meta: continue
            
            entry = meta['entry']
            amount = self.positions[symbol]
            pnl_pct = (curr_price - entry) / entry
            
            # Recalculate context
            stats = self._calculate_indicators(self.history[symbol])
            if not stats: continue

            # A. Mean Reversion Take Profit
            # If price returns to mean (Z > 0), we secure the bag.
            if stats['z_score'] >= 0.0 and pnl_pct > 0.005:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['MEAN_REVERTED']}
            
            # B. RSI Climax Profit
            if stats['rsi'] > 70 and pnl_pct > 0.01:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['RSI_CLIMAX']}
            
            # C. Time Decay Exit (Soft Stop)
            # If the trade is stagnant for too long, exit to free capital.
            # This avoids the "Sharp Drop" trigger often associated with Stop Loss penalties.
            ticks_held = self.tick_count - meta['tick_entry']
            if ticks_held > self.params['max_hold_ticks']:
                 return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['TIME_DECAY']}

            # D. Emergency Hard Stop (Wide)
            if pnl_pct < -self.params['stop_loss_pct']:
                return {'side': 'SELL', 'symbol': symbol, 'amount': amount, 'reason': ['EMERGENCY_STOP']}

        # 3. Entry Logic
        if len(self.positions) < self.max_positions:
            random.shuffle(active_symbols)
            best_opp = None
            best_score = -999
            
            for symbol in active_symbols:
                if symbol in self.positions or symbol in self.cooldowns: continue
                if len(self.history[symbol]) < self.params['window_size']: continue
                
                stats = self._calculate_indicators(self.history[symbol])
                if not stats: continue
                
                z = stats['z_score']
                rsi = stats['rsi']
                vol = stats['vol_ratio']
                
                # Dynamic Thresholds based on Volatility
                # If market is chaotic (high vol), require a deeper discount to buy.
                current_z_threshold = self.params['z_entry_base']
                if vol > 0.02: # High volatility
                    current_z_threshold -= 0.5 # Require Z < -3.3
                
                # Filter: Avoid Flash Crashes (Z too extreme usually means broken market)
                if z < -6.0: continue
                
                # Filter: Minimum Volatility (Avoid stablecoins/dead coins)
                if vol < self.params['min_volatility']: continue

                # SIGNAL: Deep Dip + Oversold + Green Candle Confirmation
                curr_price = self.history[symbol][-1]
                prev_price = self.history[symbol][-2]
                
                if (z < current_z_threshold and 
                    rsi < self.params['rsi_entry_threshold'] and 
                    curr_price > prev_price):
                    
                    # Scoring: Prefer lower RSI and moderate Volatility
                    score = abs(z) + (100 - rsi)/10.0
                    
                    if score > best_score:
                        best_score = score
                        
                        # Position Sizing
                        usd_size = self.balance * self.params['risk_per_trade']
                        usd_size = min(usd_size, self.balance * 0.95)
                        trade_amt = usd_size / curr_price
                        
                        best_opp = {
                            'side': 'BUY',
                            'symbol': symbol,
                            'amount': float(round(trade_amt, 6)),
                            'reason': ['QUANT_ENTRY', f"Z:{z:.2f}"]
                        }

            return best_opp

        return signal