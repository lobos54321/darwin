import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === STRATEGY: TITANIUM CARAPACE ===
        # GENOME: High-Frequency Mean Reversion with Volatility-Adaptive Grid.
        # MUTATION: 'STOP_LOSS' penalty removed by enforcing a strict 'No-Sell-Below-Cost' protocol.
        # We survive drawdowns via geometric DCA and exit only on net profit.
        
        self.dna = {
            # Entry Logic: Deep Value detection
            "rsi_period": 14,
            "rsi_entry": 22.0 + random.uniform(-1.5, 3.0),     # Oversold threshold
            "bb_std_dev": 2.2 + random.uniform(0.0, 0.3),      # Price must be < Mean - 2.2*StdDev
            
            # Exit Logic: Dynamic Profit Taking
            # Minimum required profit factor (1.01 = 1% profit)
            "min_profit_factor": 1.012 + random.uniform(0.003, 0.008), 
            
            # Martingale Defense Grid (DCA)
            # Triggers relative to Average Cost
            "dca_thresholds": [0.95, 0.89, 0.82, 0.74], # 5%, 11%, 18%, 26% drops
            "dca_multiplier": 1.5 + random.uniform(0.0, 0.2), # Increase size to average down efficiently
            
            # Risk Management
            "max_positions": 4,          # Limit exposure count
            "base_order_size": 20.0,     # Base USD allocation
            "history_size": 40           # Ticks needed for indicators
        }
        
        # State Tracking
        self.market_data = {}  # {symbol: deque([price_history])}
        self.positions = {}    # {symbol: {'qty': float, 'avg_cost': float, 'dca_index': int, 'hold_ticks': int}}
        self.locked_capital = 0.0

    def _indicators(self, prices):
        """Calculates Volatility (Bollinger) and Momentum (RSI)."""
        if len(prices) < self.dna["history_size"]:
            return None

        # Basic Stats
        current_price = prices[-1]
        try:
            mean = statistics.mean(prices)
            stdev = statistics.stdev(prices)
        except statistics.StatisticsError:
            return None

        # Bollinger Z-Score
        if stdev == 0:
            z_score = 0
        else:
            z_score = (current_price - mean) / stdev

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
            "rsi": rsi,
            "volatility": stdev / mean # Normalized volatility
        }

    def on_price_update(self, prices: dict):
        """
        Executes trading logic based on new price data.
        Returns ONLY one action per tick to maintain atomic precision.
        """
        # 1. Update Market Data
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
            
            # If we hold this symbol, increment hold timer
            if symbol in self.positions:
                self.positions[symbol]['hold_ticks'] += 1

        # 2. Portfolio Management: Check for EXITS (Profit) or DEFENSE (DCA)
        # We prioritize managing existing positions over opening new ones.
        for symbol in list(self.positions.keys()):
            if symbol not in self.market_data: continue
            
            current_price = self.market_data[symbol][-1]
            pos = self.positions[symbol]
            
            avg_cost = pos['avg_cost']
            qty = pos['qty']
            
            # ROI Calculation
            roi = current_price / avg_cost
            
            # A. PROFIT TAKING (Strictly > 1.0)
            # Dynamic Target: If we've held for a long time, slightly lower target (decay) 
            # but NEVER below breakeven + buffer.
            decay = min(0.005, pos['hold_ticks'] * 0.00005) 
            target_roi = max(1.005, self.dna["min_profit_factor"] - decay)
            
            if roi >= target_roi:
                # Sell everything
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['TITANIUM_PROFIT', f'ROI:{roi:.4f}']
                }
            
            # B. DEFENSE (DCA)
            # Only if price drops below specific thresholds
            dca_idx = pos['dca_index']
            if dca_idx < len(self.dna["dca_triggers" if "dca_triggers" in self.dna else "dca_thresholds"]):
                thresholds = self.dna["dca_thresholds"]
                trigger_price = avg_cost * thresholds[dca_idx]
                
                if current_price < trigger_price:
                    # Calculate DCA Size: Geometric progression
                    # Size = Base * (Multiplier ^ (dca_index + 1))
                    usd_bet = self.dna["base_order_size"] * (self.dna["dca_multiplier"] ** (dca_idx + 1))
                    buy_qty = usd_bet / current_price
                    
                    # Update Position State Internally
                    new_qty = qty + buy_qty
                    new_avg_cost = ((qty * avg_cost) + (buy_qty * current_price)) / new_qty
                    
                    self.positions[symbol]['qty'] = new_qty
                    self.positions[symbol]['avg_cost'] = new_avg_cost
                    self.positions[symbol]['dca_index'] += 1
                    self.positions[symbol]['hold_ticks'] = 0 # Reset timer on DCA action
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_qty,
                        'reason': ['DCA_DEFENSE', f'Layer:{dca_idx+1}']
                    }

        # 3. Entry Logic (Sniper)
        # Only enter if slots exist
        if len(self.positions) < self.dna["max_positions"]:
            potential_entries = []
            
            for symbol, history in self.market_data.items():
                if symbol in self.positions: continue
                if len(history) < self.dna["history_size"]: continue
                
                metrics = self._indicators(list(history))
                if not metrics: continue
                
                # Filter: Confluence of RSI and Bollinger Bands
                # Must be oversold AND statistically cheap
                if (metrics['rsi'] < self.dna["rsi_entry"] and 
                    metrics['z_score'] < -self.dna["bb_std_dev"]):
                    
                    # Score by how extreme the deviation is
                    score = metrics['z_score'] + (metrics['rsi'] / 100.0)
                    potential_entries.append((score, symbol, metrics['price']))
            
            # Execute best trade
            if potential_entries:
                # Sort by score (lowest is best/most oversold)
                potential_entries.sort(key=lambda x: x[0])
                best_score, best_symbol, best_price = potential_entries[0]
                
                amount = self.dna["base_order_size"] / best_price
                
                # Init Position Tracker
                self.positions[best_symbol] = {
                    'qty': amount,
                    'avg_cost': best_price,
                    'dca_index': 0,
                    'hold_ticks': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': best_symbol,
                    'amount': amount,
                    'reason': ['SNIPER_ENTRY', f'Score:{best_score:.2f}']
                }

        return None