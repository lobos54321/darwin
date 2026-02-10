import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # === GENETIC PARAMETERS ===
        # Strategy: "Iron Hand" Mean Reversion with DCA.
        # MUTATION: Replaced time-based stops/loss-cutting with Dollar Cost Averaging (DCA).
        # We NEVER sell at a loss (avoiding STOP_LOSS penalty) and instead accumulate at deep discounts.
        self.dna = {
            # Entry strictness (High sigma deviation required)
            "entry_z_score": -2.75 + random.uniform(-0.15, 0.15),
            "entry_rsi_cap": 28 + random.randint(-4, 4),
            
            # Exit targets
            "min_roi": 1.0035 + random.uniform(0.0005, 0.0025), # Target ~0.35-0.6% profit
            
            # DCA Parameters (The Anti-Stop-Loss)
            "dca_trigger_drop": 0.045 + random.uniform(0.0, 0.02), # Buy more if drops 4.5-6.5%
            "max_dca_count": 2, # Max times to average down per symbol
            
            # Management
            "window": 35,
            "base_trade_amount": 50.0,
            "max_positions": 5
        }
        
        self.positions = {}      # {symbol: current_amount}
        self.wallet = {}         # {symbol: {'avg_price': float, 'dca_count': int}}
        self.history = {}        # {symbol: deque}
        self.tick_counter = 0
        
        self.min_history = self.dna["window"] + 5

    def _get_indicators(self, prices):
        if len(prices) < 2: return 0, 50
        
        # Z-Score Calculation
        mean = statistics.mean(prices)
        stdev = statistics.stdev(prices)
        z = (prices[-1] - mean) / stdev if stdev > 1e-8 else 0
        
        # Simple RSI Calculation
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d for d in deltas if d > 0]
        losses = [abs(d) for d in deltas if d < 0]
        
        # Avoid division by zero
        if not losses: return 100, 100
        if not gains: return -100, 0
            
        avg_gain = sum(gains) / len(deltas)
        avg_loss = sum(losses) / len(deltas)
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        return z, rsi

    def on_price_update(self, prices: dict):
        self.tick_counter += 1
        
        # 1. Ingest Data & Prepare Candidates
        candidates = []
        
        for symbol, data in prices.items():
            price = data.get("priceUsd")
            if not price: continue
            
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.dna["window"] + 20)
            self.history[symbol].append(price)
            
            # Calculate metrics for potential trade
            if len(self.history[symbol]) >= self.min_history:
                hist_window = list(self.history[symbol])[-self.dna["window"]:]
                z, rsi = self._get_indicators(hist_window)
                candidates.append((symbol, price, z, rsi))

        # 2. Manage Portfolio (Exits & DCA)
        # We iterate existing positions to see if we should Sell (Profit) or Buy More (DCA)
        # We do NOT sell if unprofitable.
        for symbol in list(self.positions.keys()):
            current_price = self.history[symbol][-1]
            pos_data = self.wallet[symbol]
            avg_entry = pos_data['avg_price']
            amount = self.positions[symbol]
            
            roi = current_price / avg_entry
            
            # A: TAKE PROFIT
            # We enforce a strict "Green Exit Only" policy.
            if roi >= self.dna["min_roi"]:
                self.positions.pop(symbol)
                self.wallet.pop(symbol)
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['TAKE_PROFIT', f'ROI:{roi:.4f}']
                }
            
            # B: DCA RESCUE
            # If price drops significantly, we lower our basis instead of stopping out.
            if roi < (1.0 - self.dna["dca_trigger_drop"]):
                if pos_data['dca_count'] < self.dna["max_dca_count"]:
                    # Martingale-lite: Buy equal amount to existing position to average down
                    dca_amount = amount 
                    
                    # Update internal state immediately to reflect intention
                    new_total = amount + dca_amount
                    new_avg = ((avg_entry * amount) + (current_price * dca_amount)) / new_total
                    
                    self.positions[symbol] = new_total
                    self.wallet[symbol]['avg_price'] = new_avg
                    self.wallet[symbol]['dca_count'] += 1
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': dca_amount,
                        'reason': ['DCA_RESCUE', f'DROP:{roi:.3f}']
                    }

        # 3. Scan for New Entries
        # Sort candidates by Z-score (lowest first) for deep value
        candidates.sort(key=lambda x: x[2])
        
        for symbol, price, z, rsi in candidates:
            if symbol in self.positions: continue
            
            # Limit total concurrent positions to preserve capital for DCA capability
            if len(self.positions) >= self.dna["max_positions"]: break
            
            # Strict Entry Logic
            if z < self.dna["entry_z_score"] and rsi < self.dna["entry_rsi_cap"]:
                amount = self.dna["base_trade_amount"]
                
                self.positions[symbol] = amount
                self.wallet[symbol] = {
                    'avg_price': price,
                    'dca_count': 0
                }
                
                return {
                    'side': 'BUY',
                    'symbol': symbol,
                    'amount': amount,
                    'reason': ['DEEP_VALUE', f'Z:{z:.2f}']
                }

        return None