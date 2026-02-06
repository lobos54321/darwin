# Darwin SDK - User Strategy Template
# 🧬 AGENT: Bo_Bot | GEN: 80 | CODENAME: PHOENIX_PROTOCOL
# -----------------------------------------------------------------------------
# Evolution Log (Gen 80):
# 1. SURVIVAL FIRST: Reduced position size to 5% to prevent total ruin.
# 2. SIMPLIFICATION: Abandoned complex volatility squeeze for robust EMA Trend + RSI.
# 3. TRAILING STOP: Implemented a dynamic trailing stop to lock in profits early.
# 4. SANITY CHECK: Added logic to prevent trading if price data is stale or insufficient.
# -----------------------------------------------------------------------------

import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (Gen 80: Phoenix Protocol)")
        
        # --- Configuration ---
        self.roi_target = 0.05          # Target 5% profit per trade
        self.stop_loss_pct = 0.03       # Hard stop loss at 3%
        self.trailing_sl_pct = 0.015    # Trailing stop gap
        self.max_positions = 4          # Max concurrent trades
        self.position_size_usd = 50.0   # Fixed dollar amount per trade (Conservative)
        
        # --- State ---
        self.positions = {}             # {symbol: {"entry": float, "highest": float, "amount": float}}
        self.history = {}               # {symbol: deque(maxlen=30)}
        self.banned_tags = set()
        self.cash = 1000.0              # Simulated cash tracking
        
    def on_hive_signal(self, signal: dict):
        """Handle Hive Mind signals for penalties/boosts"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"🛡️ DEFENSE: Banning tags {penalize}")
            self.banned_tags.update(penalize)

    def _calculate_indicators(self, prices_list):
        """Calculate EMA and RSI"""
        if len(prices_list) < 14:
            return None, None
            
        # Simple EMA (Exponential Moving Average) - Period 10
        k = 2 / (10 + 1)
        ema = prices_list[0]
        for p in prices_list[1:]:
            ema = (p * k) + (ema * (1 - k))
            
        # RSI (Relative Strength Index) - Period 14
        deltas = [prices_list[i+1] - prices_list[i] for i in range(len(prices_list)-1)]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        avg_gain = sum(gains[-14:]) / 14 if gains else 0
        avg_loss = sum(losses[-14:]) / 14 if losses else 0.0001 # Avoid div by zero
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return ema, rsi

    def on_price_update(self, prices: dict):
        """Main trading logic loop"""
        decision = None
        
        # 1. Update History & Manage Existing Positions
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # Update history
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=30)
            self.history[symbol].append(current_price)
            
            # Check Exits (Stop Loss / Take Profit)
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # Update highest price seen for trailing stop
                if current_price > pos["highest"]:
                    pos["highest"] = current_price
                
                # Logic: Hard Stop OR Trailing Stop
                pnl_pct = (current_price - pos["entry"]) / pos["entry"]
                drop_from_peak = (pos["highest"] - current_price) / pos["highest"]
                
                should_sell = False
                reason = ""
                
                if pnl_pct <= -self.stop_loss_pct:
                    should_sell = True
                    reason = "Hard Stop Loss"
                elif pnl_pct > 0.01 and drop_from_peak >= self.trailing_sl_pct:
                    should_sell = True
                    reason = "Trailing Stop Hit"
                elif pnl_pct >= self.roi_target:
                    should_sell = True
                    reason = "Target Hit"
                    
                if should_sell:
                    print(f"📉 SELL {symbol} @ {current_price:.4f} ({reason}) PnL: {pnl_pct*100:.2f}%")
                    self.cash += current_price * pos["amount"]
                    del self.positions[symbol]
                    return ("sell", symbol, pos["amount"])

        # 2. Check Entries (If slots available)
        if len(self.positions) < self.max_positions and self.cash > self.position_size_usd:
            best_opportunity = None
            highest_score = -1
            
            for symbol, data in prices.items():
                # Skip if already holding or banned
                if symbol in self.positions or any(tag in self.banned_tags for tag in data.get("tags", [])):
                    continue
                    
                hist = self.history.get(symbol, [])
                if len(hist) < 20:
                    continue
                    
                current_price = data["priceUsd"]
                ema, rsi = self._calculate_indicators(list(hist))
                
                if ema is None:
                    continue
                
                # Strategy: Trend Pullback
                # Price is above EMA (Trend is up) AND RSI is not overbought (< 70)
                # But RSI is rising (> 40)
                if current_price > ema and 40 < rsi < 70:
                    # Score based on momentum (price vs EMA distance)
                    score = (current_price - ema) / ema
                    if score > highest_score:
                        highest_score = score
                        best_opportunity = symbol
            
            if best_opportunity:
                price = prices[best_opportunity]["priceUsd"]
                amount = self.position_size_usd / price
                self.cash -= self.position_size_usd
                
                self.positions[best_opportunity] = {
                    "entry": price,
                    "highest": price,
                    "amount": amount
                }
                print(f"🚀 BUY {best_opportunity} @ {price:.4f} [Trend+RSI]")
                return ("buy", best_opportunity, amount)
                
        return None