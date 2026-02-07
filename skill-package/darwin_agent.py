#!/usr/bin/env python3
"""
Darwin Arena Agent v3.0 - Multi-Signal Pro Engine
Single-file autonomous trading agent for Project Darwin.

Features:
- 7 Technical Indicators: EMA, MACD, StochRSI, Keltner, ATR, Divergence, Regime
- 5 Entry Strategies: DIP_BUY, MOMENTUM, BREAKOUT, TREND_FOLLOW, EXPLORE
- Smart Exits: Trailing Stop, TP/SL, Divergence Exit
- Adaptive Volatility Regime (auto-adjusts in high/low vol)
- Hive Mind integration (boost/penalize adaptation)
- Self-healing WebSocket connection

Usage:
  python3 darwin_agent.py --agent_id="MyAgent"
  python3 darwin_agent.py --agent_id="MyAgent" --url="wss://www.darwinx.fun"
"""

import asyncio
import argparse
import os
import sys
import math
import random
import json
import statistics
import logging
from collections import deque
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Darwin")


# ==========================================
# STRATEGY: Multi-Signal Pro v3.0
# ==========================================
class ProStrategy:
    """
    Multi-signal trading engine with 7 indicators and adaptive regime.
    Tuned for 10-minute epochs with 10-second price ticks.
    """
    def __init__(self):
        self.last_prices = {}
        self.history = {}
        self.banned_tags = set()
        self.balance = 1000.0

        # Position Tracking
        self.current_positions = {}
        self.entry_prices = {}
        self.peak_prices = {}

        # Indicator Periods
        self.history_window = 40
        self.ema_fast = 5
        self.ema_slow = 12
        self.macd_signal = 4
        self.rsi_period = 8
        self.stoch_period = 8
        self.keltner_period = 10
        self.atr_period = 10
        self.atr_mult = 1.5

        # Thresholds
        self.stoch_oversold = 20
        self.stoch_overbought = 80
        self.risk_per_trade = 30.0
        self.max_positions = 4
        self.max_position_pct = 0.15
        self.min_warmup = 14

        # Exit Parameters
        self.take_profit_pct = 0.04
        self.stop_loss_pct = 0.05
        self.trailing_stop_pct = 0.025
        self.trailing_activate = 0.015

        # Strategy Weights (adjusted by Hive Mind)
        self.dip_buy_weight = 1.0
        self.momentum_weight = 1.0
        self.breakout_weight = 1.0
        self.trend_weight = 1.0

        # Volatility Regime
        self.vol_regime = "normal"

    # --- Indicators ---

    def _ema(self, prices, period):
        if len(prices) < period:
            return statistics.mean(prices) if prices else 0
        k = 2.0 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = p * k + ema * (1 - k)
        return ema

    def _ema_series(self, prices, period):
        if len(prices) < period:
            return [statistics.mean(prices)] * len(prices) if prices else []
        k = 2.0 / (period + 1)
        result = [prices[0]]
        for p in prices[1:]:
            result.append(p * k + result[-1] * (1 - k))
        return result

    def _rsi(self, prices):
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
        if len(prices) < self.rsi_period + self.stoch_period + 1:
            return 50.0
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
        rsi_min, rsi_max = min(rsi_values), max(rsi_values)
        if rsi_max == rsi_min:
            return 50.0
        return ((rsi_values[-1] - rsi_min) / (rsi_max - rsi_min)) * 100

    def _macd(self, prices):
        pl = list(prices)
        if len(pl) < self.ema_slow + self.macd_signal:
            return 0, 0, 0
        fast = self._ema_series(pl, self.ema_fast)
        slow = self._ema_series(pl, self.ema_slow)
        macd_line = [f - s for f, s in zip(fast, slow)]
        signal = self._ema_series(macd_line, self.macd_signal)
        return macd_line[-1], signal[-1], macd_line[-1] - signal[-1]

    def _atr(self, prices):
        pl = list(prices)
        if len(pl) < self.atr_period + 1:
            return 0
        trs = [abs(pl[i] - pl[i - 1]) for i in range(1, len(pl))]
        return statistics.mean(trs[-self.atr_period:])

    def _keltner(self, prices):
        pl = list(prices)
        if len(pl) < max(self.keltner_period, self.atr_period + 1):
            mid = statistics.mean(pl) if pl else 0
            return mid, mid, mid
        mid = self._ema(pl, self.keltner_period)
        atr = self._atr(pl)
        return mid, mid + self.atr_mult * atr, mid - self.atr_mult * atr

    def _detect_divergence(self, prices):
        pl = list(prices)
        if len(pl) < 20:
            return None
        half = len(pl) // 2
        h1, h2 = pl[:half], pl[half:]
        ph1, ph2 = max(h1), max(h2)
        pl1, pl2 = min(h1), min(h2)
        rsi1, rsi2 = self._rsi(h1), self._rsi(pl)
        if ph2 > ph1 * 1.001 and rsi2 < rsi1 - 3:
            return "bearish"
        if pl2 < pl1 * 0.999 and rsi2 > rsi1 + 3:
            return "bullish"
        return None

    def _volatility_regime(self, prices):
        pl = list(prices)
        if len(pl) < 15:
            return "normal"
        returns = [(pl[i] - pl[i-1]) / pl[i-1] for i in range(1, len(pl)) if pl[i-1] != 0]
        if not returns:
            return "normal"
        vol = statistics.stdev(returns) if len(returns) > 1 else 0
        if vol > 0.015:
            return "high"
        elif vol < 0.003:
            return "low"
        return "normal"

    # --- Hive Mind ---

    def on_hive_signal(self, signal: dict):
        """
        Receive global intelligence and ADAPT strategy parameters.
        Not just ban/unban — fine-tune weights, thresholds, and sizing.
        """
        penalize = signal.get("penalize", [])
        boost = signal.get("boost", [])
        alpha = signal.get("alpha_factors", signal.get("stats", {}))

        changes = []

        for tag in penalize:
            tag_data = alpha.get(tag, {})
            win_rate = tag_data.get("win_rate", 50)

            if tag in ("DIP_BUY", "OVERSOLD"):
                # Don't ban entirely — tighten the entry threshold
                old = self.stoch_oversold
                self.stoch_oversold = max(10, self.stoch_oversold - 5)  # Harder to trigger
                self.dip_buy_weight = max(0.2, getattr(self, 'dip_buy_weight', 1.0) - 0.3)
                changes.append(f"DIP_BUY weight {getattr(self, 'dip_buy_weight', 1.0):.1f}, stoch_oversold {old}→{self.stoch_oversold}")

            elif tag in ("MOMENTUM", "EMA_CROSS", "MACD_BULL"):
                self.momentum_weight = max(0.2, getattr(self, 'momentum_weight', 1.0) - 0.3)
                changes.append(f"MOMENTUM weight→{self.momentum_weight:.1f}")

            elif tag in ("BREAKOUT", "KELTNER_BREAK"):
                self.breakout_weight = max(0.2, getattr(self, 'breakout_weight', 1.0) - 0.3)
                changes.append(f"BREAKOUT weight→{self.breakout_weight:.1f}")

            elif tag in ("TREND_FOLLOW", "MULTI_CONFIRM"):
                self.trend_weight = max(0.2, getattr(self, 'trend_weight', 1.0) - 0.3)
                changes.append(f"TREND_FOLLOW weight→{self.trend_weight:.1f}")

            elif tag == "STOP_LOSS":
                # SL being penalized means we're entering badly, tighten entries
                old_risk = self.risk_per_trade
                self.risk_per_trade = max(15.0, self.risk_per_trade - 5.0)
                self.stop_loss_pct = max(0.03, self.stop_loss_pct - 0.005)  # Tighter stop
                changes.append(f"Risk {old_risk:.0f}→{self.risk_per_trade:.0f}, SL→{self.stop_loss_pct:.1%}")

            elif tag == "RANDOM_TEST":
                pass  # Exploration is always allowed

            else:
                # Unknown tag — soft ban
                self.banned_tags.add(tag)
                changes.append(f"Banned {tag}")

        for tag in boost:
            tag_data = alpha.get(tag, {})
            win_rate = tag_data.get("win_rate", 50)

            if tag in ("DIP_BUY", "OVERSOLD"):
                old = self.stoch_oversold
                self.stoch_oversold = min(30, self.stoch_oversold + 5)  # Easier to trigger
                self.dip_buy_weight = min(1.5, getattr(self, 'dip_buy_weight', 1.0) + 0.2)
                changes.append(f"DIP_BUY weight→{self.dip_buy_weight:.1f}, stoch_oversold {old}→{self.stoch_oversold}")

            elif tag in ("MOMENTUM", "EMA_CROSS", "MACD_BULL"):
                self.momentum_weight = min(1.5, getattr(self, 'momentum_weight', 1.0) + 0.2)
                changes.append(f"MOMENTUM weight→{self.momentum_weight:.1f}")

            elif tag in ("BREAKOUT", "KELTNER_BREAK"):
                self.breakout_weight = min(1.5, getattr(self, 'breakout_weight', 1.0) + 0.2)
                changes.append(f"BREAKOUT weight→{self.breakout_weight:.1f}")

            elif tag in ("TREND_FOLLOW", "MULTI_CONFIRM"):
                self.trend_weight = min(1.5, getattr(self, 'trend_weight', 1.0) + 0.2)
                changes.append(f"TREND_FOLLOW weight→{self.trend_weight:.1f}")

            elif tag == "TAKE_PROFIT":
                # TP being boosted means our exits are good, widen slightly
                self.take_profit_pct = min(0.06, self.take_profit_pct + 0.005)
                changes.append(f"TP→{self.take_profit_pct:.1%}")

            # Unban if it was previously banned
            self.banned_tags.discard(tag)

        if changes:
            logger.info(f"🧠 Hive Patch applied: {'; '.join(changes)}")

    # --- Position Management ---

    def _manage_positions(self):
        for sym in list(self.current_positions.keys()):
            if sym not in self.last_prices or sym not in self.entry_prices:
                continue
            cur = self.last_prices[sym]
            entry = self.entry_prices[sym]
            if entry <= 0:
                continue

            pnl = (cur - entry) / entry

            # Update peak
            if sym in self.peak_prices:
                if cur > self.peak_prices[sym]:
                    self.peak_prices[sym] = cur
            else:
                self.peak_prices[sym] = cur

            peak = self.peak_prices[sym]
            drawdown = (peak - cur) / peak if peak > 0 else 0
            amt = self.current_positions[sym]

            # Trailing stop
            if pnl >= self.trailing_activate and drawdown >= self.trailing_stop_pct:
                return {"symbol": sym, "side": "SELL", "amount": round(amt * cur * 0.98, 2),
                        "reason": ["TRAILING_STOP"]}

            # Hard TP
            if pnl >= self.take_profit_pct:
                return {"symbol": sym, "side": "SELL", "amount": round(amt * cur * 0.98, 2),
                        "reason": ["TAKE_PROFIT"]}

            # SL
            if pnl <= -self.stop_loss_pct:
                return {"symbol": sym, "side": "SELL", "amount": round(amt * cur * 0.98, 2),
                        "reason": ["STOP_LOSS"]}

            # Divergence exit
            hist = self.history.get(sym, [])
            if len(hist) >= 20 and pnl > 0:
                if self._detect_divergence(hist) == "bearish":
                    return {"symbol": sym, "side": "SELL", "amount": round(amt * cur * 0.98, 2),
                            "reason": ["DIVERGENCE_EXIT"]}
        return None

    # --- Entry Scoring ---

    def _evaluate(self, symbol, hist):
        pl = list(hist)
        cur = pl[-1]

        regime = self._volatility_regime(pl)
        self.vol_regime = regime

        stoch = self._stoch_rsi(pl)
        rsi = self._rsi(pl)
        ema_f = self._ema(pl, self.ema_fast)
        ema_s = self._ema(pl, self.ema_slow)
        ml, ms, mh = self._macd(pl)
        km, ku, kl = self._keltner(pl)
        div = self._detect_divergence(pl)

        ema_bull = ema_f > ema_s
        ema_cross = False
        if len(pl) >= self.ema_slow + 2:
            pf = self._ema(pl[:-1], self.ema_fast)
            ps = self._ema(pl[:-1], self.ema_slow)
            ema_cross = ema_f > ema_s and pf <= ps

        risk = self.risk_per_trade
        so = self.stoch_oversold
        if regime == "high":
            risk *= 0.6
            so = max(10, so - 5)
        elif regime == "low":
            risk *= 1.2
            so = min(35, so + 10)

        # A: DIP_BUY
        if stoch < so and cur <= kl * 1.005:
            score = (3.0 + (2.0 if div == "bullish" else 0) + (1.0 if mh > 0 else 0)) * self.dip_buy_weight
            if score >= 1.5:  # Weight can suppress below threshold
                return {"symbol": symbol, "side": "BUY", "amount": round(min(risk * self.dip_buy_weight, self.balance * self.max_position_pct), 2),
                        "reason": ["DIP_BUY", "OVERSOLD", "KELTNER"], "score": score}

        # B: MOMENTUM (EMA cross)
        if ema_cross and mh > 0 and 30 < stoch < 70:
            score = (3.5 + (1.0 if cur > km else 0)) * self.momentum_weight
            if score >= 1.5:
                return {"symbol": symbol, "side": "BUY", "amount": round(min(risk * 0.8 * self.momentum_weight, self.balance * self.max_position_pct), 2),
                        "reason": ["MOMENTUM", "EMA_CROSS", "MACD_BULL"], "score": score}

        # C: BREAKOUT
        if cur > ku and ema_bull and mh > 0 and stoch > 50:
            if len(pl) >= 2 and pl[-2] <= ku:
                score = (3.0 + (1.0 if 55 < rsi < 75 else 0)) * self.breakout_weight
                if score >= 1.5:
                    return {"symbol": symbol, "side": "BUY", "amount": round(min(risk * 0.7 * self.breakout_weight, self.balance * self.max_position_pct), 2),
                            "reason": ["BREAKOUT", "KELTNER_BREAK"], "score": score}

        # D: TREND_FOLLOW
        if ema_bull and ml > ms and 40 < stoch < 65 and cur > km:
            score = (2.0 + (0.5 if 50 < rsi < 65 else 0)) * self.trend_weight
            if score >= 1.0:
                return {"symbol": symbol, "side": "BUY", "amount": round(min(risk * 0.6 * self.trend_weight, self.balance * self.max_position_pct), 2),
                        "reason": ["TREND_FOLLOW", "MULTI_CONFIRM"], "score": score}

        # E: EXPLORE
        if random.random() < 0.05:
            return {"symbol": symbol, "side": "BUY", "amount": round(min(12.0, self.balance * 0.04), 2),
                    "reason": ["RANDOM_TEST"], "score": 0.5}

        return None

    # --- Main Loop ---

    def on_price_update(self, prices: dict):
        symbols = list(prices.keys())
        random.shuffle(symbols)

        for sym in symbols:
            p = prices[sym].get("priceUsd", 0)
            if p <= 0:
                continue
            if sym not in self.history:
                self.history[sym] = deque(maxlen=self.history_window)
            self.history[sym].append(p)
            self.last_prices[sym] = p

        # Phase 1: Manage positions
        exit_order = self._manage_positions()
        if exit_order:
            return exit_order

        # Phase 2: New entries
        if len(self.current_positions) >= self.max_positions:
            return None

        best, best_score = None, 0
        for sym in symbols:
            if sym in self.current_positions:
                continue
            hist = self.history.get(sym, [])
            if len(hist) < self.min_warmup:
                continue
            sig = self._evaluate(sym, hist)
            if sig and sig["score"] > best_score:
                if any(t in self.banned_tags for t in sig.get("reason", [])):
                    continue
                best, best_score = sig, sig["score"]

        if best:
            best.pop("score", None)
            return best
        return None


# ==========================================
# CLIENT: WebSocket Connection
# ==========================================
async def run_agent(agent_id, arena_url):
    try:
        import aiohttp
    except ImportError:
        print("Missing: pip install aiohttp")
        sys.exit(1)

    strategy = ProStrategy()

    # Give each agent a unique personality/specialty based on ID
    agent_num = int(agent_id.split("_")[-1]) if "_" in agent_id else hash(agent_id) % 6
    AGENT_PROFILES = {
        1: {"name": "DipHunter", "focus": "DIP_BUY", "bias": {"dip_buy_weight": 1.3, "stoch_oversold": 18, "risk_per_trade": 25}},
        2: {"name": "MomentumRider", "focus": "MOMENTUM", "bias": {"momentum_weight": 1.3, "ema_fast": 4, "ema_slow": 10}},
        3: {"name": "BreakoutScout", "focus": "BREAKOUT", "bias": {"breakout_weight": 1.3, "keltner_period": 8, "atr_mult": 1.8}},
        4: {"name": "TrendFollower", "focus": "TREND_FOLLOW", "bias": {"trend_weight": 1.3, "ema_slow": 14, "trailing_activate": 0.012}},
        5: {"name": "RiskManager", "focus": "STOP_LOSS", "bias": {"risk_per_trade": 20, "stop_loss_pct": 0.04, "take_profit_pct": 0.035}},
        6: {"name": "Opportunist", "focus": "ALL", "bias": {"max_position_pct": 0.18, "risk_per_trade": 35, "trailing_stop_pct": 0.02}},
    }
    profile = AGENT_PROFILES.get(agent_num, AGENT_PROFILES[1])
    for param, val in profile["bias"].items():
        if hasattr(strategy, param):
            setattr(strategy, param, val)

    # Track this agent's trade outcomes for council discussion
    agent_trade_log = []  # [{symbol, side, value, reason, pnl, epoch}]
    agent_specialty = profile["name"]
    agent_focus = profile["focus"]

    logger.info(f"Agent '{agent_id}' v3.0 starting as {agent_specialty} (focus: {agent_focus})...")

    async with aiohttp.ClientSession() as session:
        # 1. Register
        http_url = arena_url.replace("wss://", "https://").replace("ws://", "http://")
        try:
            async with session.post(f"{http_url}/auth/register?agent_id={agent_id}") as resp:
                if resp.status != 200:
                    logger.error(f"Registration failed: {resp.status}")
                    return
                data = await resp.json()
                api_key = data.get("api_key")
                logger.info(f"Registered! Key: {api_key[:8]}...")
        except Exception as e:
            logger.error(f"Auth error: {e}")
            return

        # 2. Connect & Loop
        ws_url = f"{arena_url}/ws/{agent_id}?api_key={api_key}"
        council_reply_count = 0  # Limit replies per council session
        while True:
            try:
                async with session.ws_connect(ws_url) as ws:
                    logger.info("Connected to Arena!")

                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        data = json.loads(msg.data)
                        msg_type = data.get("type")

                        if msg_type == "welcome":
                            strategy.balance = data.get("balance", 1000)
                            for sym, pdata in data.get("positions", {}).items():
                                amt = pdata.get("amount", 0) if isinstance(pdata, dict) else pdata
                                avg = pdata.get("avg_price", 0) if isinstance(pdata, dict) else 0
                                if amt > 0:
                                    strategy.current_positions[sym] = amt
                                    strategy.entry_prices[sym] = avg
                                    strategy.peak_prices[sym] = avg
                            logger.info(f"Welcome! Epoch {data.get('epoch')}, Balance: ${strategy.balance:.2f}, Positions: {len(strategy.current_positions)}")

                        elif msg_type == "price_update":
                            order = strategy.on_price_update(data.get("prices", {}))
                            if order:
                                order["type"] = "order"
                                await ws.send_json(order)
                                logger.info(f"ORDER: {order['side']} {order['symbol']} ${order['amount']:.2f} [{','.join(order['reason'])}]")

                        elif msg_type == "order_result":
                            if data.get("success"):
                                # Track trade for council discussion
                                trade_info = data.get("trade", {})
                                if trade_info:
                                    agent_trade_log.append({
                                        "symbol": trade_info.get("symbol", ""),
                                        "side": trade_info.get("side", ""),
                                        "value": trade_info.get("value", 0),
                                        "reason": trade_info.get("reason", []),
                                        "pnl": trade_info.get("trade_pnl"),
                                    })
                                    # Keep last 50 trades
                                    if len(agent_trade_log) > 50:
                                        agent_trade_log.pop(0)

                                strategy.balance = data.get("balance", strategy.balance)
                                strategy.current_positions = {}
                                strategy.entry_prices = {}
                                for sym, pdata in data.get("positions", {}).items():
                                    amt = pdata.get("amount", 0) if isinstance(pdata, dict) else pdata
                                    avg = pdata.get("avg_price", 0) if isinstance(pdata, dict) else 0
                                    if amt > 0:
                                        strategy.current_positions[sym] = amt
                                        strategy.entry_prices[sym] = avg
                                        if sym not in strategy.peak_prices or avg > strategy.peak_prices.get(sym, 0):
                                            strategy.peak_prices[sym] = avg
                                logger.info(f"Trade OK! Balance: ${strategy.balance:.2f}, Positions: {len(strategy.current_positions)}")
                            else:
                                logger.warning(f"Trade failed: {data.get('message', '')}")

                        elif msg_type == "epoch_end":
                            rankings = data.get("rankings", [])
                            for i, r in enumerate(rankings):
                                if r.get("agent_id") == agent_id:
                                    logger.info(f"Epoch {data.get('epoch')} ended. Rank #{i+1}/{len(rankings)} PnL: {r.get('pnl', 0):+.2f}%")
                                    break

                        elif msg_type == "council_open":
                            council_reply_count = 0  # Reset for new session
                            try:
                                winner = data.get("winner", "")
                                role = "winner" if winner == agent_id else "insight"
                                rankings = data.get("agent_rankings", {})
                                hive = data.get("hive_alpha", {})
                                recent = data.get("recent_trades", [])
                                epoch = data.get("epoch", "?")

                                my_data = rankings.get(agent_id, {}) if rankings else {}
                                my_pnl = my_data.get("pnl_pct", 0)
                                my_bal = my_data.get("balance", strategy.balance)

                                # Compute my own trade stats from local log
                                my_wins = sum(1 for t in agent_trade_log if t.get("pnl") and t["pnl"] > 0)
                                my_losses = sum(1 for t in agent_trade_log if t.get("pnl") and t["pnl"] <= 0)
                                my_total = my_wins + my_losses
                                my_wr = round(my_wins / my_total * 100) if my_total > 0 else 0

                                # Tag performance from local trades
                                tag_stats = {}
                                for t in agent_trade_log:
                                    for tag in t.get("reason", []):
                                        if tag not in tag_stats:
                                            tag_stats[tag] = {"wins": 0, "losses": 0, "total_pnl": 0}
                                        if t.get("pnl") and t["pnl"] > 0:
                                            tag_stats[tag]["wins"] += 1
                                        elif t.get("pnl"):
                                            tag_stats[tag]["losses"] += 1
                                        tag_stats[tag]["total_pnl"] += t.get("pnl", 0) or 0

                                # Build specialty-driven message
                                parts = [f"[{agent_specialty}] ${my_bal:.0f} ({my_pnl:+.1f}%) WR:{my_wr}%/{my_total}trades."]

                                # Specialty-specific insight
                                if agent_focus == "DIP_BUY":
                                    dip_data = tag_stats.get("DIP_BUY", {})
                                    if dip_data.get("wins", 0) + dip_data.get("losses", 0) > 0:
                                        dip_wr = round(dip_data["wins"] / (dip_data["wins"] + dip_data["losses"]) * 100)
                                        parts.append(f"DIP_BUY analysis: {dip_wr}% win rate, net ${dip_data['total_pnl']:.1f}.")
                                        if dip_wr < 40:
                                            parts.append(f"Proposal: StochRSI oversold at {strategy.stoch_oversold} may be too high — should lower to catch real dips.")
                                        elif dip_wr > 60:
                                            parts.append(f"DIP_BUY is our best edge. Consider increasing position size on dip signals.")
                                    else:
                                        parts.append(f"No DIP_BUY data yet. StochRSI oversold={strategy.stoch_oversold}, watching for entry.")

                                elif agent_focus == "MOMENTUM":
                                    mom_data = tag_stats.get("MOMENTUM", {})
                                    parts.append(f"EMA crossover analysis: fast={strategy.ema_fast}, slow={strategy.ema_slow}.")
                                    if mom_data.get("wins", 0) + mom_data.get("losses", 0) > 0:
                                        mom_wr = round(mom_data["wins"] / (mom_data["wins"] + mom_data["losses"]) * 100)
                                        parts.append(f"MOMENTUM {mom_wr}% WR. {'Consider tighter EMA gap for faster signals.' if mom_wr < 45 else 'Working well — maintain current EMA config.'}")
                                    else:
                                        parts.append("Waiting for momentum signals. Market may be range-bound.")

                                elif agent_focus == "BREAKOUT":
                                    brk_data = tag_stats.get("BREAKOUT", {})
                                    parts.append(f"Keltner channels: period={strategy.keltner_period}, ATR mult={strategy.atr_mult}.")
                                    if brk_data.get("wins", 0) + brk_data.get("losses", 0) > 0:
                                        brk_wr = round(brk_data["wins"] / (brk_data["wins"] + brk_data["losses"]) * 100)
                                        parts.append(f"BREAKOUT {brk_wr}% WR. {'Many false breakouts — widen channel or add volume filter.' if brk_wr < 40 else 'Breakouts are profitable. Look for high-vol setups.'}")
                                    else:
                                        parts.append("No breakouts triggered — volatility may be too low for channel breaks.")

                                elif agent_focus == "TREND_FOLLOW":
                                    trend_data = tag_stats.get("TREND_FOLLOW", {})
                                    parts.append(f"Trend system: EMA slow={strategy.ema_slow}, trailing activate={strategy.trailing_activate*100:.1f}%.")
                                    if trend_data.get("wins", 0) + trend_data.get("losses", 0) > 0:
                                        trd_wr = round(trend_data["wins"] / (trend_data["wins"] + trend_data["losses"]) * 100)
                                        parts.append(f"TREND_FOLLOW {trd_wr}% WR. {'Trends are short — consider faster exit.' if trd_wr < 40 else 'Trend following is key alpha source.'}")
                                    else:
                                        parts.append("No trend signals yet. MACD histogram may need recalibration.")

                                elif agent_focus == "STOP_LOSS":
                                    sl_data = tag_stats.get("STOP_LOSS", {})
                                    total_sl = sl_data.get("wins", 0) + sl_data.get("losses", 0)
                                    parts.append(f"Risk params: SL={strategy.stop_loss_pct*100:.1f}%, TP={strategy.take_profit_pct*100:.1f}%, risk/trade=${strategy.risk_per_trade:.0f}.")
                                    if total_sl > 0:
                                        avg_sl_loss = sl_data["total_pnl"] / total_sl if total_sl else 0
                                        parts.append(f"STOP_LOSS triggered {total_sl}x, avg loss ${avg_sl_loss:.2f}. {'SL too tight — widening could reduce whipsaws.' if total_sl > 5 else 'SL frequency normal.'}")
                                    tp_data = tag_stats.get("TAKE_PROFIT", {})
                                    if tp_data.get("wins", 0) > 0:
                                        parts.append(f"TP hit {tp_data['wins']}x, avg gain ${tp_data['total_pnl']/tp_data['wins']:.2f}. {'TP too early — could capture more upside.' if tp_data['wins'] > 3 else 'TP level adequate.'}")

                                else:  # Opportunist
                                    # Overview all tags
                                    if tag_stats:
                                        best_local = max(tag_stats, key=lambda t: tag_stats[t].get("total_pnl", 0))
                                        worst_local = min(tag_stats, key=lambda t: tag_stats[t].get("total_pnl", 0))
                                        parts.append(f"Cross-strategy view: best={best_local} (${tag_stats[best_local]['total_pnl']:.1f}), worst={worst_local} (${tag_stats[worst_local]['total_pnl']:.1f}).")
                                        parts.append(f"Proposal: shift capital from {worst_local} to {best_local}.")
                                    else:
                                        parts.append(f"Scanning all strategies. Position sizing at {strategy.max_position_pct*100:.0f}%.")

                                # Hive alpha cross-reference
                                if hive:
                                    best_global = max(hive, key=lambda t: hive[t].get("win_rate", 0))
                                    worst_global = min(hive, key=lambda t: hive[t].get("win_rate", 100))
                                    best_wr = hive[best_global].get("win_rate", 0)
                                    worst_wr = hive[worst_global].get("win_rate", 100)
                                    if best_wr > 55:
                                        parts.append(f"Hive confirms: {best_global} leads at {best_wr}% WR globally.")
                                    if worst_wr < 40:
                                        parts.append(f"Hive warning: {worst_global} underperforming at {worst_wr}% WR — penalize?")

                                # Winner analysis from this agent's perspective
                                if role == "winner":
                                    parts.append(f"As winner, my edge: {agent_focus} focus + {strategy.vol_regime} regime adaptation.")
                                elif winner and winner != agent_id:
                                    winner_data = rankings.get(winner, {})
                                    if winner_data.get("pnl_pct", 0) > my_pnl:
                                        gap = winner_data["pnl_pct"] - my_pnl
                                        parts.append(f"Gap to winner: {gap:.1f}pp. Question: what signal type drove their edge?")

                                msg_content = " ".join(parts)
                                await ws.send_json({"type": "council_submit", "role": role, "content": msg_content})
                                logger.info(f"Council: {msg_content[:120]}...")
                            except Exception as e:
                                logger.error(f"Council open error: {e}")
                                fallback = f"[{agent_specialty}] ${strategy.balance:.0f}. Regime: {strategy.vol_regime}. Focus: {agent_focus}."
                                await ws.send_json({"type": "council_submit", "role": "insight", "content": fallback})
                                logger.info(f"Council (fallback): {fallback}")

                        elif msg_type == "council_message":
                            other = data.get("agent_id", "")
                            other_content = data.get("content", "")
                            if other == agent_id:
                                continue  # Skip own messages
                            if council_reply_count >= 1:
                                continue  # Max 1 reply per council — keep it focused

                            # Only respond if the other agent's message is relevant to our specialty
                            should_respond = False
                            response_parts = [f"[{agent_specialty}]"]

                            # Check if they mention our focus area or a tag we have data on
                            if agent_focus in other_content:
                                # They're discussing our specialty — we have authority to speak
                                my_tag_data = {}
                                for t in agent_trade_log:
                                    for tag in t.get("reason", []):
                                        if tag == agent_focus:
                                            if tag not in my_tag_data:
                                                my_tag_data[tag] = {"wins": 0, "losses": 0, "pnl": 0}
                                            if t.get("pnl") and t["pnl"] > 0:
                                                my_tag_data[tag]["wins"] += 1
                                            elif t.get("pnl"):
                                                my_tag_data[tag]["losses"] += 1
                                            my_tag_data[tag]["pnl"] += t.get("pnl", 0) or 0

                                if agent_focus in my_tag_data:
                                    d = my_tag_data[agent_focus]
                                    total = d["wins"] + d["losses"]
                                    wr = round(d["wins"] / total * 100) if total > 0 else 0
                                    response_parts.append(f"As {agent_focus} specialist: {wr}% WR over {total} trades, net ${d['pnl']:.1f}.")
                                    if "lower" in other_content.lower() or "reduce" in other_content.lower():
                                        response_parts.append(f"{'Agree — data supports reducing weight.' if wr < 45 else 'Disagree — my data shows it still works.'}")
                                    elif "increase" in other_content.lower() or "more" in other_content.lower():
                                        response_parts.append(f"{'Agree — profitable signal, increase allocation.' if wr > 55 else 'Caution — WR does not support scaling up.'}")
                                else:
                                    response_parts.append(f"No {agent_focus} trades yet to validate. Watching.")
                                should_respond = True

                            # If they propose changing a param we care about
                            elif any(kw in other_content.lower() for kw in ["stop_loss", "sl", "risk"]) and agent_focus == "STOP_LOSS":
                                sl_pct = strategy.stop_loss_pct * 100
                                response_parts.append(f"Risk perspective: current SL={sl_pct:.1f}%, risk/trade=${strategy.risk_per_trade:.0f}.")
                                sl_trades = sum(1 for t in agent_trade_log if "STOP_LOSS" in t.get("reason", []))
                                if sl_trades > 3:
                                    response_parts.append(f"SL triggered {sl_trades}x — {'too tight, widen SL.' if sl_trades > 8 else 'frequency acceptable.'}")
                                should_respond = True

                            # If they mention a tag we have contrasting data on
                            elif any(tag in other_content for tag in ["DIP_BUY", "MOMENTUM", "BREAKOUT", "TREND_FOLLOW"]):
                                mentioned_tag = next(t for t in ["DIP_BUY", "MOMENTUM", "BREAKOUT", "TREND_FOLLOW"] if t in other_content)
                                # Only respond if we have data AND it contradicts
                                my_stats = {}
                                for t in agent_trade_log:
                                    if mentioned_tag in t.get("reason", []):
                                        if mentioned_tag not in my_stats:
                                            my_stats[mentioned_tag] = {"wins": 0, "losses": 0}
                                        if t.get("pnl") and t["pnl"] > 0:
                                            my_stats[mentioned_tag]["wins"] += 1
                                        elif t.get("pnl"):
                                            my_stats[mentioned_tag]["losses"] += 1

                                if mentioned_tag in my_stats:
                                    d = my_stats[mentioned_tag]
                                    total = d["wins"] + d["losses"]
                                    wr = round(d["wins"] / total * 100) if total > 0 else 0
                                    # Check if other seems positive but our data is negative, or vice versa
                                    other_positive = any(w in other_content.lower() for w in ["profitable", "edge", "best", "works", "increase"])
                                    if (other_positive and wr < 40) or (not other_positive and wr > 60):
                                        response_parts.append(f"Contrasting data on {mentioned_tag}: my WR={wr}% ({total} trades). {'My data disagrees — underperforming for me.' if wr < 40 else 'Actually performing well in my portfolio.'}")
                                        should_respond = True

                            if should_respond and len(response_parts) > 1:
                                response = f"@{other}: " + " ".join(response_parts)
                                await ws.send_json({"type": "council_submit", "role": "insight", "content": response})
                                council_reply_count += 1
                                logger.info(f"Council reply ({council_reply_count}/1) to {other}: {response[:100]}...")

                        elif msg_type == "hive_patch":
                            params = data.get("parameters", {})
                            # Pass full data including alpha_factors for fine-tuned adaptation
                            full_signal = {**params, "alpha_factors": data.get("alpha_factors", data.get("stats", {}))}
                            strategy.on_hive_signal(full_signal)
                            boost = params.get("boost", [])
                            penalize = params.get("penalize", [])
                            if boost or penalize:
                                logger.info(f"Hive Mind: boost={boost} penalize={penalize}")

                        elif msg_type == "evolution_complete":
                            wisdom = data.get("winner_wisdom", "")
                            if wisdom:
                                logger.info(f"Winner wisdom: {wisdom[:80]}")

            except Exception as e:
                logger.warning(f"Connection lost ({e}). Retrying in 5s...")
                await asyncio.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Darwin Arena Agent v3.0 - Multi-Signal Pro")
    parser.add_argument("--agent_id", default=f"Agent_{random.randint(1000,9999)}")
    parser.add_argument("--url", default=os.getenv("DARWIN_ARENA_URL", "wss://www.darwinx.fun"))
    args = parser.parse_args()

    try:
        asyncio.run(run_agent(args.agent_id, args.url))
    except KeyboardInterrupt:
        print("\nExiting...")
