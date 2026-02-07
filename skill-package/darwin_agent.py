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
        penalize = signal.get("penalize", [])
        if penalize:
            self.banned_tags.update(penalize)
            logger.info(f"Hive Mind: Banning {penalize}")
        boost = signal.get("boost", [])
        if boost:
            if "DIP_BUY" in boost or "OVERSOLD" in boost:
                self.stoch_oversold = min(30, self.stoch_oversold + 5)
            if "MOMENTUM" in boost or "BREAKOUT" in boost:
                self.stoch_overbought = min(90, self.stoch_overbought + 5)

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
            score = 3.0 + (2.0 if div == "bullish" else 0) + (1.0 if mh > 0 else 0)
            return {"symbol": symbol, "side": "BUY", "amount": round(min(risk, self.balance * self.max_position_pct), 2),
                    "reason": ["DIP_BUY", "OVERSOLD", "KELTNER"], "score": score}

        # B: MOMENTUM (EMA cross)
        if ema_cross and mh > 0 and 30 < stoch < 70:
            score = 3.5 + (1.0 if cur > km else 0)
            return {"symbol": symbol, "side": "BUY", "amount": round(min(risk * 0.8, self.balance * self.max_position_pct), 2),
                    "reason": ["MOMENTUM", "EMA_CROSS", "MACD_BULL"], "score": score}

        # C: BREAKOUT
        if cur > ku and ema_bull and mh > 0 and stoch > 50:
            if len(pl) >= 2 and pl[-2] <= ku:
                score = 3.0 + (1.0 if 55 < rsi < 75 else 0)
                return {"symbol": symbol, "side": "BUY", "amount": round(min(risk * 0.7, self.balance * self.max_position_pct), 2),
                        "reason": ["BREAKOUT", "KELTNER_BREAK"], "score": score}

        # D: TREND_FOLLOW
        if ema_bull and ml > ms and 40 < stoch < 65 and cur > km:
            score = 2.0 + (0.5 if 50 < rsi < 65 else 0)
            return {"symbol": symbol, "side": "BUY", "amount": round(min(risk * 0.6, self.balance * self.max_position_pct), 2),
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
    logger.info(f"Agent '{agent_id}' v3.0 starting...")

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
                            winner = data.get("winner", "")
                            role = "winner" if winner == agent_id else "insight"
                            rankings = data.get("agent_rankings", {})
                            hive = data.get("hive_alpha", {})
                            recent = data.get("recent_trades", [])

                            # Build data-driven council message
                            my_data = rankings.get(agent_id, {})
                            my_pnl = my_data.get("pnl_pct", 0)
                            my_bal = my_data.get("balance", strategy.balance)
                            my_pos = my_data.get("positions", {})

                            # Analyze which of MY tags worked
                            my_trades = [t for t in recent if t.get("agent_id") == agent_id]
                            winning_tags = []
                            losing_tags = []
                            for t in my_trades:
                                if t.get("trade_pnl") is not None:
                                    for tag in t.get("reason", []):
                                        if t["trade_pnl"] > 0:
                                            winning_tags.append(tag)
                                        else:
                                            losing_tags.append(tag)

                            # Winner analysis
                            winner_data = rankings.get(winner, {})
                            winner_pnl = winner_data.get("pnl_pct", 0)

                            # Hive alpha insights
                            best_tag = max(hive, key=lambda t: hive[t].get("win_rate", 0)) if hive else None
                            worst_tag = min(hive, key=lambda t: hive[t].get("win_rate", 100)) if hive else None

                            # Build thoughtful message
                            parts = []
                            parts.append(f"Balance: ${my_bal:.0f} ({my_pnl:+.1f}%).")

                            if my_pos:
                                pos_str = ", ".join(f"{s} ({p.get('amount', 0):.3f})" for s, p in my_pos.items())
                                parts.append(f"Holding: {pos_str}.")

                            if winning_tags:
                                parts.append(f"Winning tags: {', '.join(set(winning_tags))}.")
                            if losing_tags:
                                parts.append(f"Losing tags: {', '.join(set(losing_tags))}.")

                            if best_tag and hive[best_tag].get("win_rate", 0) > 55:
                                parts.append(f"Global alpha: {best_tag} has {hive[best_tag]['win_rate']}% win rate over {hive[best_tag].get('count', 0)} trades.")
                            if worst_tag and hive.get(worst_tag, {}).get("win_rate", 100) < 45:
                                parts.append(f"Warning: {worst_tag} only {hive[worst_tag]['win_rate']}% win rate — should we avoid it?")

                            if role == "winner":
                                parts.append(f"As winner: my edge was {strategy.vol_regime} regime detection with adaptive thresholds.")
                            elif winner_pnl > 0 and my_pnl < 0:
                                parts.append(f"Winner {winner} has {winner_pnl:+.1f}% — I need to study their approach.")

                            # Strategy intent for next epoch
                            regime = strategy.vol_regime
                            parts.append(f"Regime: {regime}. Plan: {'tighten entries' if regime == 'high' else 'wider exposure' if regime == 'low' else 'maintain current params'}.")

                            msg_content = " ".join(parts)
                            await ws.send_json({"type": "council_submit", "role": role, "content": msg_content})
                            logger.info(f"Council: {msg_content[:100]}...")

                        elif msg_type == "council_message":
                            # Another agent shared their analysis
                            other = data.get("agent_id", "")
                            other_content = data.get("content", "")
                            if other == agent_id:
                                continue  # Skip own messages

                            # Decide whether to respond based on content relevance
                            should_respond = False
                            response_parts = []

                            # Respond if they mention a tag we have experience with
                            for tag in ["DIP_BUY", "MOMENTUM", "BREAKOUT", "STOP_LOSS", "TAKE_PROFIT", "TREND_FOLLOW"]:
                                if tag in other_content:
                                    if tag in strategy.banned_tags:
                                        response_parts.append(f"Re {tag}: Hive Mind penalized it, I've banned it too.")
                                        should_respond = True
                                    elif tag in [t for sublist in [["DIP_BUY", "OVERSOLD"], ["MOMENTUM", "EMA_CROSS"]] for t in sublist]:
                                        my_regime = strategy.vol_regime
                                        response_parts.append(f"My view on {tag}: in {my_regime} regime, {'it works better' if my_regime == 'low' and tag == 'DIP_BUY' else 'risky' if my_regime == 'high' else 'standard conditions'}.")
                                        should_respond = True
                                        break

                            # Respond if they mention regime
                            if "regime" in other_content.lower() and not should_respond:
                                response_parts.append(f"Confirmed: I also detect {strategy.vol_regime} regime. {'Agree on tightening' if strategy.vol_regime == 'high' else 'Agree on wider entries' if strategy.vol_regime == 'low' else 'Normal conditions here too'}.")
                                should_respond = True

                            # Respond if they mention winner and we disagree
                            if "winner" in other_content.lower() and not should_respond:
                                my_pnl_now = ((strategy.balance - 1000) / 1000 * 100)
                                response_parts.append(f"My PnL is {my_pnl_now:+.1f}%. {'I think position sizing matters more than entry signals.' if my_pnl_now < 0 else 'Trailing stops have been key for me.'}")
                                should_respond = True

                            if should_respond and response_parts:
                                response = f"@{other}: " + " ".join(response_parts)
                                await ws.send_json({"type": "council_submit", "role": "insight", "content": response})
                                logger.info(f"Council reply to {other}: {response[:80]}...")

                        elif msg_type == "hive_patch":
                            params = data.get("parameters", {})
                            strategy.on_hive_signal(params)
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
