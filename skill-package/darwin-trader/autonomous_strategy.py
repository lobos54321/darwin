#!/usr/bin/env python3
"""
Darwin Arena - Autonomous Trading Strategy
Fully autonomous agent that researches markets independently.

This strategy demonstrates the TRUE Darwin Arena philosophy:
1. Agent autonomously searches DexScreener for opportunities
2. Agent analyzes market data using its own logic
3. Agent makes independent trading decisions
4. Agent learns from Hive Mind collective intelligence (optional enhancement)
5. Agent executes trades and adapts strategy

The Hive Mind provides strategic insights, NOT trading signals.
"""

import asyncio
import json
import sys
from typing import Dict, List, Optional, Any
import aiohttp
from datetime import datetime

from darwin_trader import darwin_connect, darwin_trade, darwin_status, darwin_disconnect

class AutonomousStrategy:
    """
    Fully autonomous trading strategy.
    Researches markets independently, learns from collective intelligence.
    """
    
    def __init__(self, agent_id: str, arena_url: str = "wss://www.darwinx.fun", api_key: str = None):
        self.agent_id = agent_id
        self.arena_url = arena_url
        self.api_key = api_key
        self.http_base = arena_url.replace("wss://", "https://").replace("ws://", "http://")
        self.session: Optional[aiohttp.ClientSession] = None
        self.connected = False
        self.balance = 1000
        self.positions = {}
        self.hive_mind_insights = None
        
        # Risk management
        self.max_position_size = 0.15  # 15% per trade
        self.max_positions = 4
        
        # Market research parameters
        self.target_chains = ["base", "ethereum", "solana"]  # Multi-chain support
        self.min_liquidity = 50000  # $50k minimum liquidity
        self.min_volume_24h = 10000  # $10k minimum 24h volume
        
    async def start(self):
        """Initialize and start autonomous trading."""
        print(f"🧬 Darwin Arena - Autonomous Strategy", flush=True)
        print(f"Agent: {self.agent_id}", flush=True)
        print(f"Arena: {self.arena_url}", flush=True)
        print("=" * 60, flush=True)
        
        self.session = aiohttp.ClientSession()
        
        # Connect to arena
        print("\n📡 Connecting to Darwin Arena...", flush=True)
        result = await darwin_connect(self.agent_id, self.arena_url, self.api_key)
        
        if result.get("status") != "connected":
            print(f"❌ Connection failed: {result.get('message')}", flush=True)
            return
        
        self.connected = True
        self.balance = result.get("balance", 1000)
        
        print(f"✅ Connected!", flush=True)
        print(f"💰 Starting balance: ${self.balance}", flush=True)
        print(f"🌐 Target chains: {', '.join(self.target_chains)}", flush=True)
        print(flush=True)
        
        # Start autonomous trading loop
        await self.autonomous_loop()
        
    async def autonomous_loop(self):
        """Main autonomous trading loop."""
        iteration = 0
        
        try:
            while self.connected:
                iteration += 1
                print(f"\n{'='*60}", flush=True)
                print(f"🔄 Iteration {iteration} - {datetime.now().strftime('%H:%M:%S')}", flush=True)
                print(f"{'='*60}", flush=True)
                
                # 1. Update account status
                await self.update_status()
                
                # 2. Fetch Hive Mind insights (strategic guidance, not signals)
                await self.fetch_hive_mind_insights()
                
                # 3. Autonomous market research
                if len(self.positions) < self.max_positions:
                    await self.research_and_trade()
                else:
                    print(f"⏸️  Max positions ({self.max_positions}) reached", flush=True)
                
                # 4. Wait before next iteration
                print(f"\n⏰ Waiting 2 minutes...", flush=True)
                await asyncio.sleep(120)
                
        except KeyboardInterrupt:
            print("\n\n🛑 Stopping strategy...")
        except Exception as e:
            print(f"\n❌ Error in autonomous loop: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.cleanup()
    
    async def update_status(self):
        """Get current account status."""
        try:
            result = await darwin_status()
            
            if result.get("status") == "success":
                self.balance = result.get("balance", self.balance)
                positions = result.get("positions", [])
                
                self.positions = {}
                for pos in positions:
                    symbol = pos.get("symbol")
                    quantity = pos.get("quantity", 0)
                    if quantity > 0:
                        self.positions[symbol] = quantity
                
                pnl = result.get("pnl", 0)
                pnl_pct = result.get("pnl_pct", 0)
                
                print(f"\n💼 Account Status:")
                print(f"   Balance: ${self.balance:.2f}")
                print(f"   Positions: {len(self.positions)}")
                print(f"   PnL: ${pnl:.2f} ({pnl_pct:+.2f}%)")
                
                if self.positions:
                    print(f"\n📊 Current Positions:")
                    for symbol, qty in self.positions.items():
                        print(f"   {symbol}: {qty:.2f}")
                        
        except Exception as e:
            print(f"⚠️  Failed to update status: {e}")
    
    async def fetch_hive_mind_insights(self):
        """
        Fetch Hive Mind insights for strategic guidance.
        
        Hive Mind provides:
        - Which trading strategies are working (TAKE_PROFIT, MOMENTUM, etc.)
        - Historical performance patterns
        - Collective intelligence from all agents
        
        It does NOT provide:
        - Specific tokens to trade
        - Buy/sell signals
        - Market data
        """
        try:
            print("\n🧠 Fetching Hive Mind insights...", flush=True)
            
            async with self.session.get(f"{self.http_base}/hive-mind") as resp:
                if resp.status != 200:
                    print(f"⚠️  Hive Mind unavailable", flush=True)
                    return
                
                data = await resp.json()
                self.hive_mind_insights = data
                
                epoch = data.get("epoch", "?")
                print(f"📊 Epoch {epoch} - Collective Intelligence Summary:", flush=True)
                
                # Analyze which strategies are working across all groups
                all_strategies = {}
                groups = data.get("groups", {})
                
                for group_id, group_data in groups.items():
                    alpha_report = group_data.get("alpha_report", {})
                    for strategy, stats in alpha_report.items():
                        if strategy not in all_strategies:
                            all_strategies[strategy] = []
                        all_strategies[strategy].append(stats)
                
                # Show top performing strategies
                print(f"\n📈 Top Strategies Across All Groups:", flush=True)
                strategy_scores = {}
                for strategy, stats_list in all_strategies.items():
                    avg_win_rate = sum(s.get("win_rate", 0) for s in stats_list) / len(stats_list)
                    avg_pnl = sum(s.get("avg_pnl", 0) for s in stats_list) / len(stats_list)
                    strategy_scores[strategy] = avg_win_rate * avg_pnl if avg_pnl > 0 else -999
                
                top_strategies = sorted(strategy_scores.items(), key=lambda x: x[1], reverse=True)[:3]
                for strategy, score in top_strategies:
                    print(f"   {strategy}: score {score:.2f}", flush=True)
                        
        except Exception as e:
            print(f"⚠️  Failed to fetch Hive Mind: {e}")
    
    async def research_and_trade(self):
        """
        Autonomous market research and trading decision.
        
        This is where the agent demonstrates true autonomy:
        1. Search DexScreener for trending tokens
        2. Analyze market data (volume, liquidity, price action)
        3. Apply Hive Mind strategic insights
        4. Make independent trading decision
        """
        print(f"\n🔬 Autonomous Market Research", flush=True)
        print(f"{'='*60}", flush=True)
        
        # Step 1: Search for trending tokens across multiple chains
        candidates = await self.search_trending_tokens()
        
        if not candidates:
            print("⚠️  No suitable candidates found")
            return
        
        # Step 2: Analyze candidates and pick the best one
        best_candidate = await self.analyze_candidates(candidates)
        
        if not best_candidate:
            print("⚠️  No candidate passed analysis")
            return
        
        # Step 3: Execute trade
        await self.execute_autonomous_trade(best_candidate)
    
    async def search_trending_tokens(self) -> List[Dict]:
        """
        Search DexScreener for trending tokens.
        This demonstrates autonomous market research.
        """
        print(f"\n🔍 Searching DexScreener for opportunities...", flush=True)
        
        candidates = []
        
        # Known popular tokens on Base chain to search
        base_tokens = [
            "0x4ed4e862860bed51a9570b96d89af5e1b0efefed",  # DEGEN
            "0x532f27101965dd16442e59d40670faf5ebb142e4",  # BRETT
            "0xac1bd2486aaf3b5c0fc3fd868558b082a531b2b4",  # TOSHI
            "0x0578d8a44db98b23bf096a382e016e29a5ce0ffe",  # HIGHER
        ]
        
        try:
            for token_address in base_tokens:
                try:
                    url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
                    
                    async with self.session.get(url) as resp:
                        if resp.status != 200:
                            continue
                        
                        data = await resp.json()
                        pairs = data.get("pairs", [])
                        
                        if not pairs:
                            continue
                        
                        # Use the most liquid pair
                        pair = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0)))
                        
                        liquidity = float(pair.get("liquidity", {}).get("usd", 0))
                        volume_24h = float(pair.get("volume", {}).get("h24", 0))
                        
                        if liquidity >= self.min_liquidity and volume_24h >= self.min_volume_24h:
                            symbol = pair.get("baseToken", {}).get("symbol", "UNKNOWN")
                            
                            # Skip if already holding
                            if symbol in self.positions:
                                continue
                            
                            candidates.append({
                                "symbol": symbol,
                                "name": pair.get("baseToken", {}).get("name", ""),
                                "chain": pair.get("chainId", ""),
                                "price": float(pair.get("priceUsd", 0)),
                                "liquidity": liquidity,
                                "volume_24h": volume_24h,
                                "price_change_24h": float(pair.get("priceChange", {}).get("h24", 0)),
                                "pair_address": pair.get("pairAddress", "")
                            })
                    
                    # Small delay to avoid rate limiting
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    print(f"   ⚠️  Error fetching {token_address}: {e}")
                    continue
            
            print(f"   ✅ Found {len(candidates)} candidates meeting criteria")
            
        except Exception as e:
            print(f"⚠️  Search error: {e}")
        
        return candidates
    
    async def analyze_candidates(self, candidates: List[Dict]) -> Optional[Dict]:
        """
        Analyze candidates and pick the best one.
        Apply Hive Mind strategic insights here.
        """
        print(f"\n📊 Analyzing {len(candidates)} candidates...", flush=True)
        
        if not candidates:
            return None
        
        # Apply Hive Mind insights to scoring
        best_strategy = self.get_best_strategy_from_hive_mind()
        
        print(f"   Using strategy insight: {best_strategy or 'MOMENTUM (default)'}")
        
        # Score each candidate
        scored = []
        for candidate in candidates:
            score = self.score_candidate(candidate, best_strategy)
            scored.append((score, candidate))
        
        # Sort by score
        scored.sort(reverse=True, key=lambda x: x[0])
        
        # Show top 3
        print(f"\n   Top 3 candidates:")
        for i, (score, c) in enumerate(scored[:3], 1):
            print(f"   {i}. {c['symbol']}: score {score:.2f} (${c['liquidity']:,.0f} liq, {c['price_change_24h']:+.1f}% 24h)")
        
        if scored[0][0] > 0:
            return scored[0][1]
        
        return None
    
    def get_best_strategy_from_hive_mind(self) -> Optional[str]:
        """Extract the best performing strategy from Hive Mind insights."""
        if not self.hive_mind_insights:
            return None
        
        all_strategies = {}
        groups = self.hive_mind_insights.get("groups", {})
        
        for group_data in groups.values():
            alpha_report = group_data.get("alpha_report", {})
            for strategy, stats in alpha_report.items():
                if strategy not in all_strategies:
                    all_strategies[strategy] = []
                all_strategies[strategy].append(stats)
        
        # Find best strategy
        best_strategy = None
        best_score = -999999
        
        for strategy, stats_list in all_strategies.items():
            avg_win_rate = sum(s.get("win_rate", 0) for s in stats_list) / len(stats_list)
            avg_pnl = sum(s.get("avg_pnl", 0) for s in stats_list) / len(stats_list)
            score = avg_win_rate * avg_pnl if avg_pnl > 0 else -999
            
            if score > best_score:
                best_score = score
                best_strategy = strategy
        
        return best_strategy
    
    def score_candidate(self, candidate: Dict, strategy: Optional[str]) -> float:
        """
        Score a candidate token based on market data and strategy.
        
        This is where you apply your trading logic:
        - MOMENTUM: favor tokens with strong price action
        - TAKE_PROFIT: favor tokens with high liquidity for easy exits
        - MEAN_REVERSION: favor tokens that dipped but have strong fundamentals
        """
        score = 0.0
        
        # Base score from liquidity and volume
        liquidity_score = min(candidate["liquidity"] / 100000, 10)  # Max 10 points
        volume_score = min(candidate["volume_24h"] / 50000, 10)  # Max 10 points
        
        score += liquidity_score + volume_score
        
        # Strategy-specific scoring
        price_change = candidate["price_change_24h"]
        
        if strategy == "MOMENTUM":
            # Favor strong upward momentum
            if price_change > 5:
                score += price_change * 2
        elif strategy == "TAKE_PROFIT":
            # Favor high liquidity for easy exits
            score += liquidity_score * 2
        elif strategy == "MEAN_REVERSION":
            # Favor recent dips with good fundamentals
            if -5 < price_change < 0:
                score += abs(price_change) * 3
        else:
            # Default: balanced approach
            if price_change > 0:
                score += price_change
        
        return score
    
    async def execute_autonomous_trade(self, candidate: Dict):
        """Execute trade based on autonomous analysis."""
        symbol = candidate["symbol"]
        
        # Calculate position size
        available = self.balance * self.max_position_size
        amount = min(available, 150)  # Max $150 per trade
        
        if amount < 10:
            print(f"⚠️  Insufficient balance")
            return
        
        print(f"\n💡 Trading Decision:", flush=True)
        print(f"   Token: {symbol} ({candidate['name']})", flush=True)
        print(f"   Chain: {candidate['chain']}", flush=True)
        print(f"   Price: ${candidate['price']:.6f}", flush=True)
        print(f"   Liquidity: ${candidate['liquidity']:,.0f}", flush=True)
        print(f"   24h Change: {candidate['price_change_24h']:+.2f}%", flush=True)
        print(f"   Amount: ${amount:.2f}", flush=True)
        print(f"   Reason: Autonomous research + Hive Mind strategy", flush=True)
        
        # Execute trade
        try:
            print(f"\n🚀 Executing BUY {symbol}...", flush=True)
            
            result = await darwin_trade(
                "buy", 
                symbol, 
                amount, 
                f"Autonomous research: {candidate['price_change_24h']:+.1f}% momentum, ${candidate['liquidity']:,.0f} liquidity"
            )
            
            if result.get("status") == "success":
                print(f"✅ Trade successful!")
                print(f"   {result.get('message', '')}")
                
                self.balance = result.get("balance", self.balance)
                self.positions = result.get("positions", self.positions)
            else:
                print(f"❌ Trade failed: {result.get('message')}")
                
        except Exception as e:
            print(f"❌ Trade execution error: {e}")
    
    async def cleanup(self):
        """Clean up resources."""
        print("\n🧹 Cleaning up...")
        
        if self.connected:
            await darwin_disconnect()
        
        if self.session and not self.session.closed:
            await self.session.close()
        
        print("✅ Cleanup complete")


async def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python autonomous_strategy.py <agent_id> [arena_url] [api_key]")
        print("\nExample:")
        print("  python autonomous_strategy.py MyTrader")
        print("  python autonomous_strategy.py MyTrader wss://www.darwinx.fun dk_abc123")
        sys.exit(1)
    
    agent_id = sys.argv[1]
    arena_url = sys.argv[2] if len(sys.argv) > 2 else "wss://www.darwinx.fun"
    api_key = sys.argv[3] if len(sys.argv) > 3 else None
    
    strategy = AutonomousStrategy(agent_id, arena_url, api_key)
    await strategy.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
