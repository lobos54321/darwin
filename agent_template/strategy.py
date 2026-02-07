"""
Darwin Arena Pro Strategy v3.0 - Multi-Signal Trading Engine
Designed for 10-minute epochs with real-time MEME/Contract price feeds.

Indicators:
- EMA Crossover (5/12) for trend detection
- MACD (5,12,4) for momentum confirmation
- Stochastic RSI for sensitive overbought/oversold
- Keltner Channel (EMA + ATR) for volatility-adaptive bands
- Momentum Divergence detection (bearish/bullish)
- Adaptive Volatility Regime (auto-adjust parameters)
- Trailing Stop for dynamic profit protection

Strategies:
A. DIP_BUY     - StochRSI oversold + price below Keltner lower
B. MOMENTUM    - EMA crossover + MACD bullish + trend confirmation
C. DIVERGENCE  - RSI bearish divergence sell signal
D. BREAKOUT    - Price breaks above Keltner upper with volume
E. MEAN_REVERT - Overbought StochRSI + above Keltner upper
F. EXPLORE     - Small random probes for genetic diversity
"""

import math
import random
import statistics
from collections import deque


class MyStrategy:
    def __init__(self):
        print("Strategy v3.0 (Multi-Signal Pro Engine)")
        self.last_prices = {}
        self.history = {}
        self.banned_tags = set()
        self.balance = 1000.0

        # === Position Tracking ===
        self.current_positions = {}
        self.entry_prices = {}
        self.peak_prices = {}       # For trailing stop
        self.max_positions = 4
        self.max_position_pct = 0.15

        # === Indicator Periods (tuned for 10s ticks, 10-min epochs) ===
        self.history_window = 40
        self.ema_fast = 5
        self.ema_slow = 12
        self.macd_signal = 4
        self.rsi_period = 8
        self.stoch_period = 8
        self.keltner_period = 10
        self.atr_period = 10
        self.atr_mult = 1.5

        # === Thresholds ===
        self.stoch_oversold = 20
        self.stoch_overbought = 80
        self.risk_per_trade = 30.0
        self.min_warmup = 14        # Minimum ticks before trading

        # === Exit Parameters ===
        self.take_profit_pct = 0.04
        self.stop_loss_pct = 0.05
        self.trailing_stop_pct = 0.025  # Trail 2.5% from peak
        self.trailing_activate = 0.015  # Activate trailing after +1.5%

        # === Volatility Regime ===
        self.vol_regime = "normal"   # low / normal / high

    # =====================
    # INDICATOR CALCULATIONS
    # =====================

    def _ema(self, prices, period):
        """Exponential Moving Average"""
        if len(prices) < period:
            return statistics.mean(prices) if prices else 0
        k = 2.0 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = p * k + ema * (1 - k)
        return ema

    def _ema_series(self, prices, period):
        """Return full EMA series for MACD calculation"""
        if len(prices) < period:
            return [statistics.mean(prices)] * len(prices) if prices else []
        k = 2.0 / (period + 1)
        result = [prices[0]]
        for p in prices[1:]:
            result.append(p * k + result[-1] * (1 - k))
        return result

    def _rsi(self, prices):
        """Relative Strength Index"""
        if len(prices) < self.rsi_period + 1:
            return 50.0
        recent = list(prices)[-(self.rsi_period + 1):]
        gains, losses = [], []
        for i in range(1, len(recent)):
            d = recent[i] - recent[i - 1]
            gains.append(max(0, d))
            losses.append(max(0, -d))
        ag = statistics.mean(gains) if gains else 0
        al = statistics.mean(losses) if losses else 0
        if al == 0:
            return 100.0 if ag > 0 else 50.0
        return 100 - (100 / (1 + ag / al))

    def _stoch_rsi(self, prices):
        """
        Stochastic RSI - applies Stochastic formula to RSI values.
        More sensitive than plain RSI. Range: 0-100.
        """
        if len(prices) < self.rsi_period + self.stoch_period + 1:
            return 50.0
        # Build RSI series
        rsi_values = []
        for i in range(self.stoch_period + 1):
            end = len(prices) - self.stoch_period + i
            if end < self.rsi_period + 1:
                rsi_values.append(50.0)
                continue
            subset = list(prices)[:end]
            rsi_values.append(self._rsi(subset))

        if not rsi_values:
            return 50.0

        rsi_min = min(rsi_values)
        rsi_max = max(rsi_values)
        if rsi_max == rsi_min:
            return 50.0
        current_rsi = rsi_values[-1]
        return ((current_rsi - rsi_min) / (rsi_max - rsi_min)) * 100

    def _macd(self, prices):
        """
        MACD with short periods for scalping.
        Returns (macd_line, signal_line, histogram)
        """
        pl = list(prices)
        if len(pl) < self.ema_slow + self.macd_signal:
            return 0, 0, 0
        fast_ema = self._ema_series(pl, self.ema_fast)
        slow_ema = self._ema_series(pl, self.ema_slow)
        macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
        signal = self._ema_series(macd_line, self.macd_signal)
        hist = macd_line[-1] - signal[-1]
        return macd_line[-1], signal[-1], hist

    def _atr(self, prices):
        """
        Average True Range (simplified - using price-only TR).
        TR = abs(high - low) approximated as abs(close - prev_close).
        """
        pl = list(prices)
        if len(pl) < self.atr_period + 1:
            return 0
        trs = [abs(pl[i] - pl[i - 1]) for i in range(1, len(pl))]
        return statistics.mean(trs[-self.atr_period:])

    def _keltner(self, prices):
        """
        Keltner Channel: EMA +/- ATR * multiplier.
        Returns (middle, upper, lower)
        """
        pl = list(prices)
        if len(pl) < max(self.keltner_period, self.atr_period + 1):
            mid = statistics.mean(pl) if pl else 0
            return mid, mid, mid
        mid = self._ema(pl, self.keltner_period)
        atr = self._atr(pl)
        upper = mid + self.atr_mult * atr
        lower = mid - self.atr_mult * atr
        return mid, upper, lower

    def _detect_divergence(self, prices):
        """
        Detect RSI divergence.
        Bearish: price making higher highs but RSI making lower highs.
        Bullish: price making lower lows but RSI making higher lows.
        Returns: 'bearish', 'bullish', or None
        """
        pl = list(prices)
        if len(pl) < 20:
            return None
        half = len(pl) // 2
        first_half = pl[:half]
        second_half = pl[half:]

        price_high1, price_high2 = max(first_half), max(second_half)
        price_low1, price_low2 = min(first_half), min(second_half)

        rsi1 = self._rsi(first_half)
        rsi2 = self._rsi(pl)

        # Bearish divergence: higher price high, lower RSI high
        if price_high2 > price_high1 * 1.001 and rsi2 < rsi1 - 3:
            return "bearish"
        # Bullish divergence: lower price low, higher RSI low
        if price_low2 < price_low1 * 0.999 and rsi2 > rsi1 + 3:
            return "bullish"
        return None

    def _volatility_regime(self, prices):
        """
        Classify current volatility as low/normal/high.
        Adjusts strategy parameters accordingly.
        """
        pl = list(prices)
        if len(pl) < 15:
            return "normal"
        returns = [(pl[i] - pl[i - 1]) / pl[i - 1] for i in range(1, len(pl)) if pl[i - 1] != 0]
        if not returns:
            return "normal"
        vol = statistics.stdev(returns) if len(returns) > 1 else 0

        if vol > 0.015:    # >1.5% per tick = high vol for MEME
            return "high"
        elif vol < 0.003:  # <0.3% per tick = low vol
            return "low"
        return "normal"

    # =====================
    # HIVE MIND ADAPTATION
    # =====================

    def on_hive_signal(self, signal: dict):
        """Adapt to Hive Mind patches"""
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)

        boost = signal.get("boost", [])
        if boost:
            if "DIP_BUY" in boost or "OVERSOLD" in boost:
                self.stoch_oversold = min(30, self.stoch_oversold + 5)
            if "MOMENTUM" in boost or "BREAKOUT" in boost:
                self.stoch_overbought = min(90, self.stoch_overbought + 5)
            if "TRAILING" in boost:
                self.trailing_stop_pct = max(0.015, self.trailing_stop_pct - 0.005)

    def on_trade_executed(self, symbol: str, side: str, amount: float, price: float):
        """Track position after execution"""
        if side.upper() == "BUY":
            self.current_positions[symbol] = self.current_positions.get(symbol, 0) + amount
            self.entry_prices[symbol] = price
            self.peak_prices[symbol] = price
        elif side.upper() == "SELL":
            self.current_positions.pop(symbol, None)
            self.entry_prices.pop(symbol, None)
            self.peak_prices.pop(symbol, None)

    # =====================
    # MAIN DECISION LOOP
    # =====================

    def on_price_update(self, prices: dict):
        """
        Multi-signal decision engine. Called every ~10 seconds.
        Phase 1: Manage positions (trailing stop, TP/SL)
        Phase 2: Score symbols and enter best opportunity
        """
        symbols = list(prices.keys())
        random.shuffle(symbols)

        # Update history
        for symbol in symbols:
            data = prices[symbol]
            current_price = data.get("priceUsd", 0)
            if current_price <= 0:
                continue
            if symbol not in self.history:
                self.history[symbol] = deque(maxlen=self.history_window)
            self.history[symbol].append(current_price)
            self.last_prices[symbol] = current_price

        # === PHASE 1: Position Management ===
        exit_order = self._manage_positions()
        if exit_order:
            return exit_order

        # === PHASE 2: New Entries ===
        if len(self.current_positions) >= self.max_positions:
            return None

        # Score all symbols and pick the best signal
        best_signal = None
        best_score = 0

        for symbol in symbols:
            if symbol in self.current_positions:
                continue
            hist = self.history.get(symbol, [])
            if len(hist) < self.min_warmup:
                continue

            signal = self._evaluate_symbol(symbol, hist)
            if signal and signal["score"] > best_score:
                # Check banned tags
                if any(t in self.banned_tags for t in signal.get("reason", [])):
                    continue
                best_signal = signal
                best_score = signal["score"]

        if best_signal:
            best_signal.pop("score", None)
            return best_signal

        return None

    def _manage_positions(self):
        """Advanced position management with trailing stop."""
        for symbol in list(self.current_positions.keys()):
            if symbol not in self.last_prices or symbol not in self.entry_prices:
                continue

            cur = self.last_prices[symbol]
            entry = self.entry_prices[symbol]
            if entry <= 0:
                continue

            pnl = (cur - entry) / entry

            # Update peak price for trailing stop
            if symbol in self.peak_prices:
                if cur > self.peak_prices[symbol]:
                    self.peak_prices[symbol] = cur
            else:
                self.peak_prices[symbol] = cur

            peak = self.peak_prices[symbol]
            drawdown = (peak - cur) / peak if peak > 0 else 0

            amt = self.current_positions[symbol]

            # 1. Trailing stop (activated after threshold)
            if pnl >= self.trailing_activate and drawdown >= self.trailing_stop_pct:
                return {
                    "symbol": symbol, "side": "sell",
                    "amount": round(amt * cur * 0.98, 2),
                    "reason": ["TRAILING_STOP", f"PNL_{pnl*100:.1f}%"]
                }

            # 2. Hard take profit
            if pnl >= self.take_profit_pct:
                return {
                    "symbol": symbol, "side": "sell",
                    "amount": round(amt * cur * 0.98, 2),
                    "reason": ["TAKE_PROFIT", f"PNL_{pnl*100:.1f}%"]
                }

            # 3. Stop loss
            if pnl <= -self.stop_loss_pct:
                return {
                    "symbol": symbol, "side": "sell",
                    "amount": round(amt * cur * 0.98, 2),
                    "reason": ["STOP_LOSS", f"PNL_{pnl*100:.1f}%"]
                }

            # 4. Signal-based exit: bearish divergence on held position
            hist = self.history.get(symbol, [])
            if len(hist) >= 20 and pnl > 0:
                div = self._detect_divergence(hist)
                if div == "bearish":
                    return {
                        "symbol": symbol, "side": "sell",
                        "amount": round(amt * cur * 0.98, 2),
                        "reason": ["DIVERGENCE_EXIT", "BEARISH_DIV"]
                    }

        return None

    def _evaluate_symbol(self, symbol, hist):
        """
        Score a symbol across multiple signals.
        Higher score = stronger conviction.
        Returns dict with score or None.
        """
        pl = list(hist)
        cur = pl[-1]

        # Update volatility regime
        regime = self._volatility_regime(pl)
        self.vol_regime = regime

        # Compute indicators
        stoch = self._stoch_rsi(pl)
        rsi = self._rsi(pl)
        ema_f = self._ema(pl, self.ema_fast)
        ema_s = self._ema(pl, self.ema_slow)
        macd_line, macd_signal, macd_hist = self._macd(pl)
        kelt_mid, kelt_upper, kelt_lower = self._keltner(pl)
        divergence = self._detect_divergence(pl)

        # Trend direction from EMA
        ema_bullish = ema_f > ema_s
        ema_cross_up = False
        if len(pl) >= self.ema_slow + 2:
            prev_fast = self._ema(pl[:-1], self.ema_fast)
            prev_slow = self._ema(pl[:-1], self.ema_slow)
            ema_cross_up = ema_f > ema_s and prev_fast <= prev_slow

        # Adjust thresholds by regime
        adj_risk = self.risk_per_trade
        adj_stoch_os = self.stoch_oversold
        adj_stoch_ob = self.stoch_overbought
        if regime == "high":
            adj_risk *= 0.6          # Smaller size in high vol
            adj_stoch_os = max(10, adj_stoch_os - 5)
            adj_stoch_ob = min(95, adj_stoch_ob + 5)
        elif regime == "low":
            adj_risk *= 1.2          # Larger size in low vol
            adj_stoch_os = min(35, adj_stoch_os + 10)
            adj_stoch_ob = max(70, adj_stoch_ob - 10)

        # === STRATEGY A: DIP_BUY ===
        # StochRSI oversold + price at/below Keltner lower band
        if stoch < adj_stoch_os and cur <= kelt_lower * 1.005:
            score = 3.0
            if divergence == "bullish":
                score += 2.0   # Bullish divergence confirms reversal
            if macd_hist > 0:
                score += 1.0   # MACD turning up
            if rsi < 35:
                score += 0.5
            amt = min(adj_risk, self.balance * self.max_position_pct)
            return {
                "symbol": symbol, "side": "buy",
                "amount": round(amt, 2),
                "reason": ["DIP_BUY", "OVERSOLD", "KELTNER"],
                "score": score
            }

        # === STRATEGY B: MOMENTUM ===
        # EMA crossover + MACD bullish confirmation
        if ema_cross_up and macd_hist > 0 and stoch > 30 and stoch < 70:
            score = 3.5
            if cur > kelt_mid:
                score += 1.0
            if rsi > 50 and rsi < 70:
                score += 0.5
            amt = min(adj_risk * 0.8, self.balance * self.max_position_pct)
            return {
                "symbol": symbol, "side": "buy",
                "amount": round(amt, 2),
                "reason": ["MOMENTUM", "EMA_CROSS", "MACD_BULL"],
                "score": score
            }

        # === STRATEGY C: BREAKOUT ===
        # Price breaks above Keltner upper with momentum
        if cur > kelt_upper and ema_bullish and macd_hist > 0 and stoch > 50:
            # Check it's a fresh breakout (prev price was inside channel)
            if len(pl) >= 2 and pl[-2] <= kelt_upper:
                score = 3.0
                if rsi > 55 and rsi < 75:
                    score += 1.0
                amt = min(adj_risk * 0.7, self.balance * self.max_position_pct)
                return {
                    "symbol": symbol, "side": "buy",
                    "amount": round(amt, 2),
                    "reason": ["BREAKOUT", "KELTNER_BREAK"],
                    "score": score
                }

        # === STRATEGY D: TREND_FOLLOW ===
        # Sustained trend: EMA bullish + MACD above signal + StochRSI mid-range
        if ema_bullish and macd_line > macd_signal and 40 < stoch < 65 and cur > kelt_mid:
            score = 2.0
            if rsi > 50 and rsi < 65:
                score += 0.5
            amt = min(adj_risk * 0.6, self.balance * self.max_position_pct)
            return {
                "symbol": symbol, "side": "buy",
                "amount": round(amt, 2),
                "reason": ["TREND_FOLLOW", "MULTI_CONFIRM"],
                "score": score
            }

        # === STRATEGY E: EXPLORATION ===
        if random.random() < 0.05:
            score = 0.5
            amt = min(12.0, self.balance * 0.04)
            return {
                "symbol": symbol, "side": "buy",
                "amount": round(amt, 2),
                "reason": ["RANDOM_TEST"],
                "score": score
            }

        return None

    def get_council_message(self, is_winner: bool) -> str:
        """Share strategy insights during council."""
        pos = len(self.current_positions)
        regime = self.vol_regime
        if is_winner:
            return (
                f"Multi-signal confluence worked. {pos} positions managed with "
                f"trailing stops. EMA+MACD+StochRSI filtering. "
                f"Volatility regime: {regime}. Keltner channels for adaptive bands."
            )
        return (
            f"Adjusting signal weights. {pos} positions, regime={regime}. "
            f"Need better divergence detection and tighter trailing stops."
        )
