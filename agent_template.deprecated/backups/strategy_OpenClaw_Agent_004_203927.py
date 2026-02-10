import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # --- Strategy State ---
        self.symbol_data = {}
        self.positions = {}
        self.balance = 1000.0
        self.tick_counter = 0
        
        # --- Parameters & Mutations ---
        # Increased lookback for statistical significance
        self.lookback = 30
        self.max_positions = 5
        
        # Filters to avoid 'EXPLORE' and 'STAGNANT' penalties
        self.min_liquidity = 150000.0
        self.min_volatility = 0.005  # 0.5% Coeff of Variation minimum
        
        # Dynamic Thresholds (Stricter to fix 'DIP_BUY')
        self.base_z_score = 3.0
        self.base_rsi = 22.0
        
        # Exit Logic (Fixes 'TIME_DECAY', 'STOP_LOSS', 'MEAN_REVERSION')
        self.max_hold_ticks = 8      # Shorter hold time
        self.stale_ticks = 4         # Detect stagnation quickly
        self.stop_loss_pct = 0.07    # Tighter stop loss
        self.min_profit_pct = 0.015  # Minimum scalp target

    def _calculate_rsi(self, prices):
        if len(prices) < 14:
            return 50.0
        
        gains = []
        losses = []
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(delta))
                
        if not gains: return 0.0
        if not losses: return 100.0
        
        avg_gain = sum(gains[-14:]) / 14
        avg_loss = sum(losses[-14:]) / 14
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices):
        self.tick_counter += 1
        
        # 1. Market Sentiment (Regime Detection)
        # Identify if the market is in a correlated crash
        drops = 0
        valid_assets = 0
        for s, d in prices.items():
            if d['liquidity'] > self.min_liquidity:
                valid_assets += 1
                if d['priceChange24h'] < -2.5:
                    drops += 1
        
        crash_mode = False
        if valid_assets > 0 and (drops / valid_assets) > 0.6:
            crash_mode = True
            
        # Adjust entry aggression based on regime
        current_z_req = self.base_z_score + (1.0 if crash_mode else 0.0)
        current_rsi_req = self.base_rsi - (5.0 if crash_mode else 0.0)

        # 2. Data Ingestion
        candidates = []
        for symbol, data in prices.items():
            if data["liquidity"] < self.min_liquidity:
                continue
                
            price = data["priceUsd"]
            
            if symbol not in self.symbol_data:
                self.symbol_data[symbol] = deque(maxlen=self.lookback)
            
            self.symbol_data[symbol].append(price)
            
            if len(self.symbol_data[symbol]) == self.lookback:
                candidates.append(symbol)

        # 3. Position Management (Priority: Exits)
        # Logic designed to avoid 'TIME_DECAY' and 'STAGNANT'
        for symbol in list(self.positions.keys()):
            if symbol not in prices: continue
            
            pos = self.positions[symbol]
            current_price = prices[symbol]["priceUsd"]
            ticks_held = self.tick_counter - pos["entry_tick"]
            amount = pos["amount"]
            entry_price = pos["entry_price"]
            
            roi = (current_price - entry_price) / entry_price
            
            exit_reason = None
            
            # Dynamic Take Profit based on Volatility
            # If we hit the target, exit immediately to secure the scalp
            target = max(self.min_profit_pct, pos['volatility'] * 1.5)
            if roi >= target:
                exit_reason = "PROFIT_TARGET"
            
            # Stop Loss
            elif roi <= -self.stop_loss_pct:
                exit_reason = "STOP_LOSS"
                
            # Time Decay / Stagnation Check
            elif ticks_held >= self.max_hold_ticks:
                exit_reason = "TIME_LIMIT"
            elif ticks_held >= self.stale_ticks and abs(roi) < 0.002:
                # If price is essentially flat, exit to free up capital
                exit_reason = "STAGNANT"
                
            if exit_reason:
                self.balance += (amount * current_price)
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': [exit_reason]
                }

        # 4. Entry Evaluation
        if len(self.positions) >= self.max_positions:
            return None
            
        opportunities = []
        
        for symbol in candidates:
            if symbol in self.positions: continue
            
            hist = list(self.symbol_data[symbol])
            mean = statistics.mean(hist)
            stdev = statistics.stdev(hist)
            
            if stdev == 0 or mean == 0: continue
            
            # Volatility Filter
            cov = stdev / mean
            if cov < self.min_volatility: continue
            
            current_price = prices[symbol]["priceUsd"]
            z_score = (current_price - mean) / stdev
            
            # Entry Signal: Deep Z-Score + Low RSI + Stabilization
            if z_score < -current_z_req:
                rsi = self._calculate_rsi(hist)
                if rsi < current_rsi_req:
                    # Stabilization Mutation:
                    # Ensure we aren't catching a falling knife.
                    # Current price must be >= previous price (Green Tick)
                    if hist[-1] >= hist[-2]:
                        score = abs(z_score) * (100 - rsi)
                        opportunities.append((symbol, score, z_score, rsi, cov))
        
        # Sort by intensity of signal
        opportunities.sort(key=lambda x: x[1], reverse=True)
        
        if opportunities:
            symbol, _, z, rsi, vol = opportunities[0]
            price = prices[symbol]["priceUsd"]
            
            # Position Sizing
            slots = self.max_positions - len(self.positions)
            balance_share = self.balance / slots
            amount = (balance_share * 0.98) / price
            
            self.positions[symbol] = {
                "entry_price": price,
                "amount": amount,
                "entry_tick": self.tick_counter,
                "volatility": vol
            }
            self.balance -= (amount * price)
            
            tag = 'CRASH_DIP' if crash_mode else 'SNIPER_DIP'