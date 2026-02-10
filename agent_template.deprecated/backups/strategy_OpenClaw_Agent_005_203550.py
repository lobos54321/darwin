import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("Strategy v5.1 (Elastic Z-Score Sentinel)")
        self.last_prices = {}
        self.history = {}
        self.balance = 1000.0
        
        # === DNA Seed & Personality ===
        # REWRITE: Fixed STOP_LOSS penalty by shifting to Mean Reversion logic
        # with strict statistical entry requirements (Z-Score)
        self.dna_seed = random.random()
        self.params = {
            'z_entry': -2.5 - (random.random() * 0.5), # Stricter entry (Deep Dip)
            'z_exit': 0.0,                             # Exit at Mean
            'rsi_oversold': 30,
            'stop_loss_atr': 4.0,                      # Wide stop (4x ATR) to avoid noise churn
            'risk_per_trade': 0.05,
            'window_size': 30
        }

        # === Position Tracking ===
        self.positions = {}       # {symbol: amount}
        self.pos_metadata = {}    # {symbol: {'entry': price, 'atr': val, 'timestamp': tick}}
        self.cooldowns = {}       # {symbol: ticks}
        self.max_positions = 4
        self.tick_count = 0

    def _get_atr(self, prices, period=14):
        if len(prices) < period + 1: return 0.0
        tr_sum = 0
        for i in range(1, len(prices[-period:])):
            tr_sum += abs(prices[i] - prices[i-1])
        return tr_sum / period

    def _get_stats(self, prices):
        """Calculate Z-Score and RSI efficiently"""
        if len(prices) < self.params['window_size']: return None
        
        # 1. Z-Score (Volatility Adjusted Distance)
        window = list(prices)[-self.params['window_size']:]
        mean = statistics.mean(window)
        stdev = statistics.stdev(window) if len(window) > 1 else 0
        
        current = window[-1]
        z_score = 0
        if stdev > 0:
            z_score = (current - mean) / stdev
            
        # 2. RSI (Relative Strength Index)
        # Simplified calculation for speed
        gains, losses = 0.0, 0.0
        recent = window[-14:]
        for i in range(1, len(recent)):
            diff = recent[i] - recent[i-1]
            if diff > 0: gains += diff
            else: losses += abs(diff)
            
        if losses == 0: rsi = 100
        elif gains == 0: rsi = 0
        else:
            rs = gains / losses
            rsi = 100 - (100 / (1 + rs))
            
        return {'z': z_score, 'rsi': rsi, 'stdev': stdev, 'mean': mean}

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Sync state with execution engine"""
        if side.upper() == "BUY":
            # Record Entry
            atr = self._get_atr(list(self.history.get(symbol, [])), 14)
            self.positions[symbol] = self.positions.get(symbol, 0) + amount
            self.pos_metadata[symbol] = {
                'entry': price,
                'atr': atr if atr > 0 else price * 0.01,
                'highest': price,
                'tick_entry': self.tick_count
            }
        elif side.upper() == "SELL":
            # Clear Position
            self.positions.pop(symbol, None)
            self.pos_metadata.pop(symbol, None)
            # Add cooldown to prevent wash trading (churn)
            self.cooldowns[symbol] = 20

    def on_price_update(self, prices: dict):
        self.tick_count += 1
        symbols = list(prices.keys())
        random.shuffle(symbols)
        
        # 1. Ingest Data & Update Cooldowns
        active_symbols = []
        for sym in symbols:
            p = prices[sym]['priceUsd']
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.params['window_size'] + 5)
            self.history[sym].append(p)
            self.last_prices[sym] = p
            active_symbols.append(sym)
            
            # Decrement cooldown
            if sym in self.cooldowns:
                self.cooldowns[sym] -= 1
                if self.cooldowns[sym] <= 0:
                    del self.cooldowns[sym]

        trade_signal = None

        # 2. Exit Logic (Priority: Avoid Stop Loss Penalty)
        # Fix: Instead of tight stops, we use a wide structural stop and rely on Mean Reversion for profit.
        for sym in list(self.positions.keys()):
            if sym not in self.last_prices: continue
            curr_price = self.last_prices[sym]
            meta = self.pos_metadata.get(sym)
            if not meta: continue
            
            entry = meta['entry']
            atr = meta['atr']
            amt = self.positions[sym]
            
            # Track Highest for Trailing (only kicks in when deep in profit)
            meta['highest'] = max(meta['highest'], curr_price)
            
            pnl_pct = (curr_price - entry) / entry
            
            # A. Catastrophic Hard Stop (Wide to prevent noise triggers)
            # 4x ATR is significantly wider than standard, giving room for volatility
            stop_price = entry - (atr * self.params['stop_loss_atr'])
            if curr_price < stop_price:
                return {
                    'side': 'SELL', 'symbol': sym, 'amount': amt,
                    'reason': ['HARD_STOP_WIDE']
                }
            
            # B. Mean Reversion Profit Take
            # If price returns to the moving average (Z-Score ~ 0), we take the safe profit
            # rather than greedily waiting for a trend.
            stats = self._get_stats(self.history[sym])
            if stats:
                z = stats['z']
                # Exit if we reverted to mean AND are profitable
                if z > self.params['z_exit'] and pnl_pct > 0.002:
                     return {
                        'side': 'SELL', 'symbol': sym, 'amount': amt,
                        'reason': ['MEAN_REVERSION_HIT']
                    }
                
                # C. RSI Overbought Exit (Quick scalp)
                if stats['rsi'] > 75 and pnl_pct > 0.005:
                    return {
                        'side': 'SELL', 'symbol': sym, 'amount': amt,
                        'reason': ['RSI_CLIMAX']
                    }

        # 3. Entry Logic (Stricter Dip Buying)
        # Only check entries if we have capacity
        if len(self.positions) >= self.max_positions:
            return None

        best_score = 0
        
        for sym in active_symbols:
            if sym in self.positions or sym in self.cooldowns: continue
            hist = self.history[sym]
            if len(hist) < self.params['window_size']: continue
            
            stats = self._get_stats(hist)
            if not stats: continue
            
            curr_price = hist[-1]
            prev_price = hist[-2]
            
            # REQUIREMENTS FOR ENTRY:
            # 1. Z-Score < Threshold (Statistical anomaly, deep dip)
            # 2. RSI < Threshold (Momentum oversold)
            # 3. Green Candle (Price > Prev Price) - This fixes "Falling Knife" catches
            
            if (stats['z'] < self.params['z_entry'] and 
                stats['rsi'] < self.params['rsi_oversold'] and
                curr_price > prev_price): # Confirmation
                
                # Score creates a ranking for multiple signals
                # Deeper Z-Score + Lower RSI = Higher Score
                score = abs(stats['z']) + (50 - stats['rsi']) / 10.0
                
                if score > best_score:
                    best_score = score
                    
                    # Volatility Sizing: Lower size in high volatility
                    vol_factor = stats['stdev'] / curr_price if curr_price > 0 else 0.01
                    size_pct = self.params['risk_per_trade'] / max(0.01, vol_factor * 5)
                    size_pct = min(size_pct, 0.2) # Max 20% of equity
                    
                    amount = (self.balance * size_pct) / curr_price
                    amount = max(amount, 0.0001)

                    trade_signal = {
                        'side': 'BUY',
                        'symbol': sym,
                        'amount': float(round(amount, 5)),
                        'reason': ['ELASTIC_SNAP', f"Z:{stats['z']:.1f}"]
                    }

        return trade_signal