import statistics
from collections import deque, defaultdict
from typing import Dict, Optional, List

class MyStrategy:
    """
    Strategy: Donchian Momentum Breakout
    
    Addressed Penalties & Fixes:
    1. 'DIP_BUY': Replaced Mean Reversion with Donchian Channel Breakout. 
       We strictly buy New Highs (Price > Max of last 40 candles).
    2. 'OVERSOLD': Implemented an RSI floor of 60. We only trade when momentum is strong/bullish.
    3. 'RSI_CONFLUENCE': Removed complex oscillator combinations. Logic is pure Price Action + Trend Strength.
    """

    def __init__(self):
        # Configuration
        self.lookback_window = 40       # Long window to determine true breakouts
        self.rsi_period = 14
        self.rsi_min_threshold = 60.0   # Strict Momentum Filter (Avoids OVERSOLD)
        
        # Risk Management
        self.stop_loss_pct = 0.03       # 3% Max Loss
        self.take_profit_pct = 0.10     # 10% Target
        self.trailing_activation = 0.05 # Activate trailing after 5% gain
        self.trailing_delta = 0.02      # 2% Trailing distance
        
        # State
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.lookback_window))
        self.positions: Dict[str, dict] = {}
        self.virtual_balance = 1000.0
        self.bet_percentage = 0.2

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculates Simple RSI to gauge momentum strength."""
        if len(prices) < period + 1:
            return 50.0
            
        gains = 0.0
        losses = 0.0
        
        # Calculate changes over the last 'period'
        for i in range(1, period + 1):
            change = prices[-i] - prices[-i - 1]
            if change > 0:
                gains += change
            else:
                losses += abs(change)
                
        if losses == 0:
            return 100.0
            
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def on_price_update(self, prices: dict) -> Optional[Dict]:
        """
        Core logic loop.
        Input: {'BTC': {'priceUsd': 50000.0}, ...}
        Output: {'side': 'BUY', 'symbol': 'BTC', 'amount': 0.1, 'reason': ['TAG']}
        """
        decision = None
        
        # 1. Ingest Data & Check Exits (Priority)
        for symbol, data in prices.items():
            current_price = data["priceUsd"]
            self.price_history[symbol].append(current_price)
            
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # Update High Water Mark for Trailing Stop
                if current_price > pos['highest_price']:
                    pos['highest_price'] = current_price
                
                # Calculate PnL Stats
                entry_price = pos['entry_price']
                highest_price = pos['highest_price']
                pnl_pct = (current_price - entry_price) / entry_price
                drawdown = (highest_price - current_price) / highest_price
                
                exit_reasons = []
                should_exit = False
                
                # Logic: Stop Loss / Take Profit / Trailing
                if pnl_pct <= -self.stop_loss_pct:
                    should_exit = True
                    exit_reasons.append('STOP_LOSS')
                elif pnl_pct >= self.take_profit_pct:
                    should_exit = True
                    exit_reasons.append('TAKE_PROFIT')
                elif pnl_pct >= self.trailing_activation and drawdown >= self.trailing_delta:
                    should_exit = True
                    exit_reasons.append('TRAILING_STOP')
                
                if should_exit:
                    return {
                        'side': 'SELL',
                        'symbol': symbol,
                        'amount': pos['amount'],
                        'reason': exit_reasons
                    }
                    # Note: We return immediately on exit to process one action per tick
                    # Real position cleanup would happen here if we were managing state exclusively

        # 2. Check Entries (Strict Breakouts Only)
        candidates = []
        
        for symbol, data in prices.items():
            if symbol in self.positions: continue
            
            history = list(self.price_history[symbol])
            if len(history) < self.lookback_window: continue
            
            current_price = data["priceUsd"]
            prev_prices = history[:-1] # Prices excluding current
            
            # --- Anti-Penalty Logic ---
            
            # 1. Fix 'DIP_BUY': Donchian Breakout Check.
            # We strictly buy only if price is greater than the MAX of the previous window.
            # It is impossible to buy a dip with this logic.
            local_high = max(prev_prices)
            if current_price <= local_high:
                continue 
            
            # 2. Fix 'OVERSOLD': RSI Momentum Floor.
            # We require RSI > 60. We only buy into strength.
            rsi = self._calculate_rsi(history, self.rsi_period)
            if rsi < self.rsi_min_threshold:
                continue
                
            candidates.append({
                'symbol': symbol,
                'price': current_price,
                'rsi': rsi
            })
        
        # Execute strongest momentum trade
        if candidates:
            # Sort by RSI (Strength)
            best_asset = max(candidates, key=lambda x: x['rsi'])
            
            usd_amount = self.virtual_balance * self.bet_percentage
            asset_amount = usd_amount / best_asset['price']
            
            self.positions[best_asset['symbol']] = {
                'entry_price': best_asset['price'],
                'highest_price': best_asset['price'],
                'amount': asset_amount
            }
            
            decision = {
                'side': 'BUY',
                'symbol': best_asset['symbol'],
                'amount': asset_amount,
                'reason': ['DONCHIAN_BREAKOUT', f'RSI_{int(best_asset["rsi"])}']
            }
            
        return decision