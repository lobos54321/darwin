"""
🧪 Strategy Sandbox - Quick Usage Example

演示如何使用沙盒系统测试策略
"""

import asyncio
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from arena_server.strategy_sandbox import test_strategy_code


# 示例策略：简单的均值回归
EXAMPLE_STRATEGY = """
import math
from collections import deque

class MyStrategy:
    def __init__(self):
        self.capital = 10000.0
        self.lookback = 50
        self.data = {}
        self.positions = {}
        self.entry_threshold = 0.95  # 价格低于均值5%时买入
        self.exit_threshold = 1.02   # 价格高于均值2%时卖出

    def on_tick(self, market_data):
        orders = []
        prices = market_data.get('prices', {})
        liquidities = market_data.get('liquidities', {})

        for symbol, price in prices.items():
            # 流动性过滤
            if liquidities.get(symbol, 0) < 500000:
                continue

            # 初始化数据
            if symbol not in self.data:
                self.data[symbol] = deque(maxlen=self.lookback)

            self.data[symbol].append(price)

            # 等待足够数据
            if len(self.data[symbol]) < self.lookback:
                continue

            # 计算均值
            avg_price = sum(self.data[symbol]) / len(self.data[symbol])

            # 买入信号
            if price < avg_price * self.entry_threshold and symbol not in self.positions:
                amount = (self.capital * 0.3) / price
                orders.append({
                    'symbol': symbol,
                    'side': 'BUY',
                    'amount': amount,
                })
                self.positions[symbol] = {'amount': amount, 'entry_price': price}

            # 卖出信号
            elif price > avg_price * self.exit_threshold and symbol in self.positions:
                orders.append({
                    'symbol': symbol,
                    'side': 'SELL',
                    'amount': self.positions[symbol]['amount'],
                })
                del self.positions[symbol]

        return orders
"""


async def main():
    """主函数"""
    print("🧪 Strategy Sandbox - Quick Example")
    print("=" * 60)

    # 测试策略
    print("\n📝 Testing strategy code...")
    print("   Backtest rounds: 15")
    print("   Ticks per round: 100")

    result = await test_strategy_code(
        code=EXAMPLE_STRATEGY,
        agent_id="example_agent",
        backtest_rounds=15
    )

    # 显示结果
    print("\n" + "=" * 60)
    print("📊 TEST RESULTS")
    print("=" * 60)

    if result.passed:
        print("✅ Status: PASSED")
        print(f"\n📈 Performance Metrics:")
        print(f"   Total PnL: {result.predicted_pnl:+.2f}%")
        print(f"   Avg PnL/Round: {result.avg_pnl_per_round:+.2f}%")
        print(f"   Win Rate: {result.win_rate:.1%}")
        print(f"   Max Drawdown: {result.max_drawdown:.2f}%")
        print(f"   Backtest Rounds: {result.backtest_rounds}")
        print(f"\n⏱️ Execution Time: {result.execution_time:.3f}s")
        print("\n✅ Strategy is ready for deployment!")

    else:
        print("❌ Status: FAILED")
        print(f"\n🚫 Error Type: {result.error_type}")
        print(f"   Error Message: {result.error_message}")

        if result.syntax_errors:
            print(f"\n📝 Syntax Errors:")
            for error in result.syntax_errors:
                print(f"   - {error}")

        if result.security_violations:
            print(f"\n🔒 Security Violations:")
            for violation in result.security_violations:
                print(f"   - {violation}")

        if result.runtime_errors:
            print(f"\n💥 Runtime Errors:")
            for error in result.runtime_errors[:5]:  # 显示前5条
                print(f"   - {error}")

    # 显示详细日志（可选）
    print("\n" + "=" * 60)
    print("📋 DETAILED LOG")
    print("=" * 60)
    for log_line in result.test_log:
        print(log_line)

    print("\n" + "=" * 60)
    print("✨ Example completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
