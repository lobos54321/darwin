import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.balance = 1000.0
        self.positions = {}  # Stores: {symbol: {'entry_price': float, 'amount': float, 'tp_price': float, 'sl_price': float, 'ticks_held': int}}
        self.history = {}
        
        # === Strategy: Quantum Impulse (Fixed Horizon) ===
        # REWRITE GOAL: Eliminate 'TRAIL_STOP' penalty.
        # METHOD: Statistical Momentum Impulse with Time-Decay Exit.
        # LOGIC:
        #   1. Entry: Instantaneous log-return exceeds Z-Score threshold.
        #      (Captures immediate liquidity vacuums/bursts without looking for "dips").
        #   2. Exit: 
        #      a. Hard Take Profit (Fixed % derived from volatility at entry).
        #      b. Hard Stop Loss (Fixed % derived from volatility at entry).
        #      c. Temporal Decay (Exit after N ticks regardless of PnL).
        #   3. CRITICAL: No Trailing Stops. Exit levels are frozen at entry.
        
        self.params = {
            "window_size": 15,          # Window for local volatility calculation
            "z_threshold": 2.2,         # Sigma requirement for entry (Statistically significant move)
            "min_liq": 5_000_000.0,     # Liquidity Filter
            "min_vol": 1_000_000.0,     # Volume Filter
            "max_hold_ticks": 10,       # HFT Time limit (Time-based exit)
            "tp_multiplier": 2.5,       # TP = Volatility * Multiplier
            "sl_multiplier": 1.5,       # SL = Volatility * Multiplier
            "pos_limit": 5,             # Max concurrent positions
            "trade_size_pct": 0.15      # 15% of balance per trade
        }

    def _get_volatility_metrics(self, price_deque):
        """
        Calculates log-returns and their standard deviation.
        Returns None if insufficient data.
        """
        if len(price_deque) < self.params["window_size"]:
            return None
            
        prices = list(price_deque)
        
        # Calculate log returns: ln(p_t / p_{t-1})
        # This normalizes price changes regardless of token price magnitude
        log_returns = []
        for i in range(1, len(prices)):
            # Protection against zero/negative prices in raw data
            if prices[i] <= 0 or prices[i-1] <= 0:
                continue
            r = math.log(prices[i] / prices[i-1])
            log_returns.append(r)
            
        if not log_returns:
            return None

        # Calculate Stdev of Returns (Volatility)
        mean_r = sum(log_returns) / len(log_returns)
        variance = sum((r - mean_r) ** 2 for r in log_returns) / len(log_returns)
        std_dev = math.sqrt(variance)
        
        current_return = log_returns[-1]
        
        return {
            "std_dev": std_dev,
            "current_return": current_return,
            "price": prices[-1]
        }

    def on_price_update(self, prices):
        # 1. Position Management (Exits)
        # Priority: Check Time-Decay and Hard Exits before entering new trades
        for symbol in list(self.positions.keys()):
            pos_info = self.positions[symbol]
            current_data = prices.get(symbol)
            
            should_sell = False
            reason = ""
            
            if not current_data:
                should_sell = True
                reason = "DATA_LOST"
            else:
                try:
                    curr_price = float(current_data["priceUsd"])
                    
                    # A. Time-Based Exit (Temporal Decay)
                    # Force exit if trade doesn't work out quickly (HFT principle)
                    pos_info['ticks_held'] += 1
                    if pos_info['ticks_held'] >= self.params["max_hold_ticks"]:
                        should_sell = True
                        reason = "TIME_DECAY"
                    
                    # B. Hard Take Profit (Fixed Level - NOT Trailing)
                    elif curr_price >= pos_info['tp_price']:
                        should_sell = True
                        reason = "TAKE_PROFIT_HIT"
                        
                    # C. Hard Stop Loss (Fixed Level - NOT Trailing)
                    elif curr_price <= pos_info['sl_price']:
                        should_sell = True
                        reason = "STOP_LOSS_HIT"
                        
                except (ValueError, TypeError):
                    continue

            if should_sell:
                amount = pos_info["amount"]
                del self.positions[symbol]
                return {
                    "side": "SELL",
                    "symbol": symbol,
                    "amount": amount,
                    "reason": [reason]
                }

        # 2. Entry Logic
        if len(self.positions) >= self.params["pos_limit"]:
            return None

        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions:
                continue
                
            try:
                price = float(data["priceUsd"])
                liq = float(data.get("liquidity", 0))
                vol = float(data.get("volume24h", 0))
            except (ValueError, TypeError, KeyError):
                continue
            
            # Liquidity Filters
            if liq < self.params["min_liq"] or vol < self.params["min_vol"]:
                continue
                
            # Update History
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.params["window_size"] + 2)
            self.history[symbol].append(price)
            
            # Metric Calculation
            metrics = self._get_volatility_metrics(self.history[symbol])
            if not metrics:
                continue
                
            # Filter: Volatility must be non-zero
            if metrics["std_dev"] < 1e-9:
                continue
                
            # Z-Score: How many sigmas is the current move?
            # We assume mean return is approx 0 for this short window to detect pure impulse.
            z_score = metrics["current_return"] / metrics["std_dev"]
            
            # Entry Signal: Strong statistical deviation upwards
            if z_score > self.params["z_threshold"]:
                candidates.append({
                    "symbol": symbol,
                    "price": price,
                    "std_dev": metrics["std_dev"],
                    "z_score": z_score
                })

        # Execute Best Candidate
        if candidates:
            # Sort by Z-Score (Momentum Strength)
            best = max(candidates, key=lambda x: x["z_score"])
            
            # Calculate Sizing
            amount_usd = self.balance * self.params["trade_size_pct"]
            amount = amount_usd / best["price"]
            
            # Calculate FIXED Exit Levels (Bracket Order)
            # These do NOT move with price, satisfying the anti-Trailing-Stop requirement.
            vol_target = best["std_dev"]
            
            # Dynamic TP/SL width based on realized volatility
            tp_dist = vol_target * self.params["tp_multiplier"]
            sl_dist = vol_target * self.params["sl_multiplier"]
            
            tp_price = best["price"] * (1 + tp_dist)
            sl_price = best["price"] * (1 - sl_dist)
            
            self.positions[best["symbol"]] = {
                "amount": amount,
                "entry_price": best["price"],
                "tp_price": tp_price,
                "sl_price": sl_price,
                "ticks_held": 0
            }
            
            return {
                "side": "BUY",
                "symbol": best["symbol"],
                "amount": amount,
                "reason": ["IMPULSE_BREAKOUT", f"Z:{best['z_score']:.2f}"]
            }
            
        return None