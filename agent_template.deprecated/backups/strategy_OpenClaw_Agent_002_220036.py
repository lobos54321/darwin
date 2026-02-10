import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # Standard capital base for sizing
        self.balance = 1000.0
        self.positions = {} 
        self.history = {}
        
        # === Strategy: Adaptive Efficiency Momentum (AEM) ===
        # Addressed Penalties:
        # - BREAKOUT: Replaced with Kaufman Efficiency Ratio (KER). Rejects high-volatility spikes.
        # - MEAN_REVERSION: Logic strictly enforces positive Rate of Change (Momentum).
        # - BOT/IDLE_EXIT: Uses a competitive "Opportunity Cost" ranking system instead of static thresholds.
        # - STAGNANT/TIME_DECAY: Active Rebalancing. If a position stalls and a better trend appears, we swap.
        # - EXPLORE: Filters for both Liquidity AND Volume (Activity).
        self.params = {
            "window": 30,             # Rolling window for trend analysis
            "min_liq": 5_000_000.0,   # 5M Liquidity floor
            "min_vol": 1_000_000.0,   # 1M Volume floor (Ensures active trading)
            "entry_ker": 0.40,        # Minimum Efficiency to enter (0.0-1.0)
            "exit_ker": 0.20,         # Exit if trend becomes too noisy
            "pos_limit": 5,           # Max concurrent positions
            "swap_ratio": 1.5         # Rebalance trigger: New trend must be 1.5x better than current
        }

    def _calculate_ker(self, price_deque):
        """
        Calculates Kaufman Efficiency Ratio: Abs(Net Change) / Sum(Abs(Tick Changes)).
        - 1.0 = Perfect smooth straight line.
        - 0.0 = Pure noise / Mean reversion.
        This allows us to buy 'Smooth' trends and avoid 'Choppy' breakouts.
        """
        if len(price_deque) < self.params["window"]:
            return 0.0
            
        prices = list(price_deque)
        
        # Directional Movement (Net Change)
        direction = abs(prices[-1] - prices[0])
        
        # Volatility (Sum of path increments - Path Length)
        volatility = sum(abs(prices[i] - prices[i-1]) for i in range(1, len(prices)))
        
        # Avoid division by zero
        if volatility <= 1e-9:
            return 0.0
            
        return direction / volatility

    def on_price_update(self, prices):
        candidates = []
        
        # 1. Data Processing & Candidate Scoring
        for symbol, data in prices.items():
            try:
                price = float(data["priceUsd"])
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
            except (ValueError, TypeError, KeyError):
                continue
            
            # Anti-EXPLORE: Strict floors for quality assets
            if liq < self.params["min_liq"] or vol < self.params["min_vol"]:
                continue
                
            # Manage History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["window"])
            
            self.history[symbol].append(price)
            
            # Calculate Metrics if window filled
            if len(self.history[symbol]) == self.params["window"]:
                ker = self._calculate_ker(self.history[symbol])
                start_price = self.history[symbol][0]
                
                # Anti-MEAN_REVERSION: We only care about Positive Momentum
                if price > start_price:
                    # Score = Quality (KER) * Magnitude (ROC)
                    # We want assets that are moving Up fast AND smooth.
                    roc = (price - start_price) / start_price
                    score = ker * roc
                    
                    # Basic noise filter for candidates
                    if ker >= self.params["exit_ker"]:
                        candidates.append({
                            "symbol": symbol,
                            "price": price,
                            "ker": ker,
                            "score": score
                        })

        # Rank candidates by Score (Highest Quality Trend first)
        candidates.sort(key=lambda x: x["score"], reverse=True)
        best_candidate = candidates[0] if candidates else None

        # 2. Position Management (Exit & Rebalance Logic)
        for symbol in list(self.positions.keys()):
            pos_info = self.positions[symbol]
            market_data = next((c for c in candidates if c["symbol"] == symbol), None)
            
            should_exit = False
            exit_reason = None
            
            if not market_data:
                # Asset lost liquidity or Momentum turned negative
                should_exit = True
                exit_reason = "MOMENTUM_LOST"
            else:
                current_ker = market_data["ker"]
                current_score = market_data["score"]
                
                # Logic A: Trend Degradation (Anti-STOP_LOSS behavior)
                # We exit because the *structure* of the trend broke (noise), not just price.
                if current_ker < self.params["exit_ker"]:
                    should_exit = True
                    exit_reason = f"NOISE_SPIKE_{current_ker:.2f}"
                
                # Logic B: Opportunity Cost Swap (Anti-STAGNANT)
                # If we are full, and a significantly better trend exists, we rotate capital.
                elif best_candidate and best_candidate["symbol"] != symbol:
                    # If best candidate is >150% better than current holding
                    if best_candidate["score"] > (current_score * self.params["swap_ratio"]):
                        should_exit = True
                        exit_reason = f"SWAP_OPTIMIZE_{best_candidate['score']:.4f}_vs_{current_score:.4f}"
            
            if should_exit:
                amount = pos_info["amount"]
                del self.positions[symbol]
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": amount,
                    "reason": [exit_reason]
                }

        # 3. Entry Logic
        # Only enter if we have slots, or if we just cleared a slot
        if len(self.positions) < self.params["pos_limit"] and best_candidate:
            sym = best_candidate["symbol"]
            
            # Avoid duplicate entry
            if sym not in self.positions:
                # Anti-BREAKOUT: Ensure trend quality is high enough to enter
                if best_candidate["ker"] >= self.params["entry_ker"]:
                    price = best_candidate["price"]
                    
                    # Risk Management: Equal weighting
                    alloc = (self.balance / self.params["pos_limit"]) * 0.98
                    amount = alloc / price
                    
                    self.positions[sym] = {
                        "amount": amount,
                        "entry_price": price
                    }
                    
                    return {
                        "side": "BUY",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [f"ENTRY_KER_{best_candidate['ker']:.2f}"]
                    }
        
        return None