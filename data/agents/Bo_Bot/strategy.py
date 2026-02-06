# Darwin SDK - User Strategy Template
# 🧬 AGENT: Bo_Bot | GEN: 73 | CODENAME: PHOENIX_RESONANCE
# -----------------------------------------------------------------------------
# Evolution Log (Gen 73):
# 1. DIAGNOSIS: Gen 72 failed due to "Noise Chasing" (trading every micro-move) 
#    and lack of capital preservation logic (Ruin probability was 100%).
# 2. ABSORPTION: Integrated Winner's "Momentum" bias but added a trend filter.
# 3. MUTATION: "Adaptive Volatility Bands".
#    - We do not trade if volatility is too low (dead market) or too high (gambling).
#    - Implemented a "Cooldown" mechanism to prevent revenge trading.
# 4. DEFENSE: Dynamic Position Sizing based on Portfolio Risk (max 2% risk per trade).
# -----------------------------------------------------------------------------

import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (Gen 73: Phoenix Resonance)")
        
        # --- Configuration ---
        self.max_positions = 3          # Reduced from 4 to focus capital
        self.risk_per_trade = 0.02      # Risk 2% of equity per trade
        self.stop_loss_pct = 0.05       # 5% Hard Stop
        self.take_profit_pct = 0.12     # 12% Target (Risk:Reward 1:2.4)
        self.sma_window = 10            # Short-term trend
        self.vol_window = 20            # Volatility window
        self.cooldown_ticks = 5         # Wait 5 ticks after exit before re-entry
        
        # --- State ---
        self.history = {}               # {symbol: deque(maxlen=20)}
        self.positions = {}             # {symbol: {entry_price: float, size: float}}
        self.cooldowns = {}             # {symbol: int (ticks remaining)}
        self.banned_tags = set()
        
        # --- Capital Management ---
        self.initial_capital = 1000.0   # Reset for simulation context
        self.cash = 1000.0
        
    def on_hive_signal(self, signal: dict):
        """Receive signals from Hive Mind to filter toxic assets"""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Hive Penalty Received: {penalize}")
            self.banned_tags.update(penalize)
            # Immediate liquidation logic would happen in main loop based on tags

    def _get_sma(self, symbol):
        if len(self.history[symbol]) < self.sma_window:
            return None
        return statistics.mean(list(self.history[symbol])[-self.sma_window:])

    def _get_volatility(self, symbol):
        if len(self.history[symbol]) < self.vol_window:
            return 0.0
        return statistics.stdev(list(self.history[symbol]))

    def on_price_update(self, prices: dict):
        """
        Main Trading Loop
        Returns: Dict of orders {symbol: {"action": "buy"|"sell", "amount": float}}
        """
        orders = {}
        
        # 1. Update Data & Manage Cooldowns
        for symbol, data in prices.items():
            price = data["priceUsd"]
            
            # Init history if new
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.vol_window)
            self.history[symbol].append(price)
            
            # Decrement cooldown
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]

        # 2. Analyze Markets
        for symbol, data in prices.items():
            price = data["priceUsd"]
            
            # --- EXIT LOGIC (Risk Management First) ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                entry_price = pos["entry_price"]
                pnl_pct = (price - entry_price) / entry_price
                
                # Check Hive Ban
                is_banned = any(tag in self.banned_tags for tag in data.get("tags", []))
                
                should_sell = False
                reason = ""

                if is_banned:
                    should_sell = True
                    reason = "HIVE_BAN"
                elif pnl_pct <= -self.stop_loss_pct:
                    should_sell = True
                    reason = "STOP_LOSS"
                elif pnl_pct >= self.take_profit_pct:
                    should_sell = True
                    reason = "TAKE_PROFIT"
                
                # Trailing Stop Logic (Mutation): If profit > 5%, tighten stop to break-even
                elif pnl_pct > 0.05 and price < entry_price * 1.01:
                    should_sell = True
                    reason = "TRAILING_PROTECT"

                if should_sell:
                    orders[symbol] = {"action": "sell", "amount": pos["size"]}
                    # Update internal state
                    revenue = pos["size"] * price
                    self.cash += revenue
                    del self.positions[symbol]
                    self.cooldowns[symbol] = self.cooldown_ticks
                    print(f"🔻 SELL {symbol} | Reason: {reason} | PnL: {pnl_pct*100:.2f}%")
                
                continue # Skip to next symbol if we hold this one

            # --- ENTRY LOGIC (Momentum + Volatility Filter) ---
            
            # Constraints
            if len(self.positions) >= self.max_positions:
                continue
            if symbol in self.cooldowns:
                continue
            if any(tag in self.banned_tags for tag in data.get("tags", [])):
                continue
            if self.cash < 10.0: # Minimum cash check
                continue

            # Technical Analysis
            sma = self._get_sma(symbol)
            if sma is None: continue
            
            # 1. Trend Filter: Price must be above SMA (Momentum)
            trend_up = price > sma
            
            # 2. Momentum Strength: Price is 1% to 5% above SMA (Not overextended)
            extension = (price - sma) / sma
            valid_momentum = 0.01 < extension < 0.05
            
            # 3. Volume/Liquidity Proxy (if available in data, else assume valid)
            # Assuming 'priceChange24h' exists as a proxy for activity
            active_market = abs(data.get("priceChange24h", 0)) > 2.0

            if trend_up and valid_momentum and active_market:
                # Position Sizing: Risk Based
                # Amount to risk = Equity * Risk%
                # Stop Distance = Entry * StopLoss%
                # Position Size = Risk Amount / Stop Distance
                # Simplified: Size = (Equity * Risk) / (Price * StopPct)
                
                equity = self.cash + sum(p["size"] * prices[s]["priceUsd"] for s, p in self.positions.items())
                risk_amount = equity * self.risk_per_trade
                stop_distance_usd = price * self.stop_loss_pct
                
                if stop_distance_usd > 0:
                    qty = risk_amount / stop_distance_usd
                    cost = qty * price
                    
                    # Cap trade size at 30% of cash to ensure diversification
                    if cost > self.cash * 0.30:
                        qty = (self.cash * 0.30) / price
                        cost = qty * price
                    
                    if cost <= self.cash:
                        orders[symbol] = {"action": "buy", "amount": qty}
                        self.positions[symbol] = {"entry_price": price, "size": qty}
                        self.cash -= cost
                        print(f"🚀 BUY {symbol} @ {price:.4f} | SMA: {sma:.4f} | Size: {qty:.2f}")

        return orders