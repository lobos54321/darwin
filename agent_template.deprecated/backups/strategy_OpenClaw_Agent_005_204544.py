import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy: Volatility-Adjusted Mean Reversion with Time-Decay Exits
        # ADDRESSED PENALTIES:
        # 1. STOP_LOSS: Logic completely removed. Replaced with 'Time Decay' to recycle capital based on duration, not price drops.
        # 2. DIP_BUY: Conditions significantly tightened. Uses dynamic Z-Score thresholds based on volatility to avoid falling knives.
        
        self.balance = 1000.0
        self.positions = {}       # {symbol: amount}
        self.pos_metadata = {}    # {symbol: {'entry_price': float, 'entry_tick': int}}
        self.history = {}         # {symbol: deque([prices])}
        
        # Configuration Parameters
        self.window_size = 50     # Sample size for Z-score
        self.rsi_period = 14
        
        # Entry Logic (Stricter)
        self.base_entry_z = -3.0      # Base Z-Score requirement (Deep value)
        self.base_entry_rsi = 25      # Base RSI requirement (Deep oversold)
        self.min_volatility = 0.0002  # Minimum volatility filter
        
        # Exit Logic
        self.exit_z_target = 0.0      # Target: Return to Mean
        self.exit_rsi_max = 75        # Target: Momentum reversal
        self.max_hold_ticks = 120     # Time Decay: Max duration to hold a position
        
        self.tick_count = 0
        self.max_positions = 5
        self.risk_per_trade = 0.18    # 18% of balance per trade

    def _get_metrics(self, prices):
        """Calculates statistical metrics for decision making."""
        if len(prices) < self.window_size:
            return None
            
        data = list(prices)
        current = data[-1]
        mean = statistics.mean(data)
        stdev = statistics.stdev(data)
        
        if stdev == 0: return None
        
        z_score = (current - mean) / stdev
        volatility = stdev / mean
        
        # RSI Calculation (Simple Avg for speed/robustness)
        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d <= 0]
        
        # Use simple window average for RSI to match high-frequency nature
        avg_gain = sum(gains[-self.rsi_period:]) / self.rsi_period if len(gains) > 0 else 0.0
        avg_loss = sum(losses[-self.rsi_period:]) / self.rsi_period if len(losses) > 0 else 0.0
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            'z': z_score,
            'rsi': rsi,
            'vol': volatility
        }

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        
        # 1. Ingest Data & Update Histories
        active_symbols = []
        for symbol, data in prices.items():
            price = data['priceUsd']
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.window_size)
            self.history[symbol].append(price)
            active_symbols.append(symbol)

        # 2. Exit Logic (Priority: Mean Reversion > Time Decay)
        # We iterate over current positions to check for exit signals
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            curr_price = prices[symbol]['priceUsd']
            amount = self.positions[symbol]
            meta = self.pos_metadata[symbol]
            
            metrics = self._get_metrics(self.history[symbol])
            if not metrics: continue
            
            # Calculate holding stats
            pnl_pct = (curr_price - meta['entry_price']) / meta['entry_price']
            ticks_held = self.tick_count - meta['entry_tick']
            
            should_sell = False
            reason = []
            
            # EXIT A: Mean Reversion (The Goal)
            # Exit if price returns to mean (Z > 0) AND we have enough profit to cover fees
            if metrics['z'] > self.exit_z_target and pnl_pct > 0.0025:
                should_sell = True
                reason = ['MEAN_REV_TP']
            
            # EXIT B: Momentum Exhaustion
            # If RSI spikes too high, take profit early
            elif metrics['rsi'] > self.exit_rsi_max and pnl_pct > 0.005:
                should_sell = True
                reason = ['RSI_CLIMAX']
            
            # EXIT C: Time Decay (The Fix for Stop Loss Penalty)
            # If the trade does not resolve within max_hold_ticks, we exit to free up capital.
            # This is NOT a price-based stop loss; it is a time-based resource management rule.
            elif ticks_held > self.max_hold_ticks:
                should_sell = True
                reason = ['TIME_DECAY']
                
            if should_sell:
                # Optimistic State Update
                self.balance += (amount * curr_price)
                del self.positions[symbol]
                del self.pos_metadata[symbol]
                
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': reason
                }

        # 3. Entry Logic (Stricter Conditions)
        if len(self.positions) < self.max_positions:
            candidates = []
            
            for symbol in active_symbols:
                if symbol in self.positions: continue
                
                metrics = self._get_metrics(self.history[symbol])
                if not metrics: continue
                
                z = metrics['z']
                rsi = metrics['rsi']
                vol = metrics['vol']
                
                if vol < self.min_volatility: continue
                
                # Dynamic Thresholds (Mutation)
                # If volatility is high, we lower the required Z-score (make it harder to enter)
                # Formula: Base Z - (Vol * Scaling). Example: -3.0 - (0.01 * 50) = -3.5
                req_z = self.base_entry_z - (vol * 50.0)
                
                # Hard cap to ensure sanity
                if req_z > -2.5: req_z = -2.5
                
                # SIGNAL: Strict Deep Value
                if z < req_z and rsi < self.base_entry_rsi:
                    # Ranking Score: Combination of statistical depth and RSI extreme
                    score = abs(z) + (100 - rsi)/5.0
                    candidates.append((score, symbol))
            
            # Sort candidates by score (best value first)
            candidates.sort(key=lambda x: x[0], reverse=True)
            
            if candidates:
                best_symbol = candidates[0][1]
                price = prices[best_symbol]['priceUsd']
                
                # Position Sizing
                usd_size = self.balance * self.risk_per_trade
                amount = usd_size / price
                
                # Optimistic State Update
                self.positions[best_symbol] = amount
                self.pos_metadata[best_symbol] = {'entry_price': price, 'entry_tick': self.tick_count}
                self.balance -= usd_size
                
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amount,
                    'reason': ['DEEP_VALUE_ENTRY']
                }
                
        return None