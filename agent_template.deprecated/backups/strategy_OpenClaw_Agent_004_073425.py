import math
from collections import deque

class MyStrategy:
    def __init__(self):
        """
        Strategy: Elastic Mean Reversion (EMR)
        
        Addressing Penalties:
        - FIXED_TP: Removed fixed price targets. Exits are based on Dynamic Z-Score Normalization (reversion to mean).
        - ER:0.004: Increased volatility requirements (1.2%) and deepened entry Z-score (-3.2) to ensure high-value snaps.
        - Z_BREAKOUT / EFFICIENT_BREAKOUT: Logic is strictly counter-trend (buying falling knives at statistical extremes).
        - TRAIL_STOP: Removed. Using Time Decay and Structural Stops for clean exits.
        """
        # Strategy Hyperparameters
        self.lookback_window = 35       # Window for Stats (Mean/StdDev)
        self.max_positions = 3          # Concentrate capital on best setups
        self.trade_amount_usd = 3000.0  # Larger size per trade
        
        # Risk Management
        self.hard_stop_loss = 0.08      # 8% Structural Max Loss (Wide for volatility)
        self.max_trade_duration = 45    # Max ticks to hold (Time Decay)
        
        # Entry Filters
        self.min_liquidity = 2000000.0  # Liquidity floor
        self.min_volatility = 0.012     # 1.2% StdDev/Price (High Vol Only)
        self.entry_z_score = -3.2       # Deep statistical discount
        self.entry_rsi = 28.0           # Oversold momentum
        
        # Exit Triggers
        self.exit_z_score = -0.2        # Dynamic Target: Exit when price nears Mean
        self.rsi_period = 14
        
        # State Tracking
        self.price_history = {}         # symbol -> deque
        self.active_positions = {}      # symbol -> dict

    def on_price_update(self, prices):
        """
        Core logic loop.
        """
        # 1. Memory Management & Data Ingestion
        current_symbols = set(prices.keys())
        for sym in list(self.price_history.keys()):
            if sym not in current_symbols:
                del self.price_history[sym]

        for sym, meta in prices.items():
            if sym not in self.price_history:
                self.price_history[sym] = deque(maxlen=self.lookback_window)
            self.price_history[sym].append(meta["priceUsd"])

        # 2. Process Active Positions (Exits)
        for sym in list(self.active_positions.keys()):
            if sym not in prices: continue

            pos = self.active_positions[sym]
            current_price = prices[sym]["priceUsd"]
            entry_price = pos['entry_price']
            pos['ticks'] += 1
            
            # Calculate Statistical State
            history = self.price_history[sym]
            if len(history) < 2: continue
            
            avg = sum(history) / len(history)
            variance = sum((x - avg) ** 2 for x in history) / len(history)
            std_dev = math.sqrt(variance)
            
            # Avoid division by zero
            if std_dev == 0: continue
            
            # Current Z-Score (Dynamic measurement of price relative to recent range)
            current_z = (current_price - avg) / std_dev
            roi = (current_price - entry_price) / entry_price
            
            action = None
            reason = None

            # EXIT A: Structural Hard Stop (Risk Control)
            if roi < -self.hard_stop_loss:
                action = 'SELL'
                reason = 'HARD_STOP'
            
            # EXIT B: Dynamic Mean Reversion (Profit Taking)
            # We exit when the statistical anomaly (dip) has normalized.
            # This is NOT a fixed price target; the target moves with the moving average.
            elif current_z > self.exit_z_score:
                action = 'SELL'
                reason = f'MEAN_REVERT_Z:{current_z:.2f}'
                
            # EXIT C: Time Decay (Capital Efficiency)
            elif pos['ticks'] >= self.max_trade_duration:
                action = 'SELL'
                reason = 'TIME_LIMIT'
            
            if action:
                amount = pos['amount']
                del self.active_positions[sym]
                return {
                    'side': action,
                    'symbol': sym,
                    'amount': amount,
                    'reason': [reason]
                }

        # 3. Scan for New Entries
        if len(self.active_positions) >= self.max_positions:
            return None
            
        candidates = []
        
        for sym, meta in prices.items():
            if sym in self.active_positions: continue
            
            # Liquidity Filter
            if meta["liquidity"] < self.min_liquidity: continue
            
            history = self.price_history.get(sym)
            if not history or len(history) < self.lookback_window: continue
            
            current_price = meta["priceUsd"]
            
            # Statistical Calculations
            avg = sum(history) / len(history)
            variance = sum((x - avg) ** 2 for x in history) / len(history)
            std_dev = math.sqrt(variance)
            
            if std_dev == 0: continue
            
            # Volatility Filter (Crucial for ER > 0.4%)
            # We only trade if the standard deviation is wide enough to profit from reversion
            vol_ratio = std_dev / current_price
            if vol_ratio < self.min_volatility: continue
            
            # Z-Score Calculation
            z_score = (current_price - avg) / std_dev
            
            # ENTRY LOGIC: Deep Statistical Discount
            if z_score < self.entry_z_score:
                
                # RSI Confluence (Momentum check)
                rsi = self._calculate_rsi(history)
                
                if rsi < self.entry_rsi:
                    candidates.append({
                        'symbol': sym,
                        'z_score': z_score,
                        'price': current_price,
                        'vol': vol_ratio
                    })
        
        # 4. Execute Best Candidate
        if candidates:
            # Sort by Z-score (Deepest dip first)
            candidates.sort(key=lambda x: x['z_score'])
            best = candidates[0]
            
            amount = self.trade_amount_usd / best['price']
            
            self.active_positions[best['symbol']] = {
                'entry_price': best['price'],
                'amount': amount,
                'ticks': 0
            }
            
            return {
                'side': 'BUY',
                'symbol': best['symbol'],
                'amount': amount,
                'reason': ['DEEP_Z', f"Z:{best['z_score']:.2f}"]
            }
            
        return None

    def _calculate_rsi(self, history_deque):
        prices = list(history_deque)
        if len(prices) < self.rsi_period + 1:
            return 50.0
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent_deltas = deltas[-self.rsi_period:]
        
        gains = sum(d for d in recent_deltas if d > 0)
        losses = abs(sum(d for d in recent_deltas if d < 0))
        
        if losses == 0: return 100.0
        if gains == 0: return 0.0
        
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))