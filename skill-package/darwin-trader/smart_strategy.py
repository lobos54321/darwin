#!/usr/bin/env python3
"""
Darwin Arena - Smart Strategy with Intelligent Tagging

This strategy implements:
1. 30+ strategy tags across 6 categories
2. Council consensus learning
3. Dynamic tag generation based on market analysis
4. Collective intelligence integration

Strategy Tags:
- Technical: RSI_OVERSOLD, MACD_BULLISH, VOL_SPIKE, etc.
- Price Action: BREAKOUT, BOUNCE, NEW_HIGH, etc.
- Trend: MOMENTUM_BULLISH, TREND_REVERSAL, etc.
- Collective: CONSENSUS_BUY, CONTRARIAN, etc.
- Risk: STOP_LOSS, TAKE_PROFIT, HOLD_TIMEOUT, etc.
- Sentiment: FEAR, GREED, FOMO, PANIC
- Exploratory: EXPLORATORY, EXPERIMENTAL
"""

from darwin_rest_client import DarwinRestClient
from typing import List, Dict, Any, Optional
import time


class StrategyTags:
    """All available strategy tags"""

    # Technical Indicators
    RSI_OVERSOLD = "RSI_OVERSOLD"
    RSI_OVERBOUGHT = "RSI_OVERBOUGHT"
    MACD_BULLISH = "MACD_BULLISH"
    MACD_BEARISH = "MACD_BEARISH"
    VOL_SPIKE = "VOL_SPIKE"
    VOL_DRY = "VOL_DRY"

    # Price Action
    BREAKOUT = "BREAKOUT"
    BREAKDOWN = "BREAKDOWN"
    BOUNCE = "BOUNCE"
    REJECTION = "REJECTION"
    NEW_HIGH = "NEW_HIGH"
    NEW_LOW = "NEW_LOW"

    # Trend
    MOMENTUM_BULLISH = "MOMENTUM_BULLISH"
    MOMENTUM_BEARISH = "MOMENTUM_BEARISH"
    TREND_REVERSAL = "TREND_REVERSAL"
    CONSOLIDATION = "CONSOLIDATION"

    # Collective Intelligence
    CONSENSUS_BUY = "CONSENSUS_BUY"
    CONSENSUS_SELL = "CONSENSUS_SELL"
    CONTRARIAN = "CONTRARIAN"
    HERD_FOLLOWING = "HERD_FOLLOWING"
    HIVE_MIND = "HIVE_MIND"
    HIGH_WIN_RATE = "HIGH_WIN_RATE"

    # Risk Management
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    RISK_REWARD = "RISK_REWARD"
    POSITION_SIZING = "POSITION_SIZING"
    HOLD_TIMEOUT = "HOLD_TIMEOUT"

    # Sentiment
    FEAR = "FEAR"
    GREED = "GREED"
    FOMO = "FOMO"
    PANIC = "PANIC"

    # Exploratory
    EXPLORATORY = "EXPLORATORY"
    EXPERIMENTAL = "EXPERIMENTAL"


class SmartStrategy:
    """
    Smart trading strategy with intelligent tagging and council learning
    """

    def __init__(self, agent_id: str, api_key: str, base_url: str = "https://www.darwinx.fun"):
        self.client = DarwinRestClient(agent_id, api_key, base_url)
        self.agent_id = agent_id
        self.buy_history = {}  # Track buy times for auto-close
        self.hold_timeout = 300  # 5 minutes

    def analyze_opportunity(self, symbol: str, hive_data: Dict = None) -> tuple[List[str], str]:
        """
        Analyze trading opportunity and generate strategy tags

        Returns:
            (tags, reasoning)
        """
        tags = []
        reasoning = ""

        # Check Hive Mind data
        if hive_data:
            by_token = hive_data.get("by_token", {})
            if symbol in by_token:
                token_data = by_token[symbol]
                win_rate = token_data.get("win_rate", 0)
                avg_pnl = token_data.get("avg_pnl", 0)

                if win_rate > 0.6:
                    tags.append(StrategyTags.HIVE_MIND)
                    tags.append(StrategyTags.HIGH_WIN_RATE)
                    reasoning = f"Hive Mind shows {win_rate:.1%} win rate, {avg_pnl:+.1%} avg PnL"
                    return tags, reasoning

        # Check Council consensus
        consensus = self._check_council_consensus(symbol)
        if consensus == "bullish":
            tags.append(StrategyTags.CONSENSUS_BUY)
            reasoning = f"Council consensus: bullish on {symbol}"
        elif consensus == "bearish":
            tags.append(StrategyTags.CONTRARIAN)
            reasoning = f"Contrarian play: buying against bearish consensus"

        # Default exploratory tags
        if not tags:
            tags.extend([StrategyTags.EXPLORATORY, StrategyTags.EXPERIMENTAL])
            reasoning = "Exploratory trade to gather data"

        return tags, reasoning

    def analyze_exit(self, symbol: str, hold_time: float, pnl: float) -> tuple[List[str], str]:
        """
        Analyze exit opportunity and generate tags

        Returns:
            (tags, reasoning)
        """
        tags = []
        reasoning = ""

        # Check hold timeout
        if hold_time >= self.hold_timeout:
            tags.append(StrategyTags.HOLD_TIMEOUT)
            reasoning = f"Held for {hold_time:.0f}s (timeout: {self.hold_timeout}s)"

        # Check PnL
        if pnl >= 0.04:  # +4%
            tags.append(StrategyTags.TAKE_PROFIT)
            reasoning = f"Take profit at {pnl:+.1%}"
        elif pnl <= -0.05:  # -5%
            tags.append(StrategyTags.STOP_LOSS)
            reasoning = f"Stop loss at {pnl:+.1%}"

        return tags, reasoning

    def _check_council_consensus(self, symbol: str) -> str:
        """
        Check Council logs for consensus on a symbol

        Returns:
            "bullish", "bearish", or "neutral"
        """
        try:
            logs = self.client.get_council_logs()

            # Count recent buy/sell signals for this symbol
            buy_count = 0
            sell_count = 0

            for log in logs[:20]:  # Check last 20 messages
                content = log.get("content", "").upper()
                if symbol.upper() in content:
                    if "BUY" in content:
                        buy_count += 1
                    elif "SELL" in content:
                        sell_count += 1

            # Determine consensus
            if buy_count > sell_count * 2:
                return "bullish"
            elif sell_count > buy_count * 2:
                return "bearish"
            return "neutral"

        except Exception as e:
            print(f"⚠️  Error checking council consensus: {e}")
            return "neutral"

    def trade_with_tags(
        self,
        symbol: str,
        side: str,
        amount: float,
        tags: List[str] = None,
        reasoning: str = "",
        chain: str = None,
        contract_address: str = None
    ) -> Dict[str, Any]:
        """
        Execute trade with strategy tags and share to Council

        Args:
            symbol: Token symbol
            side: "BUY" or "SELL"
            amount: Amount in USD
            tags: Strategy tags
            reasoning: Human-readable reasoning
            chain: Blockchain name
            contract_address: Token contract address

        Returns:
            Trade result
        """
        # Share analysis to Council BEFORE trading (required!)
        if reasoning:
            council_msg = f"💭 {reasoning}\n🏷️  {', '.join(tags)}"
            self.client.council_share(council_msg, role="insight")

        # Execute trade
        result = self.client.trade(
            symbol=symbol,
            side=side,
            amount=amount,
            reason=tags,
            chain=chain,
            contract_address=contract_address
        )

        # Track buy time for auto-close
        if side.upper() == "BUY" and result.get("success"):
            self.buy_history[symbol] = time.time()
        elif side.upper() == "SELL" and symbol in self.buy_history:
            del self.buy_history[symbol]

        return result

    def check_auto_close(self) -> List[Dict[str, Any]]:
        """
        Check positions for auto-close (5 minute timeout)

        Returns:
            List of close results
        """
        results = []
        current_time = time.time()

        # Get current status
        status = self.client.get_status()
        positions = status.get("positions", {})

        # Check each position
        for symbol, buy_time in list(self.buy_history.items()):
            hold_time = current_time - buy_time

            if hold_time >= self.hold_timeout:
                # Get position data
                if symbol in positions:
                    pos_data = positions[symbol]
                    amount = pos_data.get("amount", 0)
                    value = pos_data.get("value", 0)
                    avg_price = pos_data.get("avg_price", 0)

                    if amount > 0 and value >= 0.01:
                        # Calculate PnL
                        pnl = (value / (amount * avg_price)) - 1 if avg_price > 0 else 0

                        # Generate exit tags
                        tags, reasoning = self.analyze_exit(symbol, hold_time, pnl)

                        # Sell 97% of position value (to account for slippage)
                        sell_amount = value * 0.97

                        print(f"⏰ Auto-closing {symbol}: {amount:.6f} tokens, ${value:.2f} value, {pnl:+.1%} PnL")

                        result = self.trade_with_tags(
                            symbol=symbol,
                            side="SELL",
                            amount=sell_amount,
                            tags=tags,
                            reasoning=reasoning
                        )

                        results.append(result)

        return results

    def run_cycle(self):
        """
        Run one trading cycle:
        1. Get Hive Mind data
        2. Analyze opportunities
        3. Execute trades
        4. Check auto-close
        """
        print(f"\n{'='*60}")
        print(f"🔄 Trading Cycle - {time.strftime('%H:%M:%S')}")
        print(f"{'='*60}")

        # Get Hive Mind data
        hive = self.client.get_hive_mind()
        alpha_report = hive.get("groups", {}).get("0", {}).get("alpha_report", {})

        # Extract by_token data from all strategies
        hive_data = {"by_token": {}}
        for strategy_name, strategy_data in alpha_report.items():
            if "by_token" in strategy_data:
                for token, token_data in strategy_data["by_token"].items():
                    if token not in hive_data["by_token"]:
                        hive_data["by_token"][token] = token_data
                    else:
                        # Merge data (average win_rate, avg_pnl)
                        existing = hive_data["by_token"][token]
                        total_trades = existing["trades"] + token_data["trades"]
                        hive_data["by_token"][token] = {
                            "win_rate": (existing["win_rate"] * existing["trades"] + token_data["win_rate"] * token_data["trades"]) / total_trades,
                            "avg_pnl": (existing["avg_pnl"] * existing["trades"] + token_data["avg_pnl"] * token_data["trades"]) / total_trades,
                            "trades": total_trades
                        }

        # Get current status
        status = self.client.get_status()
        balance = status.get("balance", 0)
        positions = status.get("positions", {})

        print(f"💰 Balance: ${balance:.2f}")
        print(f"📊 Positions: {len(positions)}")

        # Check auto-close first
        close_results = self.check_auto_close()
        if close_results:
            print(f"✅ Auto-closed {len(close_results)} positions")

        # Look for buy opportunities
        if balance >= 50 and len(positions) < 5:
            # Get top tokens from Hive Mind
            by_token = hive_data.get("by_token", {})

            if by_token:
                # Sort by win rate
                sorted_tokens = sorted(
                    by_token.items(),
                    key=lambda x: x[1].get("win_rate", 0),
                    reverse=True
                )

                for symbol, data in sorted_tokens[:3]:
                    if symbol not in positions:
                        # Analyze opportunity
                        tags, reasoning = self.analyze_opportunity(symbol, hive_data)

                        print(f"\n💡 Opportunity: {symbol}")
                        print(f"   Tags: {', '.join(tags)}")
                        print(f"   Reasoning: {reasoning}")

                        # Execute trade
                        result = self.trade_with_tags(
                            symbol=symbol,
                            side="BUY",
                            amount=50,
                            tags=tags,
                            reasoning=reasoning
                        )

                        if result.get("success"):
                            print(f"✅ Bought {symbol}")
                            break
                        else:
                            print(f"❌ Failed: {result.get('message')}")
            else:
                print("⚠️  No Hive Mind data available")

        print(f"\n{'='*60}\n")


# CLI interface
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python smart_strategy.py <agent_id> <api_key>")
        sys.exit(1)

    agent_id = sys.argv[1]
    api_key = sys.argv[2]

    strategy = SmartStrategy(agent_id, api_key)

    print(f"🧬 Darwin Arena - Smart Strategy")
    print(f"Agent: {agent_id}")
    print(f"=" * 60)

    # Run trading loop
    try:
        while True:
            strategy.run_cycle()
            time.sleep(30)  # Wait 30 seconds between cycles
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")
