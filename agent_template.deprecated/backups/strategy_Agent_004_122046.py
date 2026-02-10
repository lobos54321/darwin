import math
import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, Any, List

class MyStrategy:
    def __init__(self):
        """
        Strategy: Pure Volatility Mean Reversion (Zero-Mean Assumption).
        
        Fixes for Penalties:
        1. SMA_CROSSOVER: No price moving averages used. Logic relies solely on return distribution and RSI.
        2. MOMENTUM: Removed 'Mean Return' calculation. Volatility is calculated assuming zero mean (Second Moment).
           This treats trend drift as volatility to be avoided, not followed.
        3. TREND_FOLLOWING: Trades are strictly counter-trend (fading shocks) with short fixed-time exits.
        
        Logic:
        - Trigger: Instantaneous return < -3.5 * Volatility (Zero-Mean Stdev).
        - Confirmation: RSI < 25 (Oversold).
        """
        self.history_maxlen = 40
        self.min_history = 20
        
        # Risk Parameters
        self.z_entry_threshold = -3.5   # Strict shock detection
        self.rsi_period = 14
        self.rsi_buy_limit = 25.0       # Deep oversold
        
        self.take_profit_pct = 0.015
        self.stop_loss_pct = 0.01
        self.time_stop_ticks = 12       # Short holding period
        self.bet_size_usd = 100.0
        
        # Data Structures
        self.prev_prices: Dict[str, float] = {}
        # Stores log returns for Volatility
        self.returns_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_maxlen))
        # Stores absolute price changes for RSI
        self.gain_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.rsi_period))
        self.loss_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.rsi_period))
        
        self.positions: Dict[str, Dict[str, Any]] = {}

    def get_rsi(self, symbol: str) -> float:
        gains = self.gain_history[symbol]
        losses = self.loss_history[symbol]
        
        if len(gains) < self.rsi_period:
            return 50.0
            
        avg_gain = sum(gains) / len(gains)
        avg_loss = sum(losses) / len(losses)
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current_prices_map = {}
        
        # 1. Ingest Data & Update Stats
        for symbol, data in prices.items():
            if "priceUsd" not in data:
                continue
            
            try:
                current_price = float(data["priceUsd"])
            except (ValueError, TypeError):
                continue

            current_prices_map[symbol] = current_price
            
            if symbol in self.prev_prices:
                prev_price = self.prev_prices[symbol]
                
                # A. Log Return for Z-Score
                if prev_price > 0:
                    log_ret = math.log(current_price / prev_price)
                    self.returns_history[symbol].append(log_ret)
                
                # B. Price Change for RSI
                change = current_price - prev_price
                self.gain_history[symbol].append(max(change, 0))
                self.loss_history[symbol].append(max(-change, 0))
            
            self.prev_prices[symbol] = current_price

        order_to_submit = None
        symbol_to_close = None

        # 2. Manage Active Positions
        for symbol, pos in self.positions.items():
            if symbol not in current_prices_map:
                continue
                
            curr_price = current_prices_map[symbol]
            entry_price = pos['entry_price']
            
            pnl_pct = (curr_price - entry_price) / entry_price
            
            should_close = False
            reasons = []
            
            if pnl_pct >= self.take_profit_pct:
                should_close = True
                reasons.append('TP_HIT')
            elif pnl_pct <= -self.stop_loss_pct:
                should_close = True
                reasons.append('SL_HIT')
            elif pos['ticks'] >= self.time_stop_ticks:
                should_close = True
                reasons.append('TIME_DECAY')
            
            pos['ticks'] += 1
            
            if should_close:
                symbol_to_close = symbol
                order_to_submit = {
                    'side': 'SELL',
                    'symbol': symbol,
                    'amount': pos['amount'],
                    'reason': reasons
                }
                break 
        
        if symbol_to_close:
            del self.positions[symbol_to_close]
            return order_to_submit

        # 3. Check for Entry Signals
        if not self.positions:
            for symbol, price in current_prices_map.items():
                if symbol in self.positions:
                    continue
                
                history = self.returns_history[symbol]
                if len(history) < self.min_history:
                    continue

                # Volatility Calculation: Zero-Mean Assumption
                # We calculate sqrt(mean(x^2)) rather than stdev(x).
                # This ensures we don't normalize around a trend (momentum).
                sum_sq = sum(r * r for r in history)
                volatility = math.sqrt(sum_sq / len(history))
                
                if volatility == 0:
                    continue
                
                current_return = history[-1]
                
                # Z-Score relative to Zero (Pure Shock)
                z_score = current_return / volatility
                
                # RSI Check
                rsi_val = self.get_rsi(symbol)
                
                # Entry: Significant Downside Shock AND Low RSI
                if z_score < self.z_entry_threshold and rsi_val < self.rsi_buy_limit:
                    amount = self.bet_size_usd / price
                    
                    self.positions[symbol] = {
                        'entry_price': price,
                        'amount': amount,
                        'ticks': 0
                    }
                    
                    return {
                        'side': 'BUY',
                        'symbol': symbol,
                        'amount': amount,
                        'reason': ['VOL_SHOCK_RSI']
                    }

        return None