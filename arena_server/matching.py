"""
模拟撮合引擎
处理 Agent 的虚拟交易，计算盈亏

支持任意币种交易 - Agents 可以交易任何 DexScreener 上的代币
"""

import aiohttp
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum
from collections import deque
from config import INITIAL_BALANCE, SIMULATED_SLIPPAGE

# DexScreener API
DEXSCREENER_BASE_URL = "https://api.dexscreener.com/latest/dex"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Position:
    """持仓"""
    symbol: str
    amount: float = 0.0
    avg_price: float = 0.0
    
    @property
    def value(self) -> float:
        return self.amount * self.avg_price


@dataclass
class Order:
    """订单"""
    id: str
    agent_id: str
    symbol: str
    side: OrderSide
    amount: float
    price: float
    timestamp: datetime = field(default_factory=datetime.now)
    filled: bool = False
    fill_price: Optional[float] = None


@dataclass
class AgentAccount:
    """Agent 账户"""
    agent_id: str
    balance: float = INITIAL_BALANCE  # USDC
    initial_balance: float = INITIAL_BALANCE
    positions: Dict[str, Position] = field(default_factory=dict)
    orders: List[Order] = field(default_factory=list)
    pnl_history: List[float] = field(default_factory=list)

    def get_total_value(self, current_prices: Dict[str, float] = None) -> float:
        """总资产价值 (用当前市场价估值，不破坏 avg_price)"""
        positions_value = 0.0
        for sym, pos in self.positions.items():
            if current_prices and sym in current_prices:
                positions_value += pos.amount * current_prices[sym]
            else:
                positions_value += pos.amount * pos.avg_price
        return self.balance + positions_value

    @property
    def total_value(self) -> float:
        """总资产价值 (基于 avg_price，仅在无市场价时使用)"""
        positions_value = sum(p.value for p in self.positions.values())
        return self.balance + positions_value

    def get_pnl(self, current_prices: Dict[str, float] = None) -> float:
        """总盈亏"""
        return self.get_total_value(current_prices) - self.initial_balance

    def get_pnl_percent(self, current_prices: Dict[str, float] = None) -> float:
        """盈亏百分比"""
        return (self.get_pnl(current_prices) / self.initial_balance) * 100

    @property
    def pnl(self) -> float:
        """总盈亏 (基于 avg_price)"""
        return self.total_value - self.initial_balance

    @property
    def pnl_percent(self) -> float:
        """盈亏百分比 (基于 avg_price)"""
        return (self.pnl / self.initial_balance) * 100


class MatchingEngine:
    """模拟撮合引擎"""
    
    def __init__(self):
        self.accounts: Dict[str, AgentAccount] = {}
        self.agents = self.accounts  # Alias for compatibility
        self.current_prices: Dict[str, float] = {}
        self.token_metadata: Dict[str, dict] = {}  # Store chain and contract_address
        self.order_count = 0
        self.trade_history: deque = deque(maxlen=500) # Rolling history for Hive Mind attribution
    
    def get_balance(self, agent_id: str) -> float:
        """获取账户余额"""
        account = self.accounts.get(agent_id)
        return account.balance if account else 0.0
    
    def get_positions(self, agent_id: str) -> Dict[str, dict]:
        """获取持仓信息"""
        account = self.accounts.get(agent_id)
        if not account:
            return {}
        return {
            symbol: {"amount": pos.amount, "avg_price": pos.avg_price, "value": pos.amount * self.current_prices.get(symbol, pos.avg_price)}
            for symbol, pos in account.positions.items()
        }
    
    def calculate_pnl(self, agent_id: str) -> float:
        """计算盈亏百分比 (基于当前市场价)"""
        account = self.accounts.get(agent_id)
        if not account:
            return 0.0
        return account.get_pnl_percent(self.current_prices)
    
    def register_agent(self, agent_id: str) -> AgentAccount:
        """注册新 Agent"""
        if agent_id not in self.accounts:
            self.accounts[agent_id] = AgentAccount(agent_id=agent_id)
        return self.accounts[agent_id]
    
    def update_prices(self, prices: Dict[str, dict]):
        """更新当前价格"""
        for symbol, data in prices.items():
            if "priceUsd" in data:
                self.current_prices[symbol] = data["priceUsd"]
    
    def get_account(self, agent_id: str) -> Optional[AgentAccount]:
        """获取账户"""
        return self.accounts.get(agent_id)

    async def _fetch_price_realtime(self, symbol: str) -> Optional[float]:
        """实时从 DexScreener 获取价格（支持任意币种）

        尝试通过 symbol 搜索代币，返回流动性最高的交易对价格
        """
        try:
            url = f"{DEXSCREENER_BASE_URL}/search?q={symbol}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pairs = data.get("pairs", [])

                        if not pairs:
                            return None

                        # 过滤：只要 baseToken.symbol 匹配的
                        matching_pairs = [
                            p for p in pairs
                            if p.get("baseToken", {}).get("symbol", "").upper() == symbol.upper()
                        ]

                        if not matching_pairs:
                            return None

                        # 取流动性最高的交易对
                        best_pair = max(
                            matching_pairs,
                            key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0)
                        )

                        price = float(best_pair.get("priceUsd", 0))
                        if price > 0:
                            return price

        except Exception as e:
            print(f"Error fetching price for {symbol}: {e}")

        return None

    async def execute_order(self, agent_id: str, symbol: str, side: OrderSide, amount_usd: float, reason: List[str] = None, chain: str = None, contract_address: str = None) -> tuple:
        """执行订单 - 支持任意币种

        如果币种不在缓存中，会实时从 DexScreener 获取价格

        Args:
            agent_id: Agent ID
            symbol: Token symbol
            side: BUY or SELL
            amount_usd: Amount in USD (for BUY) or token quantity (for SELL)
            reason: Strategy tags
            chain: Blockchain name (e.g., "base", "ethereum", "solana")
            contract_address: Token contract address

        Returns:
            tuple: (success: bool, message: str, fill_price: float)
        """
        account = self.accounts.get(agent_id)
        if not account:
            return (False, "Account not found", 0.0)

        # 获取当前价格（如果不在缓存中，实时获取）
        current_price = self.current_prices.get(symbol)

        # Store chain and contract_address if provided
        if chain or contract_address:
            if symbol not in self.token_metadata:
                self.token_metadata[symbol] = {}
            if chain:
                self.token_metadata[symbol]["chain"] = chain
            if contract_address:
                self.token_metadata[symbol]["contract_address"] = contract_address

        if current_price is None:
            # 实时从 DexScreener 获取价格
            try:
                current_price = await self._fetch_price_realtime(symbol)

                if current_price is None:
                    return (False, f"Cannot fetch price for symbol: {symbol}. Please ensure it exists on DexScreener.", 0.0)

                # 缓存价格
                self.current_prices[symbol] = current_price

            except Exception as e:
                return (False, f"Error fetching price for {symbol}: {str(e)}", 0.0)

        # 应用滑点
        if side == OrderSide.BUY:
            fill_price = current_price * (1 + SIMULATED_SLIPPAGE)
        else:
            fill_price = current_price * (1 - SIMULATED_SLIPPAGE)
        
        if side == OrderSide.BUY:
            # Minimum trade size guard
            if amount_usd < 0.01:
                return (False, f"Trade value too small: ${amount_usd:.6f}", 0.0)
            # 检查余额
            if account.balance < amount_usd:
                return (False, f"Insufficient balance: {account.balance:.2f} < {amount_usd:.2f}", 0.0)
            
            token_amount = amount_usd / fill_price
            
            # 扣款
            account.balance -= amount_usd
            
            # 更新持仓
            if symbol not in account.positions:
                account.positions[symbol] = Position(symbol=symbol)
            
            pos = account.positions[symbol]
            new_amount = pos.amount + token_amount
            pos.avg_price = ((pos.amount * pos.avg_price) + (token_amount * fill_price)) / new_amount if new_amount > 0 else 0
            pos.amount = new_amount
            
            self.order_count += 1

            # Get token metadata
            token_meta = self.token_metadata.get(symbol, {})

            # Record trade with TAGS + chain + contract_address
            self.trade_history.appendleft({
                "time": datetime.now().isoformat(),
                "agent_id": agent_id,
                "side": "BUY",
                "symbol": symbol,
                "chain": token_meta.get("chain", "unknown"),
                "contract_address": token_meta.get("contract_address", ""),
                "amount": token_amount,
                "price": fill_price,
                "value": amount_usd,
                "reason": reason or [],
                "trade_pnl": None  # Unknown until position is closed
            })
            
            print(f"✅ {agent_id} BUY {token_amount:.4f} {symbol} @ ${fill_price:.4f} Tags:{reason}")
            return (True, f"Bought {token_amount:.4f} {symbol}", fill_price)
            
        else:  # SELL
            token_amount = amount_usd / fill_price

            if symbol not in account.positions or account.positions[symbol].amount < token_amount:
                return (False, "Insufficient position to sell", 0.0)

            pos = account.positions[symbol]

            # Guard: reject dust trades worth less than $0.01
            sell_value = token_amount * fill_price
            if sell_value < 0.01:
                # Auto-clean dust position
                if pos.amount * fill_price < 0.01:
                    del account.positions[symbol]
                return (False, f"Trade value too small: ${sell_value:.6f}", 0.0)

            pos.amount -= token_amount
            account.balance += sell_value

            if pos.amount <= 0 or (pos.amount * fill_price < 0.01):
                del account.positions[symbol]
            
            self.order_count += 1

            # Compute per-trade PnL for this sell
            trade_pnl = ((fill_price - pos.avg_price) / pos.avg_price * 100) if pos.avg_price > 0 else 0

            # Get token metadata
            token_meta = self.token_metadata.get(symbol, {})

            # Record trade with TAGS + per-trade PnL + chain + contract_address
            self.trade_history.appendleft({
                "time": datetime.now().isoformat(),
                "agent_id": agent_id,
                "side": "SELL",
                "symbol": symbol,
                "chain": token_meta.get("chain", "unknown"),
                "contract_address": token_meta.get("contract_address", ""),
                "amount": token_amount,
                "price": fill_price,
                "value": token_amount * fill_price,
                "entry_price": pos.avg_price,
                "trade_pnl": round(trade_pnl, 2),
                "reason": reason or []  # SELL tags: TAKE_PROFIT, STOP_LOSS, etc.
            })

            print(f"✅ {agent_id} SELL {token_amount:.4f} {symbol} @ ${fill_price:.4f} PnL:{trade_pnl:+.1f}% Tags:{reason}")
            return (True, f"Sold {token_amount:.4f} {symbol}", fill_price)
    
    @property
    def last_prices(self) -> Dict[str, float]:
        """Alias for current_prices (compatibility)"""
        return self.current_prices

    async def refresh_all_position_prices(self):
        """刷新所有持仓代币的价格（用于准确的 PnL 计算）"""
        # 收集所有持仓代币
        all_symbols = set()
        for account in self.accounts.values():
            all_symbols.update(account.positions.keys())

        # 批量获取价格
        for symbol in all_symbols:
            if symbol not in self.current_prices:
                try:
                    price = await self._fetch_price_realtime(symbol)
                    if price:
                        self.current_prices[symbol] = price
                except Exception as e:
                    logger.error(f"Failed to refresh price for {symbol}: {e}")

    async def refresh_all_position_prices(self) -> int:
        """刷新所有持仓代币的价格（用于准确的 PnL 计算）

        Returns:
            int: 成功更新的代币数量
        """
        # 收集所有持仓代币
        symbols = set()
        for account in self.accounts.values():
            symbols.update(account.positions.keys())

        if not symbols:
            return 0

        updated = 0
        for symbol in symbols:
            try:
                price = await self._fetch_price_realtime(symbol)
                if price and price > 0:
                    self.current_prices[symbol] = price
                    updated += 1
            except Exception as e:
                print(f"Failed to refresh price for {symbol}: {e}")

        return updated

    def get_leaderboard(self) -> List[tuple]:
        """获取排行榜 (使用当前市场价计算，不修改 avg_price)"""
        rankings = [
            (account.agent_id,
             account.get_pnl_percent(self.current_prices),
             account.get_total_value(self.current_prices))
            for account in self.accounts.values()
        ]
        rankings.sort(key=lambda x: x[1], reverse=True)
        return rankings
    
    def print_leaderboard(self):
        """打印排行榜"""
        rankings = self.get_leaderboard()
        print("\n🏆 Leaderboard")
        print("-" * 50)
        for i, (agent_id, pnl_pct, total) in enumerate(rankings, 1):
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "  "
            print(f"{emoji} #{i} {agent_id}: {pnl_pct:+.2f}% (${total:,.2f})")


# 测试
if __name__ == "__main__":
    import asyncio
    
    async def test():
        engine = MatchingEngine()
        
        # 注册测试 Agent
        engine.register_agent("Agent_001")
        engine.register_agent("Agent_002")
        
        # 模拟价格
        engine.update_prices({
            "CLANKER": {"priceUsd": 35.0},
            "MOLT": {"priceUsd": 0.05},
        })
        
        # 执行交易
        await engine.execute_order("Agent_001", "CLANKER", OrderSide.BUY, 500)
        await engine.execute_order("Agent_002", "MOLT", OrderSide.BUY, 300)
        
        # 价格变动
        engine.update_prices({
            "CLANKER": {"priceUsd": 38.0},  # +8.5%
            "MOLT": {"priceUsd": 0.045},     # -10%
        })
        
        engine.print_leaderboard()
    
    asyncio.run(test())
