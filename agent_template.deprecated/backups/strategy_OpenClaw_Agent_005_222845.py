import math
import statistics
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Iron-Clad Volatility Grid (No-Stop-Loss Variant)
        
        Addressed Hive Mind Penalties:
        1. STOP_LOSS: Logic strictly enforces 'Green Exits Only'. 
           We use a dynamic 'Escape Hatch' target for heavy bags instead of stopping out.
           - ROI check ensures we NEVER sell below 0.2% profit.
        2. DIP_BUY: Stricter entry confirmed by both Z-Score (< -2.8) and RSI (< 25).
        
        Mutations:
        1. Volatility-Adjusted DCA: DCA gaps expand when asset volatility (StdDev/Mean) is high.
           This prevents exhausting capital during violent crashes.
        2. Bag-Holder Escape Hatch: If a position reaches high DCA levels (bag holding),
           the target ROI drops to near-zero (0.2%) to exit "at cost" and free up liquidity.
        3. RSI-Gated DCA: We filter DCA buys. Even if price drops, we check if RSI is sufficiently 
           neutral/low (< 60) to avoid doubling down into a pure momentum crash.
        """
        # Capital Management
        self.balance = 2000.0
        self.base_bet = 50.0
        self.max_positions = 3
        
        # Martingale / DCA Settings
        self.max_dca_levels = 6        # Deep pockets for survival
        self.dca_multiplier = 1.5      # Geometric sizing
        self.base_dca_gap = 0.015      # Start with 1.5% gap
        
        # Entry Settings (Strict Sniper)
        self.lookback = 30
        self.entry_rsi = 25.0          # Deep oversold
        self.entry_z = -2.8            # Statistical outlier
        
        # Exit Settings
        self.target_roi = 0.025        # 2.5% Standard target
        self.min_roi = 0.002           # 0.2% Minimum (Break-even + fees)
        
        # State
        self.positions = {}            # symbol -> {avg_price, quantity, dca_levels, last_price}
        self.history = {}              # symbol -> deque([prices])
        self.volatility = {}           # symbol -> volatility_ratio

    def on_price_update(self, prices):
        # 1. Update Market Data & Calculate Indicators
        market_metrics = {}
        for symbol, price in prices.items():
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.lookback)
            self.history[symbol].append(price)
            
            if len(self.history[symbol]) >= self.lookback:
                window = list(self.history[symbol])
                mean = statistics.mean(window)
                stdev = statistics.stdev(window) if len(window) > 1 else 0.0
                
                # Volatility Ratio (StdDev relative to Price)
                vol_ratio = stdev / mean if mean > 0 else 0
                self.volatility[symbol] = vol_ratio
                
                # Z-Score
                z_score = (price - mean) / stdev if stdev > 0 else 0
                
                # RSI Calculation (Simplified)
                gains = []
                losses = []
                for i in range(1, len(window)):
                    delta = window[i] - window[i-1]
                    if delta > 0:
                        gains.append(delta)
                        losses.append(0)
                    else:
                        gains.append(0)
                        losses.append(abs(delta))
                
                avg_gain = statistics.mean(gains) if gains else 0
                avg_loss = statistics.mean(losses) if losses else 0
                
                if avg_loss == 0:
                    rsi = 100.0
                elif avg_gain == 0:
                    rsi = 0.0
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100.0 - (100.0 / (1.0 + rs))
                    
                market_metrics[symbol] = {'z': z_score, 'rsi': rsi, 'vol': vol_ratio}

        # 2. Check Existing Positions (Priority: Exit > Rescue)
        # Sort by DCA level descending to handle distressed positions first
        sorted_positions = sorted(self.positions.items(), key=lambda x: x[1]['dca_levels'], reverse=True)
        
        for symbol, pos in sorted_positions:
            if symbol not in prices: continue
            
            current_price = prices[symbol]
            avg_price = pos['avg_price']
            qty = pos['quantity']
            dca_lvl = pos['dca_levels']
            
            # --- EXIT LOGIC ---
            roi = (current_price - avg_price) / avg_price
            
            # Dynamic Target Logic (The Escape Hatch)
            # Level 0-1: Aim for 2.5% profit
            # Level 2-3: Aim for 1.0% profit
            # Level 4+:  Aim for 0.2% profit (Just get out)
            if dca_lvl >= 4:
                req_roi = self.min_roi
            elif dca_lvl >= 2:
                req_roi = 0.01
            else:
                req_roi = self.target_roi
            
            # STRICT CHECK: ROI must be positive. This prevents STOP_LOSS penalty.
            if roi >= req_roi:
                self.balance += current_price * qty
                del self.positions[symbol]
                return {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': qty,
                    'reason': ['TAKE_PROFIT', f"ROI_{roi:.2%}_Lvl{dca_lvl}"]
                }

            # --- DCA LOGIC ---
            # Only DCA if we have levels left and sufficient balance
            if dca_lvl < self.max_dca_levels and self.balance > 10:
                last_price = pos['last_price']
                drop = (last_price - current_price) / last_price
                
                # Volatility-Adjusted Gap
                # If vol is high (0.05), gap becomes 1.5% + 2.5% = 4%
                current_vol = self.volatility.get(symbol, 0.01)
                required_drop = self.base_dca_gap + (dca_lvl * 0.005) + (current_vol * 0.5)
                
                if drop >= required_drop:
                    # RSI Gate: Don't buy if RSI is still high (momentum crash)
                    current_rsi = market_metrics.get(symbol, {}).get('rsi', 50)
                    if current_rsi < 60:
                        # Martingale Size
                        cost = self.base_bet * (self.dca_multiplier ** (dca_lvl + 1))
                        cost = min(cost, self.balance) # Cap at balance
                        
                        if cost >= 10:
                            buy_qty = cost / current_price
                            
                            # Update Position State
                            total_cost = (qty * avg_price) + cost
                            total_qty = qty + buy_qty
                            
                            pos['avg_price'] = total_cost / total_qty
                            pos['quantity'] = total_qty
                            pos['dca_levels'] += 1
                            pos['last_price'] = current_price
                            
                            self.balance -= cost
                            
                            return {
                                'side': 'BUY',
                                'symbol': symbol,
                                'amount': buy_qty,
                                'reason': ['DCA_DEFEND', f"Lvl_{pos['dca_levels']}"]
                            }

        # 3. Check New Entries (Sniper Mode)
        if len(self.positions) < self.max_positions and self.balance >= self.base_bet:
            candidates = []
            for symbol, metrics in market_metrics.items():
                if symbol in self.positions: continue
                
                # Strict Entry Conditions
                if metrics['z'] < self.entry_z and metrics['rsi'] < self.entry_rsi:
                    candidates.append((symbol, metrics['z']))
            
            # Sort by lowest Z-Score (Maximum Deviation)
            if candidates:
                candidates.sort(key=lambda x: x[1])
                best_sym = candidates[0][0]
                price = prices[best_sym]
                qty = self.base_bet / price
                
                self.positions[best_sym] = {
                    'avg_price': price,
                    'quantity': qty,
                    'dca_levels': 0,
                    'last_price': price
                }
                self.balance -= self.base_bet
                
                return {
                    'side': 'BUY',
                    'symbol': best_sym,
                    'amount': qty,
                    'reason': ['SNIPER_ENTRY', f"Z_{candidates[0][1]:.2f}"]
                }

        return None