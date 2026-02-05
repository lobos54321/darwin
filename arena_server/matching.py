"""
模拟撮合引擎
处理 Agent 的虚拟交易，计算盈亏
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum
from collections import deque
from config import INITIAL_BALANCE, SIMULATED_SLIPPAGE


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
    positions: Dict[str, Position] = field(default_factory=dict)
    orders: List[Order] = field(default_factory=list)
    pnl_history: List[float] = field(default_factory=list)
    
    @property
    def total_value(self) -> float:
        """总资产价值"""
        positions_value = sum(p.value for p in self.positions.values())
        return self.balance + positions_value
    
    @property
    def pnl(self) -> float:
        """总盈亏"""
        return self.total_value - INITIAL_BALANCE
    
    @property
    def pnl_percent(self) -> float:
        """盈亏百分比"""
        return (self.pnl / INITIAL_BALANCE) * 100


class MatchingEngine:
    """模拟撮合引擎"""
    
    def __init__(self):
        self.accounts: Dict[str, AgentAccount] = {}
        self.agents = self.accounts  # Alias for compatibility
        self.current_prices: Dict[str, float] = {}
        self.order_count = 0
        self.trade_history: deque = deque(maxlen=50) # Rolling history of last 50 trades
    
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
        """计算盈亏百分比"""
        account = self.accounts.get(agent_id)
        return account.pnl_percent if account else 0.0
    
    def register_agent(self, agent_id: str) -> AgentAccount:
        """注册新 Agent"""
        if agent_id not in self.accounts:
            self.accounts[agent_id] = AgentAccount(agent_id=agent_id)
        return self.accounts[agent_id]
    
    def update_prices(self, prices: Dict[str, dict]):
        """更新当前价格"""
        for symbol, data in prices.items():
            self.current_prices[symbol] = data["priceUsd"]
        
        # 更新所有持仓的价值
        for account in self.accounts.values():
            for symbol, position in account.positions.items():
                if symbol in self.current_prices:
                    # 只更新用于计算的当前价格，不改变 avg_price
                    pass
    
    def get_account(self, agent_id: str) -> Optional[AgentAccount]:
        """获取账户"""
        return self.accounts.get(agent_id)
    
    def execute_order(self, agent_id: str, symbol: str, side: OrderSide, amount_usd: float, reason: List[str] = None) -> tuple:
        """执行订单
        
        Returns:
            tuple: (success: bool, message: str, fill_price: float)
        """
        account = self.accounts.get(agent_id)
        if not account:
            return (False, "Account not found", 0.0)
        
        if symbol not in self.current_prices:
            return (False, f"Unknown symbol: {symbol}", 0.0)
        
        current_price = self.current_prices[symbol]
        
        # 应用滑点
        if side == OrderSide.BUY:
            fill_price = current_price * (1 + SIMULATED_SLIPPAGE)
        else:
            fill_price = current_price * (1 - SIMULATED_SLIPPAGE)
        
        if side == OrderSide.BUY:
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
            
            # Record trade with TAGS
            self.trade_history.appendleft({
                "time": datetime.now().strftime("%H:%M:%S"),
                "agent": agent_id,
                "side": "BUY",
                "symbol": symbol,
                "amount": token_amount,
                "price": fill_price,
                "value": amount_usd,
                "reason": reason or [] # Store the strategy tags
            })
            
            print(f"✅ {agent_id} BUY {token_amount:.4f} {symbol} @ ${fill_price:.4f} Tags:{reason}")
            return (True, f"Bought {token_amount:.4f} {symbol}", fill_price)
            
        else:  # SELL
            token_amount = amount_usd / fill_price
            
            if symbol not in account.positions or account.positions[symbol].amount < token_amount:
                return (False, "Insufficient position to sell", 0.0)
            
            pos = account.positions[symbol]
            pos.amount -= token_amount
            account.balance += token_amount * fill_price
            
            if pos.amount <= 0:
                del account.positions[symbol]
            
            self.order_count += 1
            
            # Record trade
            self.trade_history.appendleft({
                "time": datetime.now().strftime("%H:%M:%S"),
                "agent": agent_id,
                "side": "SELL",
                "symbol": symbol,
                "amount": token_amount,
                "price": fill_price,
                "value": token_amount * fill_price
            })
            
            print(f"✅ {agent_id} SELL {token_amount:.4f} {symbol} @ ${fill_price:.4f}")
            return (True, f"Sold {token_amount:.4f} {symbol}", fill_price)
    
    def get_leaderboard(self) -> List[tuple]:
        """获取排行榜"""
        # 先更新所有持仓价值
        for account in self.accounts.values():
            for symbol, position in account.positions.items():
                if symbol in self.current_prices:
                    position.avg_price = self.current_prices[symbol]  # 用当前价计算价值
        
        rankings = [
            (account.agent_id, account.pnl_percent, account.total_value)
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
    engine.execute_order("Agent_001", "CLANKER", OrderSide.BUY, 500)
    engine.execute_order("Agent_002", "MOLT", OrderSide.BUY, 300)
    
    # 价格变动
    engine.update_prices({
        "CLANKER": {"priceUsd": 38.0},  # +8.5%
        "MOLT": {"priceUsd": 0.045},     # -10%
    })
    
    engine.print_leaderboard()
