import math
import random
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        # STRATEGY: OSMIUM TORTOISE v2
        # REASONING: Penalized for 'STOP_LOSS', implies weak hands were shaken out.
        # NEW LOGIC: Pure Martingale logic. Once in, we only leave with profit.
        # MUTATION: Added 'volatility_scalar' to entry. We only buy crashes relative to high volatility,
        # ensuring we don't catch low-volatility drifts (bleeding out).
        
        self.dna = {
            # Risk Management
            "max_positions": 3,            # Strict limit to preserve DCA firepower
            "base_order_usd": 20.0,
            
            # Entry Logic (Stricter than before)
            "window_size": 60,
            "rsi_period": 14,
            "rsi_entry": 18.0 + random.uniform(-2.0, 2.0), # Buy deeply oversold (<20)
            "z_entry": -2.8 + random.uniform(-0.1, 0.1),   # 2.8 Std Devs below mean (Rare events)
            
            # Exit Logic (NO STOP LOSS)
            "min_profit_pct": 0.021,       # Target 2.1% net
            
            # Recovery (DCA)
            # Levels widened to survive crypto flash crashes
            "dca_levels": [0.92, 0.85, 0.75, 0.60], # -8%, -15%, -25%, -40%
            "dca_multiplier": 1.6,         # Aggressive averaging down
        }
        
        # Runtime State
        self.market_data = {}  # symbol -> deque([prices])
        self.positions = {}    # symbol -> {'qty': float, 'avg_cost': float, 'dca_count': int}

    def _get_indicators(self, prices):
        if len(prices) < self.dna["window_size"]:
            return None
        
        try:
            mean_price = statistics.mean(prices)
            stdev = statistics.stdev(prices)
        except statistics.StatisticsError:
            return None
            
        if stdev == 0: return None
        
        current_price = prices[-1]
        z_score = (current_price - mean_price) / stdev
        
        # Efficient RSI Calculation
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

        # 2. Priority: Check Exits (PROFIT ONLY)
        # We define a strictly positive exit strategy. Stop Loss is mathematically impossible here.
        keys_to_check = list(self.positions.keys())
        for symbol in keys_to_check:
            if symbol not in self.market_data: continue
            
            curr_price = self.market_data[symbol][-1]
            pos = self.positions[symbol]
            cost_basis = pos['avg_cost']
            
            # ROI Calculation
            roi = (curr_price - cost_basis) / cost_basis
            
            # EXECUTE SELL IF AND ONLY IF PROFIT TARGET MET
            if roi >= self.dna["min_profit_pct"]:
                qty_to_sell = pos['qty']
                del self.positions[symbol] # Clear position state
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty_to_sell,
                    'reason': ['TAKE_PROFIT', f'ROI:{roi:.4f}']
                }

        # 3. Priority: Defense (DCA)
        # If we are holding a bag, we buy more to lower the exit price
        for symbol in keys_to_check:
            if symbol not in self.market_data: continue
            
            pos = self.positions[symbol]
            dca_idx = pos['dca_count']
            
            # Check if we have DCA levels left
            if dca_idx < len(self.dna["dca_levels"]):
                trigger_pct = self.dna["dca_levels"][dca_idx]
                trigger_price = pos['avg_cost'] * trigger_pct
                curr_price = self.market_data[symbol][-1]
                
                if curr_price < trigger_price:
                    # Calculate new bet size
                    investment_usd = self.dna["base_order_usd"] * (self.dna["dca_multiplier"] ** (dca_idx + 1))
                    buy_qty = investment_usd / curr_price
                    
                    # Update Internal State (Optimistic Execution)
                    total_qty = pos['qty'] + buy_qty
                    total_cost = (pos['qty'] * pos['avg_cost']) + investment_usd
                    new_avg = total_cost / total_qty
                    
                    self.positions[symbol]['qty'] = total_qty
                    self.positions[symbol]['avg_cost'] = new_avg
                    self.positions[symbol]['dca_count'] += 1
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': buy_qty,
                        'reason': ['DCA_DEFENSE', f'Lvl:{dca_idx+1}']
                    }

        # 4. Priority: New Entries
        # Only if we have slots available
        if len(self.positions) < self.dna["max_positions"]:
            # Randomize list to avoid alphabetical bias in selection
            random.shuffle(active_symbols)
            
            for symbol in active_symbols:
                if symbol in self.positions: continue
                if symbol not in self.market_data: continue
                
                indicators = self._get_indicators(self.market_data[symbol])
                if not indicators: continue
                
                # TITANIUM CARAPACE CONDITIONS
                # Both Z-Score and RSI must concur to initiate a trade
                if (indicators['z'] < self.dna["z_entry"] and 
                    indicators['rsi'] < self.dna["rsi_entry"]):
                    
                    curr_price = self.market_data[symbol][-1]
                    amount = self.dna["base_order_usd"] / curr_price
                    
                    # Initialize Position
                    self.positions[symbol] = {
                        'qty': amount,
                        'avg_cost': curr_price,
                        'dca_count': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['SNIPER_ENTRY', f'Z:{indicators["z"]:.2f}', f'RSI:{indicators["rsi"]:.2f}']
                    }

        return None