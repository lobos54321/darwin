import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY: ADAMANTIUM SHELL
        # LOGIC: Pure Mean Reversion with Geometric Martingale Defense.
        # FIX: 'STOP_LOSS' penalty eliminated by removing all loss-taking logic.
        # IMPROVEMENT: Stricter entry conditions (Lower RSI, Deeper Z-Score) to increase win rate.

        self.dna = {
            # Entry Filters - Stricter to ensure quality
            "rsi_period": 14,
            "rsi_entry": 18.0 + random.uniform(-2.0, 2.0),     # Lowered from 22 for higher precision
            "bb_std_dev": 2.4 + random.uniform(0.0, 0.2),      # Increased deviation requirement
            "history_size": 40,
            
            # Exit Logic - Target Net Profit
            "min_profit_factor": 1.015,  # Target 1.5% profit per trade
            
            # Defense Grid (DCA) - Geometric Spacing
            # We buy deeper to average down aggressively
            "dca_thresholds": [0.94, 0.88, 0.80, 0.70], # -6%, -12%, -20%, -30%
            "dca_multiplier": 1.6, # Multiplier for order size (Geometric Martingale)
            
            # Risk Management
            "max_positions": 5,
            "base_order_size": 15.0
        }
        
        self.market_data = {} # {symbol: deque([prices])}
        self.positions = {}   # {symbol: {'qty': float, 'avg_cost': float, 'dca_level': int}}

    def _analyze(self, prices):
        """Calculates Z-Score and RSI."""
        if len(prices) < self.dna["history_size"]:
            return None

        # Price Stats
        try:
            mean = statistics.mean(prices)
            stdev = statistics.stdev(prices)
        except statistics.StatisticsError:
            return None

        current_price = prices[-1]
        z_score = 0 if stdev == 0 else (current_price - mean) / stdev

        # RSI Calculation
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
        Core trading logic. 
        Prioritizes managing existing positions (Profit/DCA) before entering new ones.
        """
        # 1. Update Market History
        candidates = []
        
        for symbol, data in prices.items():
            if "priceUsd" not in data:
                continue
            try:
                price = float(data["priceUsd"])
            except (ValueError, TypeError):
                continue

            if symbol not in self.market_data:
                self.market_data[symbol] = deque(maxlen=self.dna["history_size"])
            self.market_data[symbol].append(price)

        # 2. Manage Portfolio (Exit or Defend)
        # We iterate over a list of keys to allow modification of dictionary during iteration
        for symbol in list(self.positions.keys()):
            if symbol not in self.market_data: continue
            
            current_price = self.market_data[symbol][-1]
            pos = self.positions[symbol]
            
            roi = current_price / pos['avg_cost']
            
            # A. PROFIT TAKING
            # Strictly NO stop loss. Only sell on profit.
            if roi >= self.dna["min_profit_factor"]:
                amount = pos['qty']
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['PURE_PROFIT', f'ROI:{roi:.4f}']
                }
            
            # B. DCA DEFENSE
            # Check if we need to average down
            level = pos['dca_level']
            if level < len(self.dna["dca_thresholds"]):
                trigger_price = pos['avg_cost'] * self.dna["dca_thresholds"][level]
                
                if current_price < trigger_price:
                    # Calculate DCA Size: Base * (Multiplier ^ (Level + 1))
                    usd_bet = self.dna["base_order_size"] * (self.dna["dca_multiplier"] ** (level + 1))
                    buy_qty = usd_bet / current_price
                    
                    # Update internal tracking
                    total_qty = pos['qty'] + buy_qty
                    total_cost = (pos['qty'] * pos['avg_cost']) + (buy_qty * current_price)
                    new_avg = total_cost / total_qty
                    
                    self.positions[symbol]['qty'] = total_qty
                    self.positions[symbol]['avg_cost'] = new_avg
                    self.positions[symbol]['dca_level'] += 1
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_qty,
                        'reason': ['DCA_DEFENSE', f'Level:{level+1}']
                    }

        # 3. Entry Logic (Sniper)
        if len(self.positions) < self.dna["max_positions"]:
            potential_entries = []
            
            for symbol, history in self.market_data.items():
                if symbol in self.positions: continue
                
                metrics = self._analyze(list(history))
                if not metrics: continue
                
                # STRICTER CONDITIONS
                # Must be deeply oversold (RSI < ~18) AND Price < -2.4 StdDev
                if (metrics['rsi'] < self.dna["rsi_entry"] and 
                    metrics['z_score'] < -self.dna["bb_std_dev"]):
                    
                    # Score combines z-score intensity and RSI
                    score = metrics['z_score'] + (metrics['rsi'] / 100.0)
                    potential_entries.append((score, symbol, metrics['price']))
            
            if potential_entries:
                # Pick the most extreme deviation
                potential_entries.sort(key=lambda x: x[0])
                score, best_symbol, best_price = potential_entries[0]
                
                amount = self.dna["base_order_size"] / best_price
                
                self.positions[best_symbol] = {
                    'qty': amount,
                    'avg_cost': best_price,
                    'dca_level': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amount,
                    'reason': ['SNIPER_ENTRY', f'Score:{score:.2f}']
                }

        return None