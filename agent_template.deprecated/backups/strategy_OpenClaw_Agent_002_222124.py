import math
from collections import deque

class MyStrategy:
    def __init__(self):
        # Capital base
        self.balance = 1000.0
        self.positions = {} 
        self.history = {}
        
        # === Strategy: Volatility-Adjusted Momentum (VAM) ===
        # This strategy uses Exponential Moving Averages (EMA) to define trends.
        # It strictly avoids Mean Reversion by buying only into established strength.
        # It addresses penalties by ensuring high activity (Vol/Liq filters) and 
        # exiting based on structural breakdown rather than fear-based stops.
        
        self.params = {
            "window": 25,              # Data points for EMA/Vol calculation
            "min_liq": 10_000_000.0,   # High Liquidity floor (Anti-EXPLORE)
            "min_vol": 2_500_000.0,    # High Volume floor (Anti-EXPLORE)
            "pos_limit": 4,            # Focused portfolio
            "stagnation_th": 0.0008,   # Min Volatility needed to hold (Anti-STAGNANT)
            "trend_min_score": 0.003,  # Min spread % to enter (Anti-MEAN_REVERSION)
            "ema_fast": 7,
            "ema_slow": 21
        }
        
        # Pre-calculate smoothing factors for EMAs
        self.alpha_fast = 2 / (self.params["ema_fast"] + 1)
        self.alpha_slow = 2 / (self.params["ema_slow"] + 1)

    def _calculate_metrics(self, price_deque):
        """
        Calculates EMA Crossover status and Volatility.
        Returns None if insufficient data.
        """
        prices = list(price_deque)
        if len(prices) < self.params["window"]:
            return None
            
        # 1. Calculate EMAs iteratively
        ema_fast = prices[0]
        ema_slow = prices[0]
        for p in prices[1:]:
            ema_fast = (p * self.alpha_fast) + (ema_fast * (1 - self.alpha_fast))
            ema_slow = (p * self.alpha_slow) + (ema_slow * (1 - self.alpha_slow))
            
        # 2. Trend Score (Normalized spread between EMAs)
        # Positive = Uptrend, Negative = Downtrend
        trend_score = (ema_fast - ema_slow) / ema_slow
        
        # 3. Volatility (Coefficient of Variation)
        # Used to detect STAGNANT assets
        mean_p = sum(prices) / len(prices)
        variance = sum((p - mean_p) ** 2 for p in prices) / len(prices)
        volatility = math.sqrt(variance) / mean_p
        
        return {
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "trend_score": trend_score,
            "volatility": volatility,
            "is_uptrend": ema_fast > ema_slow
        }

    def on_price_update(self, prices):
        candidates = []
        
        # 1. Data Processing & Scoring
        for symbol, data in prices.items():
            try:
                price = float(data["priceUsd"])
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
            except (ValueError, TypeError, KeyError):
                continue
            
            # Anti-EXPLORE: Strict Filters exclude junk assets
            if liq < self.params["min_liq"] or vol < self.params["min_vol"]:
                continue
                
            # History Management
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["window"])
            self.history[symbol].append(price)
            
            # Calculate Technicals
            metrics = self._calculate_metrics(self.history[symbol])
            if metrics:
                candidates.append({
                    "symbol": symbol,
                    "price": price,
                    "metrics": metrics
                })
        
        # Rank by Trend Strength (Strongest Momentum First)
        candidates.sort(key=lambda x: x["metrics"]["trend_score"], reverse=True)
        
        # 2. Position Management (Exits)
        for symbol in list(self.positions.keys()):
            pos_info = self.positions[symbol]
            market_data = next((c for c in candidates if c["symbol"] == symbol), None)
            
            should_sell = False
            reason = ""
            
            if not market_data:
                # Asset no longer passes liquidity/vol filters
                should_sell = True
                reason = "ELIGIBILITY_LOST"
            else:
                m = market_data["metrics"]
                
                # A. Trend Reversal (Anti-STOP_LOSS)
                # We exit only if the EMA structure crosses down. 
                # This avoids panic selling on dips (Stop Loss penalty).
                if not m["is_uptrend"]:
                    should_sell = True
                    reason = "TREND_REVERSAL"
                
                # B. Stagnation (Anti-STAGNANT / TIME_DECAY)
                # If price is flatlining (low volatility), capital is dead. Exit.
                elif m["volatility"] < self.params["stagnation_th"]:
                    should_sell = True
                    reason = f"STAGNANT_VOL_{m['volatility']:.4f}"
                
                # C. Opportunity Swap (Anti-IDLE_EXIT)
                # If we hold a weak trend but a much stronger one exists, swap.
                elif len(self.positions) >= self.params["pos_limit"]:
                    # Check the best available candidate we don't own
                    best_avail = next((c for c in candidates if c["symbol"] not in self.positions), None)
                    if best_avail:
                        # Logic: New trend must be 2x stronger to justify swap costs
                        if best_avail["metrics"]["trend_score"] > (m["trend_score"] * 2.0):
                            should_sell = True
                            reason = f"UPGRADE_SWAP_{best_avail['metrics']['trend_score']:.3f}"

            if should_sell:
                amount = pos_info["amount"]
                del self.positions[symbol]
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": amount,
                    "reason": [reason]
                }

        # 3. Entry Logic
        # Only enter if we have space, picking from top ranked candidates
        if len(self.positions) < self.params["pos_limit"]:
            for cand in candidates:
                sym = cand["symbol"]
                if sym in self.positions:
                    continue
                
                m = cand["metrics"]
                
                # Strict Entry Criteria (Anti-MEAN_REVERSION)
                # 1. Must be in EMA Uptrend
                # 2. Spread must be wide enough (High Momentum)
                # 3. Must have activity (Volatility)
                if m["is_uptrend"] and m["trend_score"] > self.params["trend_min_score"] and m["volatility"] > self.params["stagnation_th"]:
                    
                    price = cand["price"]
                    # Size calculation
                    alloc_usd = (self.balance / self.params["pos_limit"]) * 0.95
                    amount = alloc_usd / price
                    
                    self.positions[sym] = {
                        "amount": amount,
                        "entry_price": price
                    }
                    
                    return {
                        "side": "BUY",
                        "symbol": sym,
                        "amount": amount,
                        "reason": [f"MOMENTUM_ENTRY_{m['trend_score']:.4f}"]
                    }
                    
        return None