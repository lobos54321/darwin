#!/usr/bin/env python3
"""
Darwin Arena - Baseline Auto-Trading Strategy
Autonomous trading agent that learns from collective intelligence.

This strategy:
1. Connects to Darwin Arena
2. Fetches Hive Mind recommendations every 2 minutes
3. Analyzes market data from DexScreener
4. Makes trading decisions using LLM reasoning
5. Executes trades with risk management
6. Receives and applies hot patches from attribution analysis
"""

import asyncio
import json
import sys
import time
from typing import Dict, List, Optional, Any
import aiohttp
from datetime import datetime

# Import the darwin_trader tool functions
from darwin_trader import (
    darwin_connect, 
    darwin_trade, 
    darwin_status, 
    darwin_disconnect,
    get_strategy_weights,
    get_council_trades
)

class BaselineStrategy:
    """
    Baseline trading strategy that learns from Hive Mind.
    """
    
    def __init__(self, agent_id: str, arena_url: str = "wss://www.darwinx.fun", api_key: str = None):
        self.agent_id = agent_id
        self.arena_url = arena_url
        self.api_key = api_key
        self.http_base = arena_url.replace("wss://", "https://").replace("ws://", "http://")
        self.session: Optional[aiohttp.ClientSession] = None
        self.connected = False
        self.tokens = []
        self.balance = 1000
        self.positions = {}
        self.last_hive_mind = None
        self.last_prices = {}
        
        # Risk management
        self.max_position_size = 0.15  # 15% per trade
        self.stop_loss = -0.05  # -5%
        self.take_profit = 0.04  # +4%
        self.max_positions = 4
        
        # Strategy weights (updated by hot patches)
        self.strategy_weights = {}  # Will be populated by hot patches
        
    async def start(self):
        """Initialize and start the trading loop."""
        print(f"🧬 Darwin Arena Baseline Strategy", flush=True)
        print(f"Agent: {self.agent_id}", flush=True)
        print(f"Arena: {self.arena_url}", flush=True)
        print("=" * 60, flush=True)
        
        # Create HTTP session
        print("Creating HTTP session", flush=True)
        self.session = aiohttp.ClientSession()
        
        # Connect to arena
        print("\n📡 Connecting to arena...", flush=True)
        
        # Check if API key is needed
        if not self.api_key:
            # Check if connecting to remote server
            if "darwinx.fun" in self.arena_url or "localhost" not in self.arena_url:
                print("⚠️  No API key provided!", flush=True)
                print("   For remote connections, you need an API key.", flush=True)
                print("   Get one at: https://www.darwinx.fun", flush=True)
                print("   Or run locally: python3 baseline_strategy.py YourAgent ws://localhost:8000", flush=True)
                print("\n   Attempting connection anyway (will fail if not whitelisted)...", flush=True)
        
        print("About to call darwin_connect", flush=True)
        result = await darwin_connect(self.agent_id, self.arena_url, self.api_key)
        print(f"darwin_connect returned: {result.get('status')}", flush=True)
        
        if result.get("status") != "connected":
            print(f"❌ Connection failed: {result.get('message')}", flush=True)
            return
        
        self.connected = True
        self.tokens = result.get("tokens", [])
        self.balance = result.get("balance", 1000)
        
        print(f"✅ Connected!", flush=True)
        print(f"💰 Starting balance: ${self.balance}", flush=True)
        print(f"📊 Token pool: {', '.join(self.tokens)}", flush=True)
        print(flush=True)
        
        # Start trading loop
        print("About to start trading_loop", flush=True)
        await self.trading_loop()
        print("trading_loop finished", flush=True)
        
    async def trading_loop(self):
        """Main trading loop - runs every 2 minutes."""
        print("Entered trading_loop", flush=True)
        iteration = 0
        
        try:
            while self.connected:
                iteration += 1
                print(f"\n{'='*60}", flush=True)
                print(f"🔄 Iteration {iteration} - {datetime.now().strftime('%H:%M:%S')}", flush=True)
                print(f"{'='*60}", flush=True)
                
                # 1. Fetch Hive Mind recommendations
                print("Step 1: fetch_hive_mind", flush=True)
                await self.fetch_hive_mind()
                
                # 2. Get current status
                print("Step 2: update_status", flush=True)
                await self.update_status()
                
                # 3. Check existing positions for stop-loss/take-profit
                print("Step 3: manage_positions", flush=True)
                await self.manage_positions()
                
                # 4. Look for new opportunities
                print("Step 4: find_opportunities", flush=True)
                if len(self.positions) < self.max_positions:
                    await self.find_opportunities()
                else:
                    print(f"⏸️  Max positions ({self.max_positions}) reached, skipping new trades", flush=True)
                
                # 5. Wait 2 minutes
                print(f"\n⏰ Waiting 2 minutes until next iteration...", flush=True)
                await asyncio.sleep(120)
                
        except KeyboardInterrupt:
            print("\n\n🛑 Stopping strategy...")
        except Exception as e:
            print(f"\n❌ Error in trading loop: {e}")
        finally:
            await self.cleanup()
    
    async def fetch_hive_mind(self):
        """Fetch collective intelligence recommendations from Hive Mind."""
        try:
            print("\n🧠 Fetching Hive Mind recommendations...", flush=True)
            
            print(f"Making GET request to {self.http_base}/hive-mind", flush=True)
            async with self.session.get(f"{self.http_base}/hive-mind") as resp:
                print(f"Got response status: {resp.status}", flush=True)
                if resp.status != 200:
                    print(f"⚠️  Hive Mind unavailable (status {resp.status})", flush=True)
                    return
                
                print("Parsing JSON", flush=True)
                data = await resp.json()
                self.last_hive_mind = data
                
                epoch = data.get("epoch", "?")
                print(f"📊 Epoch {epoch}", flush=True)
                
                # Find our group
                groups = data.get("groups", {})
                print(f"Found {len(groups)} groups", flush=True)
                for group_id, group_data in groups.items():
                    print(f"Checking group {group_id}", flush=True)
                    group_tokens = group_data.get("tokens", [])
                    print(f"  Group tokens: {group_tokens}", flush=True)
                    print(f"  Our tokens: {self.tokens}", flush=True)
                    if set(group_tokens) == set(self.tokens):
                        print(f"🏢 Group {group_id}: {', '.join(group_tokens)}", flush=True)
                        
                        # Show alpha report summary
                        alpha_report = group_data.get("alpha_report", {})
                        if alpha_report:
                            print(f"\n📈 Strategy Performance:", flush=True)
                            for strategy, stats in list(alpha_report.items())[:3]:
                                win_rate = stats.get("win_rate", 0)
                                avg_pnl = stats.get("avg_pnl", 0)
                                impact = stats.get("impact", "UNKNOWN")
                                print(f"   {strategy}: {win_rate:.1f}% win rate, {avg_pnl:+.2f}% avg PnL ({impact})", flush=True)
                        break
                
                print("fetch_hive_mind completed", flush=True)
                        
        except Exception as e:
            print(f"⚠️  Failed to fetch Hive Mind: {e}")
    
    async def update_status(self):
        """Get current account status."""
        try:
            result = await darwin_status()
            
            if result.get("status") == "success":
                self.balance = result.get("balance", self.balance)
                positions = result.get("positions", [])
                
                # Update positions dict
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
    
    async def manage_positions(self):
        """Check existing positions for stop-loss or take-profit."""
        if not self.positions:
            return
        
        print(f"\n🔍 Checking positions for exit signals...")
        
        for symbol in list(self.positions.keys()):
            quantity = self.positions[symbol]
            
            # Get current price from last state
            current_price = None
            if self.last_state:
                prices = self.last_state.get("prices", {})
                current_price = prices.get(symbol)
            
            if not current_price:
                continue
            
            # Calculate position value
            position_value = quantity * current_price
            
            # Get entry price from positions data
            entry_price = None
            if self.last_state:
                positions = self.last_state.get("positions", [])
                for pos in positions:
                    if pos.get("symbol") == symbol:
                        entry_price = pos.get("entry_price")
                        break
            
            if not entry_price:
                continue
            
            # Calculate P&L percentage
            pnl_pct = (current_price - entry_price) / entry_price
            
            # Check stop-loss
            if pnl_pct <= self.stop_loss:
                print(f"🛑 Stop-loss triggered for {symbol}: {pnl_pct*100:.2f}%")
                await self.execute_trade("sell", symbol, position_value, ["STOP_LOSS"])
            
            # Check take-profit
            elif pnl_pct >= self.take_profit:
                print(f"🎯 Take-profit triggered for {symbol}: {pnl_pct*100:.2f}%")
                await self.execute_trade("sell", symbol, position_value, ["TAKE_PROFIT"])
    
    async def find_opportunities(self):
        """Analyze market and find trading opportunities."""
        print(f"\n🔎 Scanning for opportunities...")
        
        # Simple baseline strategy:
        # 1. Look at Hive Mind recommendations
        # 2. Check which tokens in our pool have positive signals
        # 3. Pick the best one and buy
        
        if not self.last_hive_mind:
            print("⚠️  No Hive Mind data available")
            return
        
        # Find our group's alpha report
        groups = self.last_hive_mind.get("groups", {})
        alpha_report = None
        
        for group_id, group_data in groups.items():
            group_tokens = group_data.get("tokens", [])
            if set(group_tokens) == set(self.tokens):
                alpha_report = group_data.get("alpha_report", {})
                break
        
        if not alpha_report:
            print("⚠️  No alpha report available")
            return
        
        # Find best performing strategy (with hot patch weights applied)
        best_strategy = None
        best_score = -999999
        
        # Get current strategy weights from hot patches
        self.strategy_weights = get_strategy_weights()
        
        for strategy, stats in alpha_report.items():
            impact = stats.get("impact", "UNKNOWN")
            score = stats.get("score", 0)
            
            # Apply hot patch weight (default 0.5 if not set)
            weight = self.strategy_weights.get(strategy, 0.5)
            adjusted_score = score * weight
            
            if impact == "POSITIVE" and adjusted_score > best_score:
                best_score = adjusted_score
                best_strategy = strategy
        
        if not best_strategy:
            print("⚠️  No positive strategies found")
            return
        
        weight_info = f" (weight: {self.strategy_weights.get(best_strategy, 0.5):.1f})" if best_strategy in self.strategy_weights else ""
        print(f"✨ Best strategy: {best_strategy} (score: {best_score:.2f}){weight_info}")
        
        # Get token recommendations from this strategy
        strategy_data = alpha_report[best_strategy]
        by_token = strategy_data.get("by_token", {})
        
        # If best strategy has no token data, scan all strategies
        if not by_token:
            print("⚠️  Best strategy has no token data, scanning all strategies...")
            by_token = {}
            for strategy, stats in alpha_report.items():
                strategy_tokens = stats.get("by_token", {})
                for token, token_stats in strategy_tokens.items():
                    if token not in by_token:
                        by_token[token] = token_stats
                    else:
                        # Merge stats (use better performing one)
                        if token_stats.get("avg_pnl", 0) > by_token[token].get("avg_pnl", 0):
                            by_token[token] = token_stats
        
        # Find best token
        best_token = None
        best_token_score = -999999
        
        for token, token_stats in by_token.items():
            # 🔓 No longer restrict to group tokens - agents can discover any token
            if token in self.positions:
                continue  # Already holding
            
            win_rate = token_stats.get("win_rate", 0)
            avg_pnl = token_stats.get("avg_pnl", 0)
            
            # Simple scoring: win_rate * avg_pnl
            token_score = win_rate * avg_pnl if avg_pnl > 0 else -999999
            
            if token_score > best_token_score:
                best_token_score = token_score
                best_token = token
        
        if not best_token:
            print("⚠️  No suitable tokens found with positive performance")
            return
        
        # Calculate position size
        available = self.balance * self.max_position_size
        amount = min(available, 150)  # Max $150 per trade
        
        if amount < 10:
            print(f"⚠️  Insufficient balance for trade (${amount:.2f})")
            return
        
        print(f"\n💡 Opportunity found!")
        print(f"   Token: {best_token}")
        print(f"   Strategy: {best_strategy}")
        print(f"   Amount: ${amount:.2f}")
        print(f"   Reason: Following Hive Mind collective intelligence")
        
        # Execute trade with strategy tag as list
        await self.execute_trade("buy", best_token, amount, [best_strategy])
    
    async def execute_trade(self, action: str, symbol: str, amount: float, reason: list):
        """Execute a trade."""
        try:
            print(f"\n🚀 Executing {action.upper()} {symbol}...")
            
            result = await darwin_trade(action, symbol, amount, reason)
            
            if result.get("status") == "success":
                print(f"✅ Trade successful!")
                print(f"   {result.get('message', '')}")
                
                # Update local state
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
    print("In main()", flush=True)
    if len(sys.argv) < 2:
        print("Usage: python baseline_strategy.py <agent_id> [arena_url] [api_key]")
        print("\nExample:")
        print("  python baseline_strategy.py MyTrader")
        print("  python baseline_strategy.py MyTrader wss://www.darwinx.fun")
        print("  python baseline_strategy.py MyTrader wss://www.darwinx.fun dk_abc123")
        sys.exit(1)
    
    print("Parsing args", flush=True)
    agent_id = sys.argv[1]
    arena_url = sys.argv[2] if len(sys.argv) > 2 else "wss://www.darwinx.fun"
    api_key = sys.argv[3] if len(sys.argv) > 3 else None
    
    print(f"Creating strategy for {agent_id}", flush=True)
    strategy = BaselineStrategy(agent_id, arena_url, api_key)
    print("Starting strategy", flush=True)
    await strategy.start()


if __name__ == "__main__":
    print("Script starting immediately", flush=True)
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
