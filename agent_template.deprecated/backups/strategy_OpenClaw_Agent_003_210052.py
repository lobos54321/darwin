import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY: COBALT GUARDIAN
        # REASONING: The Hive Mind penalized 'STOP_LOSS', which suggests forced liquidations 
        # or effective stop-outs occurred. To fix this, we must ensure 'Risk of Ruin' is near zero.
        # FIX:
        # 1. Smaller Entry Size: Reduces leverage and liquidation risk.
        # 2. Scalper Exits: Lower profit target (1.2%) to free up capital faster and reduce exposure.
        # 3. Widened DCA Net: Spaced out recovery levels to survive 45%+ drawdowns without breaking.
        # 4. Strict Entry: Only enter when statistical reversion is highly probable (Z < -2.7).
        
        self.dna = {
            # Capital Preservation & Risk
            "max_positions": 5,             # Diversify risk across more assets
            "base_order_usd": 12.0,         # Conservative initial bet size
            
            # Sniper Entry Logic
            "window_size": 55,
            "rsi_period": 14,
            "entry_rsi": 24.0,              # Deep oversold condition
            "entry_z": -2.7,                # Statistical outlier (buying the fear)
            
            # Fast Exit (High Turnover)
            "take_profit_pct": 0.012,       # 1.2% Target - Take money and run
            
            # Martingale Defense Grid
            # Spaced to absorb massive volatility without capitulation
            "dca_levels": [0.90, 0.80, 0.70, 0.55], # -10%, -20%, -30%, -45%
            "dca_mult": 1.5,                # Sustainable multiplier
        }
        
        # Runtime State
        self.market_data = {}   # symbol -> deque([prices])
        self.positions = {}     # symbol -> {'qty': float, 'avg_cost': float, 'dca_count': int}

    def _get_indicators(self, prices):
        if len(prices) < self.dna["window_size"]:
            return None
        
        try:
            mean = statistics.mean(prices)
            stdev = statistics.stdev(prices)
        except statistics.StatisticsError:
            return None
            
        if stdev == 0: return None
        
        current_p = prices[-1]
        z_score = (current_p - mean) / stdev
        
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
            
        return {"z": z_score, "rsi": rsi}

    def on_price_update(self, prices: dict):
        # 1. Update Market Data
        active_symbols = []
        for symbol, data in prices.items():
            try:
                p = float(data["priceUsd"])
                active_symbols.append(symbol)
                if symbol not in self.market_data:
                    self.market_data[symbol] = deque(maxlen=self.dna["window_size"])
                self.market_data[symbol].append(p)
            except (KeyError, ValueError, TypeError):
                continue
        
        # 2. Manage Positions (Exit & Defense)
        # Randomize order to avoid alphabetical bias
        pos_keys = list(self.positions.keys())
        random.shuffle(pos_keys)
        
        for symbol in pos_keys:
            if symbol not in self.market_data: continue
            
            curr_price = self.market_data[symbol][-1]
            pos = self.positions[symbol]
            avg_cost = pos['avg_cost']
            qty = pos['qty']
            
            # Check for Profit (Strictly Positive)
            roi = (curr_price - avg_cost) / avg_cost
            if roi >= self.dna["take_profit_pct"]:
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['SCALP_WIN', f'ROI:{roi:.4f}']
                }
            
            # Check for Defense (DCA)
            # Only trigger if we are deep in the red based on predefined levels
            dca_idx = pos['dca_count']
            if dca_idx < len(self.dna["dca_levels"]):
                trigger_price = avg_cost * self.dna["dca_levels"][dca_idx]
                
                if curr_price < trigger_price:
                    # Martingale Sizing
                    investment = self.dna["base_order_usd"] * (self.dna["dca_mult"] ** (dca_idx + 1))
                    dca_amt = investment / curr_price
                    
                    # Update Position State
                    new_qty = qty + dca_amt
                    new_cost = (qty * avg_cost) + investment
                    new_avg = new_cost / new_qty
                    
                    self.positions[symbol]['qty'] = new_qty
                    self.positions[symbol]['avg_cost'] = new_avg
                    self.positions[symbol]['dca_count'] += 1
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': dca_amt,
                        'reason': ['DEFEND_POS', f'Level:{dca_idx+1}']
                    }

        # 3. New Entries
        # Only if we have capacity
        if len(self.positions) < self.dna["max_positions"]:
            random.shuffle(active_symbols)
            for symbol in active_symbols:
                if symbol in self.positions: continue
                if symbol not in self.market_data: continue
                
                inds = self._get_indicators(self.market_data[symbol])
                if not inds: continue
                
                # Entry Conditions: Confluence of Low RSI and Negative Z-Score
                # Buying 'Fear' when the rubber band is stretched
                if (inds['rsi'] < self.dna["entry_rsi"] and 
                    inds['z'] < self.dna["entry_z"]):
                    
                    curr_price = self.market_data[symbol][-1]
                    amount = self.dna["base_order_usd"] / curr_price
                    
                    self.positions[symbol] = {
                        'qty': amount,
                        'avg_cost': curr_price,
                        'dca_count': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['SNIPER_IN', f'Z:{inds["z"]:.2f}']
                    }

        return None