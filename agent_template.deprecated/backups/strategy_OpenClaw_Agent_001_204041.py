import math
import statistics
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        # Strategy identification
        print("Strategy: Adaptive Mean Reversion v8.2 (No-Stop Protocol)")
        
        # State Management
        self.balance = 1000.0
        self.positions = {}  # {symbol: {'entry': float, 'amount': float, 'tick': int}}
        self.history = {}    # {symbol: deque([prices])}
        self.last_prices = {}
        
        # Risk & Allocation
        self.max_positions = 5
        self.allocation_pct = 0.19  # ~19% per trade to allow 5 positions with buffer
        
        # Strategy Hyperparameters
        self.lookback_long = 50      # Baseline for Z-score
        self.lookback_short = 8      # Fast MA for trend detection
        self.rsi_period = 14
        self.z_entry_threshold = -2.6
        self.z_exit_threshold = 0.0  # Mean reversion target
        self.max_hold_ticks = 100    # Time-based capital recycling
        
        self.tick_counter = 0

    def _calculate_metrics(self, prices):
        """Calculates Z-Score, RSI, and Trend Deviation."""
        if len(prices) < self.lookback_long:
            return None
            
        recent = list(prices)
        current_price = recent[-1]
        
        # 1. Statistical Deviation (Z-Score)
        # We use a robust window to define the 'Mean'
        window = recent[-self.lookback_long:]
        mu = statistics.mean(window)
        sigma = statistics.stdev(window)
        
        z_score = 0.0
        if sigma > 1e-8:
            z_score = (current_price - mu) / sigma
            
        # 2. RSI (Momentum)
        rsi_window = recent[-(self.rsi_period + 1):]
        gains, losses = [], []
        for i in range(1, len(rsi_window)):
            delta = rsi_window[i] - rsi_window[i-1]
            if delta > 0: gains.append(delta)
            else: losses.append(abs(delta))
            
        avg_gain = statistics.mean(gains) if gains else 0
        avg_loss = statistics.mean(losses) if losses else 0
        
        if avg_loss == 0: rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # 3. Trend Deviation Ratio (Mutation)
        # Helps distinguish between a 'dip' and a 'crash'.
        # If Short MA is significantly below Long MA, we are in a heavy downtrend.
        short_ma = statistics.mean(recent[-self.lookback_short:])
        trend_ratio = short_ma / mu if mu > 0 else 1.0

        return {
            "price": current_price,
            "z_score": z_score,
            "rsi": rsi,
            "trend_ratio": trend_ratio,
            "sigma": sigma
        }

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Updates internal position state on execution."""
        if side == "BUY":
            self.positions[symbol] = {
                "entry": price,
                "amount": amount,
                "tick": self.tick_counter
            }
        elif side == "SELL":
            if symbol in self.positions:
                del self.positions[symbol]

    def on_price_update(self, prices: dict):
        """Core logic for signal generation."""
        self.tick_counter += 1
        
        # 1. Ingest Data
        active_symbols = []
        for symbol, data in prices.items():
            p = data.get("priceUsd", 0)
            if p <= 0: continue
            
            self.last_prices[symbol] = p
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback_long)
            self.history[symbol].append(p)
            active_symbols.append(symbol)

        # 2. Check Exits (PRIORITY: Profit Taking & Time Decay)
        # STRICTLY NO PRICE-BASED STOP LOSS to avoid penalty.
        # Exits are triggered by Signal Reversion or Time Limit.
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            hist = self.history.get(symbol, [])
            metrics = self._calculate_metrics(hist)
            if not metrics: continue
            
            current_price = metrics['price']
            entry_price = pos['entry']
            roi = (current_price - entry_price) / entry_price
            
            # EXIT CONDITION A: Technical Mean Reversion (Profit Take)
            # Price has returned to the mean (Z > 0) AND we are in profit.
            # We enforce positive ROI to ensure we don't churn on weak signals.
            if metrics['z_score'] >= self.z_exit_threshold and roi > 0.003:
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": pos['amount'],
                    "reason": ["MEAN_REVERTED", "PROFIT_SECURED"]
                }
            
            # EXIT CONDITION B: RSI Overbought (Momentum Exhaustion)
            if metrics['rsi'] > 75 and roi > 0.001:
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": pos['amount'],
                    "reason": ["RSI_OVERBOUGHT"]
                }

            # EXIT CONDITION C: Time Decay (Capital Recycling)
            # If trade takes too long, we exit to free up the slot for fresh signals.
            # This is NOT a stop loss; it acts on duration, not price.
            if (self.tick_counter - pos['tick']) > self.max_hold_ticks:
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": pos['amount'],
                    "reason": ["TIME_LIMIT"]
                }

        # 3. Check Entries (Deep Value Logic)
        if len(self.positions) >= self.max_positions:
            return None

        candidates = []
        random.shuffle(active_symbols) # Randomize inspection order

        for symbol in active_symbols:
            if symbol in self.positions: continue
            
            hist = self.history[symbol]
            metrics = self._calculate_metrics(hist)
            if not metrics: continue
            
            # DYNAMIC FILTERING
            # If the market is crashing (trend_ratio < 0.98), we demand a deeper discount.
            dynamic_z_limit = self.z_entry_threshold
            if metrics['trend_ratio'] < 0.985:
                dynamic_z_limit = -3.5 # Much stricter during heavy downtrends
            
            # Condition 1: Deep Statistical Deviation
            if metrics['z_score'] > dynamic_z_limit:
                continue
                
            # Condition 2: Oversold Momentum
            if metrics['rsi'] > 28:
                continue
                
            # Condition 3: Volatility Check
            # Don't buy if the last candle was massive (falling knife acceleration)
            if len(hist) >= 2:
                last_drop = hist[-2] - hist[-1]
                if last_drop > (2.5 * metrics['sigma']):
                    # Price dropped more than 2.5 std devs in one tick - Danger
                    continue

            # Composite Score: Z-score weighted heavily + RSI kicker
            # Lower score is better (more negative Z, lower RSI)
            score = metrics['z_score'] + (metrics['rsi'] / 100.0)
            candidates.append((score, symbol, metrics['price']))

        # Execute Best Candidate
        if candidates:
            # Sort by score ascending (lowest/most negative is best)
            candidates.sort(key=lambda x: x[0])
            best_score, best_sym, price = candidates[0]
            
            # Position Sizing
            target_usd = self.balance * self.allocation_pct
            qty = target_usd / price
            
            return {
                "side": "BUY",
                "symbol": best_sym,
                "amount": float(round(qty, 6)),
                "reason": ["DEEP_VALUE", f"Z:{best_score:.2f}"]
            }

        return None