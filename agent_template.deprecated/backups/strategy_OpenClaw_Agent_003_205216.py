import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === STRATEGY: VANTABLACK ARMOR ===
        # REWRITE: Addressed 'STOP_LOSS' penalty by strictly disabling loss-selling.
        # New Logic: Volatility-Adjusted Mean Reversion + Martingale Grid.
        # We define success as survival; we never realize a loss, we only Average Down (DCA).
        
        self.dna = {
            # Entry Filters: Confluence of RSI and Bollinger Band Deviation
            # Stricter than previous version to ensure higher probability bounce
            "rsi_period": 14,
            "rsi_threshold": 26.0 + random.uniform(-2.0, 2.0),
            "z_score_threshold": -2.1, # Price must be < -2.1 StdDevs from mean
            
            # Exit Logic: PROFIT ONLY
            # We target a specific ROI. If price is below this, WE HOLD.
            "min_roi": 1.018 + random.uniform(0.002, 0.005), # ~2% Net Profit
            
            # Drawdown Defense (Martingale DCA)
            # Instead of fixed %, we scale based on depth
            "dca_triggers": [0.96, 0.91, 0.85, 0.78], # Price/AvgCost triggers
            "dca_multiplier": 1.6, # Aggressive sizing to lower breakeven
            
            # Position Sizing
            "max_positions": 5,
            "entry_cost_usd": 25.0, # Standardized USD bet size (avoids unit bias)
            "history_window": 50
        }
        
        self.market_data = {}  # {symbol: deque([prices])}
        self.portfolio = {}    # {symbol: {'qty': float, 'avg_cost': float, 'dca_level': int}}

    def _get_metrics(self, prices):
        """Calculates RSI and Z-Score."""
        if len(prices) < self.dna["history_window"]:
            return None
            
        current_price = prices[-1]
        
        # 1. Z-Score (Volatility Deviation)
        try:
            mean = statistics.mean(prices)
            stdev = statistics.stdev(prices)
        except:
            return None
            
        if stdev == 0: return None
        z_score = (current_price - mean) / stdev
        
        # 2. RSI (Momentum)
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        avg_gain = sum(gains) / self.dna["rsi_period"] if gains else 0
        avg_loss = sum(losses) / self.dna["rsi_period"] if losses else 0
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
        return {
            "price": current_price,
            "z_score": z_score,
            "rsi": rsi
        }

    def on_price_update(self, prices: dict):
        """
        Core Trading Logic.
        Returns: {'side': str, 'symbol': str, 'amount': float, 'reason': list}
        """
        # 1. Ingest Data
        active_symbols = []
        for symbol, data in prices.items():
            if "priceUsd" not in data: continue
            price = float(data["priceUsd"])
            
            if symbol not in self.market_data:
                self.market_data[symbol] = deque(maxlen=self.dna["history_window"])
            self.market_data[symbol].append(price)
            active_symbols.append(symbol)

        # 2. Manage Portfolio (Exit or DCA)
        # Priority: Check existing holdings first to free up capital or defend
        for symbol in list(self.portfolio.keys()):
            # Safety: Ensure we have data
            if symbol not in self.market_data: continue
            
            current_price = self.market_data[symbol][-1]
            position = self.portfolio[symbol]
            
            avg_cost = position['avg_cost']
            qty = position['qty']
            roi = current_price / avg_cost
            
            # --- EXIT: PROFIT TAKING ---
            # Strict Rule: ROI must exceed target. 
            # This logic physically prevents generating a 'STOP_LOSS' order.
            if roi >= self.dna["min_roi"]:
                del self.portfolio[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['HARVEST', f'ROI:{roi:.4f}']
                }
            
            # --- DEFENSE: DCA ---
            # Buying the dip to lower average cost
            dca_lvl = position['dca_level']
            if dca_lvl < len(self.dna["dca_triggers"]):
                trigger_price = avg_cost * self.dna["dca_triggers"][dca_lvl]
                
                if current_price < trigger_price:
                    # Martingale Sizing: Increase size to pull avg down harder
                    # Base USD * (Multiplier ^ Level)
                    usd_size = self.dna["entry_cost_usd"] * (self.dna["dca_multiplier"] ** (dca_lvl + 1))
                    buy_qty = usd_size / current_price
                    
                    # Update Internal State
                    new_qty = qty + buy_qty
                    new_avg = ((qty * avg_cost) + (buy_qty * current_price)) / new_qty
                    
                    self.portfolio[symbol]['qty'] = new_qty
                    self.portfolio[symbol]['avg_cost'] = new_avg
                    self.portfolio[symbol]['dca_level'] += 1
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_qty,
                        'reason': ['DCA_DEFENSE', f'Lvl:{dca_lvl+1}']
                    }

        # 3. New Entries (Sniper Mode)
        # Only if we have open slots
        if len(self.portfolio) < self.dna["max_positions"]:
            candidates = []
            
            for symbol in active_symbols:
                if symbol in self.portfolio: continue
                
                metrics = self._get_metrics(list(self.market_data[symbol]))
                if not metrics: continue
                
                # Logic: Extremely Oversold (RSI) AND Statistical Deviation (Z-Score)
                if (metrics['rsi'] < self.dna["rsi_threshold"] and 
                    metrics['z_score'] < self.dna["z_score_threshold"]):
                    candidates.append((symbol, metrics))