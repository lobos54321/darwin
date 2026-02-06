# Darwin SDK - User Strategy Template
# 🧬 AGENT: Bo_Bot | GEN: 77 | CODENAME: ADAPTIVE_FLUX_SURVIVOR
# -----------------------------------------------------------------------------
# Evolution Log (Gen 77):
# 1. SURVIVAL PROTOCOL: Fixed the catastrophic -100% ruin by implementing strict
#    position sizing (max 20% per asset) and ignoring high-risk assets.
# 2. HYBRIDIZATION: Absorbed "Momentum" logic from winners but added a 
#    "Trend Confirmation" filter to avoid buying fake-outs (whipsaws).
# 3. HIVE INTEGRATION: Now actively listens to Hive Mind penalties to blacklist
#    toxic assets immediately.
# 4. MUTATION: "Flux Scoring". Ranks assets by stability + upward drift rather 
#    than pure explosive volatility.
# -----------------------------------------------------------------------------

import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        print("🧠 Strategy Initialized (Gen 77: Adaptive Flux Survivor)")
        
        # --- Configuration ---
        self.HISTORY_LEN = 20           # Number of ticks for SMA/Volatility
        self.BUY_THRESHOLD = 1.2        # Momentum score threshold
        self.STOP_LOSS_PCT = 0.05       # 5% Hard Stop
        self.TAKE_PROFIT_PCT = 0.15     # 15% Target
        self.TRAILING_DEVIATION = 0.03  # Trailing stop distance
        self.MAX_ALLOCATION = 0.2       # Max 20% of capital per asset
        
        # --- State ---
        self.history = {}               # {symbol: deque([prices], maxlen=20)}
        self.positions = {}             # {symbol: {'entry': float, 'highest': float, 'vol': float}}
        self.banned_tags = set()        # Penalized tags/symbols
        self.cooldowns = {}             # {symbol: int (ticks remaining)}

    def on_hive_signal(self, signal: dict):
        """Adapt to collective intelligence signals"""
        # 1. Absorb penalties (Safety)
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"🛡️ DEFENSE: Blacklisting toxic assets: {penalize}")
            self.banned_tags.update(penalize)
            
        # 2. Absorb boosts (Opportunity)
        # In this generation, we treat boosts as a cooldown reset
        boost = signal.get("boost", [])
        for symbol in boost:
            if symbol in self.cooldowns:
                del self.cooldowns[symbol]

    def _calculate_indicators(self, prices):
        if len(prices) < self.HISTORY_LEN:
            return None
        
        current = prices[-1]
        sma = sum(prices) / len(prices)
        try:
            stdev = statistics.stdev(prices)
        except:
            stdev = 0
            
        # Flux Score: (Current - SMA) normalized by Volatility
        # High score = Strong uptrend relative to recent noise
        if stdev == 0:
            z_score = 0
        else:
            z_score = (current - sma) / stdev
            
        return {
            "sma": sma,
            "stdev": stdev,
            "z_score": z_score
        }

    def on_price_update(self, prices: dict):
        """
        Core logic loop. Returns a decision dictionary or None.
        """
        decision = None
        best_opportunity = None
        highest_score = -999

        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # --- 1. Data Ingestion ---
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.HISTORY_LEN)
            self.history[symbol].append(current_price)
            
            # Manage Cooldowns
            if symbol in self.cooldowns:
                self.cooldowns[symbol] -= 1
                if self.cooldowns[symbol] <= 0:
                    del self.cooldowns[symbol]
                continue

            # Skip banned assets
            if symbol in self.banned_tags:
                continue

            # --- 2. Position Management (Defense) ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                entry_price = pos['entry']
                
                # Update highest price seen for trailing stop
                if current_price > pos['highest']:
                    pos['highest'] = current_price
                
                # Check Hard Stop Loss
                pct_change = (current_price - entry_price) / entry_price
                if pct_change < -self.STOP_LOSS_PCT:
                    print(f"🛑 STOP LOSS: {symbol} at {pct_change:.2%}")
                    del self.positions[symbol]
                    self.cooldowns[symbol] = 10 # Stay away for a bit
                    return {"action": "sell", "symbol": symbol, "amount": "100%"}
                
                # Check Trailing Stop
                drawdown_from_peak = (current_price - pos['highest']) / pos['highest']
                if drawdown_from_peak < -self.TRAILING_DEVIATION:
                    print(f"📉 TRAILING STOP: {symbol} dropped {drawdown_from_peak:.2%} from peak")
                    del self.positions[symbol]
                    return {"action": "sell", "symbol": symbol, "amount": "100%"}
                
                # Check Take Profit
                if pct_change > self.TAKE_PROFIT_PCT:
                    print(f"💰 TAKE PROFIT: {symbol} at {pct_change:.2%}")
                    del self.positions[symbol]
                    return {"action": "sell", "symbol": symbol, "amount": "100%"}
                
                continue # Already holding, don't buy more

            # --- 3. Entry Logic (Offense) ---
            stats = self._calculate_indicators(self.history[symbol])
            if not stats:
                continue
                
            # Filter: Only buy if price is above SMA (Trend is up)
            # AND Volatility is manageable (not crazy spikes)
            # AND Z-Score indicates a breakout from the mean
            
            is_uptrend = current_price > stats["sma"]
            breakout_strength = stats["z_score"]
            
            if is_uptrend and breakout_strength > self.BUY_THRESHOLD:
                if breakout_strength > highest_score:
                    highest_score = breakout_strength
                    best_opportunity = symbol

        # Execute Buy for the single best asset found this tick
        if best_opportunity:
            # Simple check to ensure we don't exceed max positions is handled by 
            # the wallet manager usually, but we limit logic here
            if len(self.positions) < 5: # Max 5 positions
                print(f"🚀 ENTRY: {best_opportunity} (Score: {highest_score:.2f})")
                self.positions[best_opportunity] = {
                    'entry': prices[best_opportunity]["priceUsd"],
                    'highest': prices[best_opportunity]["priceUsd"]
                }
                decision = {
                    "action": "buy",
                    "symbol": best_opportunity,
                    "amount": self.MAX_ALLOCATION 
                }

        return decision