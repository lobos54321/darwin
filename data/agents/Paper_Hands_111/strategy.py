import math
import statistics
from collections import deque
from typing import Dict, List, Optional, Set

class MyStrategy:
    """
    Agent: Paper_Hands_111 -> Evolved: Phoenix_Ascension_v3
    
    Evolutionary Improvements:
    1.  Trend Following (EMA Crossover): Replaces mean reversion to catch meme super-cycles.
    2.  Trailing Stop Mechanism: Replaces fixed TP to let winners run (unlimited upside).
    3.  Portfolio Heat Control: Limits correlation risk by filtering weak momentum.
    4.  Capital Preservation: Dynamic position sizing based on current equity to recover drawdown.
    """

    def __init__(self):
        print("🔥 Strategy Evolved: Phoenix_Ascension_v3 Initialized")
        
        # === Configuration ===
        self.ema_short_period = 7
        self.ema_long_period = 21
        self.max_positions = 4          # Increased slightly to diversify
        self.stop_loss_pct = 0.04       # Tight 4% hard stop
        self.trailing_stop_pct = 0.08   # 8% trailing stop to handle volatility
        self.min_24h_change = 2.0       # Only enter assets with positive momentum (>2%)
        
        # === State Management ===
        self.history: Dict[str, deque] = {}     # Price history for EMA calc
        self.positions: Dict[str, dict] = {}    # Currently held assets
        self.banned_tags: Set[str] = set()      # Hive Mind penalties
        
        # Current simulated balance (starts with residual from previous generation)
        self.balance = 536.69 
        self.initial_balance = 536.69

    def on_hive_signal(self, signal: dict):
        """Absorb Hive Mind wisdom to filter toxic assets."""
        penalize = signal.get("penalize", [])
        if penalize:
            print(f"⚠️ Hive Alert: Penalizing tags {penalize}")
            self.banned_tags.update(penalize)

    def _calculate_ema(self, prices: List[float], period: int) -> float:
        if len(prices) < period:
            return statistics.mean(prices)
        
        multiplier = 2 / (period + 1)
        ema = prices[0] # Start with SMA of first few or just first price
        # Simple iterative calculation
        for price in prices:
            ema = (price - ema) * multiplier + ema
        return ema

    def on_price_update(self, prices: dict) -> List[dict]:
        """
        Main trading logic loop.
        Returns a list of orders: [{"symbol": "MOLT", "side": "BUY", "amount": 100}, ...]
        """
        orders = []
        
        # 1. Update History & Manage Existing Positions
        active_symbols = list(self.positions.keys())
        
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            
            # Update History Deque
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=30)
            self.history[symbol].append(current_price)
            
            # --- Exit Logic (Risk Management) ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                entry_price = pos['entry_price']
                highest_price = pos.get('highest_price', entry_price)
                
                # Update High Water Mark
                if current_price > highest_price:
                    self.positions[symbol]['highest_price'] = current_price
                    highest_price = current_price
                
                # Check Hard Stop Loss
                pnl_pct = (current_price - entry_price) / entry_price
                if pnl_pct < -self.stop_loss_pct:
                    orders.append({"symbol": symbol, "side": "SELL", "amount": pos['amount'], "reason": "STOP_LOSS"})
                    self.balance += current_price * pos['amount']
                    del self.positions[symbol]
                    continue

                # Check Trailing Stop
                drawdown_from_peak = (highest_price - current_price) / highest_price
                if drawdown_from_peak > self.trailing_stop_pct and pnl_pct > 0:
                    orders.append({"symbol": symbol, "side": "SELL", "amount": pos['amount'], "reason": "TRAILING_STOP"})
                    self.balance += current_price * pos['amount']
                    del self.positions[symbol]
                    continue
                    
        # 2. Entry Logic (Trend Following)
        # Sort candidates by 24h change to prioritize momentum
        candidates = []
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            if symbol in self.banned_tags: continue # Check Hive bans (simplified logic assuming symbol is tag)
            
            price_change = data.get("priceChange24h", 0)
            if price_change < self.min_24h_change: continue
            
            candidates.append((symbol, data, price_change))
            
        # Sort by strongest momentum
        candidates.sort(key=lambda x: x[2], reverse=True)
        
        for symbol, data, change in candidates:
            if len(self.positions) >= self.max_positions:
                break
                
            if self.balance < 10: # Minimum capital check
                break

            current_price = data["priceUsd"]
            history = self.history.get(symbol, [])
            
            if len(history) >= self.ema_long_period:
                ema_short = self._calculate_ema(list(history), self.ema_short_period)
                ema_long = self._calculate_ema(list(history), self.ema_long_period)
                
                # Golden Cross Condition + Price Strength
                if ema_short > ema_long and current_price > ema_short:
                    # Position Sizing: Use 20% of CURRENT balance (Conservative Recovery)
                    trade_amount_usd = self.balance * 0.20
                    token_amount = trade_amount_usd / current_price
                    
                    self.positions[symbol] = {
                        "entry_price": current_price,
                        "amount": token_amount,
                        "highest_price": current_price
                    }
                    self.balance -= trade_amount_usd
                    
                    orders.append({
                        "symbol": symbol, 
                        "side": "BUY", 
                        "amount": token_amount,
                        "cost": trade_amount_usd
                    })
                    print(f"🚀 ENTER {symbol} @ {current_price} (EMA Trend)")

        return orders