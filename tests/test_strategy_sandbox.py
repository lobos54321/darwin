"""
🧪 Strategy Sandbox Testing - Test Suite

测试沙盒系统的各个功能：
1. 语法验证
2. 安全检查
3. 结构验证
4. 回测执行
5. 完整集成测试
"""

import asyncio
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from arena_server.strategy_sandbox import (
    SecurityValidator,
    SandboxExecutor,
    BacktestEngine,
    StrategySandbox,
    test_strategy_code,
    validate_strategy_before_submission,
)


# ========== 测试用例：策略代码 ==========

# ✅ 合法策略
VALID_STRATEGY = """
import math
import random
from collections import deque

class MyStrategy:
    def __init__(self):
        self.capital = 10000.0
        self.lookback = 50
        self.data = {}
        self.positions = {}

    def on_tick(self, market_data):
        orders = []
        tick = market_data.get('tick', 0)
        prices = market_data.get('prices', {})

        for symbol, price in prices.items():
            # 初始化数据
            if symbol not in self.data:
                self.data[symbol] = deque(maxlen=self.lookback)

            self.data[symbol].append(price)

            # 简单的均值回归策略
            if len(self.data[symbol]) >= self.lookback:
                avg_price = sum(self.data[symbol]) / len(self.data[symbol])

                # 买入信号：价格低于均值5%
                if price < avg_price * 0.95 and symbol not in self.positions:
                    amount = (self.capital * 0.3) / price
                    orders.append({
                        'symbol': symbol,
                        'side': 'BUY',
                        'amount': amount,
                    })
                    self.positions[symbol] = {'amount': amount, 'entry_price': price}

                # 卖出信号：价格回到均值
                elif price > avg_price and symbol in self.positions:
                    orders.append({
                        'symbol': symbol,
                        'side': 'SELL',
                        'amount': self.positions[symbol]['amount'],
                    })
                    del self.positions[symbol]

        return orders
"""

# ❌ 语法错误
SYNTAX_ERROR_STRATEGY = """
class MyStrategy:
    def __init__(self):
        self.capital = 10000.0
        # 缺少冒号
        if True
            pass

    def on_tick(self, market_data):
        return []
"""

# ❌ 安全违规：导入禁止模块
SECURITY_VIOLATION_IMPORT = """
import os
import subprocess

class MyStrategy:
    def __init__(self):
        self.capital = 10000.0

    def on_tick(self, market_data):
        # 尝试执行系统命令
        os.system("ls -la")
        return []
"""

# ❌ 安全违规：无限循环
SECURITY_VIOLATION_LOOP = """
class MyStrategy:
    def __init__(self):
        self.capital = 10000.0

    def on_tick(self, market_data):
        # 无限循环
        while True:
            pass
        return []
"""

# ❌ 结构错误：缺少必需方法
STRUCTURE_ERROR_MISSING_METHOD = """
class MyStrategy:
    def __init__(self):
        self.capital = 10000.0

    # 缺少 on_tick 方法
"""

# ❌ 结构错误：类名错误
STRUCTURE_ERROR_WRONG_CLASS = """
class WrongClassName:
    def __init__(self):
        self.capital = 10000.0

    def on_tick(self, market_data):
        return []
"""

# ❌ 运行时错误：除零错误
RUNTIME_ERROR_STRATEGY = """
class MyStrategy:
    def __init__(self):
        self.capital = 10000.0

    def on_tick(self, market_data):
        # 除零错误
        result = 1 / 0
        return []
"""


# ========== 测试函数 ==========

async def test_syntax_validation():
    """测试语法验证"""
    print("\n" + "="*60)
    print("🧪 Test 1: Syntax Validation")
    print("="*60)

    # 测试合法代码
    print("\n✅ Testing valid syntax...")
    valid, errors = SecurityValidator.validate_syntax(VALID_STRATEGY)
    assert valid, f"Valid code should pass: {errors}"
    print("   PASS: Valid syntax accepted")

    # 测试语法错误
    print("\n❌ Testing syntax error...")
    valid, errors = SecurityValidator.validate_syntax(SYNTAX_ERROR_STRATEGY)
    assert not valid, "Syntax error should be detected"
    assert len(errors) > 0, "Should return error messages"
    print(f"   PASS: Syntax error detected - {errors[0]}")


async def test_security_validation():
    """测试安全验证"""
    print("\n" + "="*60)
    print("🔒 Test 2: Security Validation")
    print("="*60)

    # 测试合法代码
    print("\n✅ Testing safe code...")
    safe, violations = SecurityValidator.validate_security(VALID_STRATEGY)
    assert safe, f"Safe code should pass: {violations}"
    print("   PASS: Safe code accepted")

    # 测试禁止导入
    print("\n❌ Testing forbidden imports...")
    safe, violations = SecurityValidator.validate_security(SECURITY_VIOLATION_IMPORT)
    assert not safe, "Forbidden imports should be detected"
    assert any("os" in v or "subprocess" in v for v in violations), "Should detect os/subprocess"
    print(f"   PASS: Forbidden imports detected - {violations[0]}")

    # 测试无限循环
    print("\n❌ Testing infinite loop...")
    safe, violations = SecurityValidator.validate_security(SECURITY_VIOLATION_LOOP)
    assert not safe, "Infinite loop should be detected"
    assert any("infinite loop" in v.lower() for v in violations), "Should detect infinite loop"
    print(f"   PASS: Infinite loop detected - {violations[0]}")


async def test_structure_validation():
    """测试结构验证"""
    print("\n" + "="*60)
    print("🏗️ Test 3: Structure Validation")
    print("="*60)

    # 测试合法结构
    print("\n✅ Testing valid structure...")
    valid, errors = SecurityValidator.validate_class_structure(VALID_STRATEGY)
    assert valid, f"Valid structure should pass: {errors}"
    print("   PASS: Valid structure accepted")

    # 测试缺少方法
    print("\n❌ Testing missing method...")
    valid, errors = SecurityValidator.validate_class_structure(STRUCTURE_ERROR_MISSING_METHOD)
    assert not valid, "Missing method should be detected"
    assert any("on_tick" in e for e in errors), "Should detect missing on_tick"
    print(f"   PASS: Missing method detected - {errors[0]}")

    # 测试错误类名
    print("\n❌ Testing wrong class name...")
    valid, errors = SecurityValidator.validate_class_structure(STRUCTURE_ERROR_WRONG_CLASS)
    assert not valid, "Wrong class name should be detected"
    assert any("MyStrategy" in e for e in errors), "Should detect missing MyStrategy"
    print(f"   PASS: Wrong class name detected - {errors[0]}")


async def test_sandbox_execution():
    """测试沙盒执行"""
    print("\n" + "="*60)
    print("⚙️ Test 4: Sandbox Execution")
    print("="*60)

    executor = SandboxExecutor()

    # 测试合法执行
    print("\n✅ Testing valid execution...")
    market_data = {
        'tick': 10,
        'prices': {'VIRTUAL': 1.5, 'BRETT': 0.8},
        'volumes': {'VIRTUAL': 50000, 'BRETT': 30000},
        'liquidities': {'VIRTUAL': 1000000, 'BRETT': 800000},
    }

    success, orders, error = executor.execute_strategy(VALID_STRATEGY, market_data, {})
    assert success, f"Valid strategy should execute: {error}"
    print(f"   PASS: Strategy executed successfully")
    print(f"   Orders returned: {len(orders) if orders else 0}")

    # 测试运行时错误
    print("\n❌ Testing runtime error...")
    success, orders, error = executor.execute_strategy(RUNTIME_ERROR_STRATEGY, market_data, {})
    assert not success, "Runtime error should be caught"
    assert "division by zero" in error.lower() or "zerodivision" in error.lower(), "Should detect division by zero"
    print(f"   PASS: Runtime error caught - {error.split(':')[0]}")


async def test_backtest_engine():
    """测试回测引擎"""
    print("\n" + "="*60)
    print("📊 Test 5: Backtest Engine")
    print("="*60)

    engine = BacktestEngine(initial_balance=10000.0)

    # 生成模拟数据
    print("\n📈 Generating mock market data...")
    symbols = ['VIRTUAL', 'BRETT', 'DEGEN']
    market_history = engine.generate_mock_market_data(symbols, num_ticks=50, volatility=0.02)
    print(f"   Generated {len(market_history)} ticks for {len(symbols)} symbols")

    # 运行回测
    print("\n🔄 Running backtest...")
    success, results, logs = engine.run_backtest(VALID_STRATEGY, market_history, symbols)

    assert success, f"Backtest should succeed: {logs[-5:] if logs else 'No logs'}"
    print(f"   PASS: Backtest completed")
    print(f"   Final PnL: {results['final_pnl_percent']:+.2f}%")
    print(f"   Win Rate: {results['win_rate']:.1%}")
    print(f"   Max Drawdown: {results['max_drawdown']:.1%}")
    print(f"   Execution Time: {results['execution_time']:.3f}s")


async def test_full_sandbox():
    """测试完整沙盒系统"""
    print("\n" + "="*60)
    print("🧪 Test 6: Full Sandbox System")
    print("="*60)

    sandbox = StrategySandbox(backtest_rounds=5, ticks_per_round=50)

    # 测试合法策略
    print("\n✅ Testing valid strategy (full pipeline)...")
    result = await sandbox.test_strategy(VALID_STRATEGY, "test_agent")

    assert result.passed, f"Valid strategy should pass all tests: {result.error_message}"
    print(f"   PASS: All tests passed")
    print(f"   Backtest Rounds: {result.backtest_rounds}")
    print(f"   Predicted PnL: {result.predicted_pnl:+.2f}%")
    print(f"   Avg PnL/Round: {result.avg_pnl_per_round:+.2f}%")
    print(f"   Win Rate: {result.win_rate:.1%}")

    # 测试失败策略
    print("\n❌ Testing invalid strategy (syntax error)...")
    result = await sandbox.test_strategy(SYNTAX_ERROR_STRATEGY, "test_agent")

    assert not result.passed, "Invalid strategy should fail"
    assert result.error_type == "SYNTAX_ERROR", f"Should detect syntax error, got {result.error_type}"
    print(f"   PASS: Correctly rejected - {result.error_type}")

    print("\n❌ Testing invalid strategy (security violation)...")
    result = await sandbox.test_strategy(SECURITY_VIOLATION_IMPORT, "test_agent")

    assert not result.passed, "Security violation should fail"
    assert result.error_type == "SECURITY_VIOLATION", f"Should detect security violation, got {result.error_type}"
    print(f"   PASS: Correctly rejected - {result.error_type}")


async def test_validation_api():
    """测试验证API"""
    print("\n" + "="*60)
    print("🔌 Test 7: Validation API")
    print("="*60)

    # 测试合法策略
    print("\n✅ Testing validation API with valid strategy...")
    allowed, message, result = await validate_strategy_before_submission(
        VALID_STRATEGY, "test_agent", min_backtest_rounds=3
    )

    assert allowed, f"Valid strategy should be allowed: {message}"
    assert result.passed, "Test result should show passed"
    print(f"   PASS: Strategy allowed")
    print(f"   Message: {message[:100]}...")

    # 测试失败策略
    print("\n❌ Testing validation API with invalid strategy...")
    allowed, message, result = await validate_strategy_before_submission(
        SYNTAX_ERROR_STRATEGY, "test_agent", min_backtest_rounds=3
    )

    assert not allowed, "Invalid strategy should be rejected"
    assert not result.passed, "Test result should show failed"
    print(f"   PASS: Strategy rejected")
    print(f"   Message: {message[:100]}...")


async def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*80)
    print("🧪 STRATEGY SANDBOX TEST SUITE")
    print("="*80)

    tests = [
        ("Syntax Validation", test_syntax_validation),
        ("Security Validation", test_security_validation),
        ("Structure Validation", test_structure_validation),
        ("Sandbox Execution", test_sandbox_execution),
        ("Backtest Engine", test_backtest_engine),
        ("Full Sandbox System", test_full_sandbox),
        ("Validation API", test_validation_api),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            await test_func()
            passed += 1
        except AssertionError as e:
            print(f"\n❌ TEST FAILED: {name}")
            print(f"   Error: {str(e)}")
            failed += 1
        except Exception as e:
            print(f"\n💥 TEST ERROR: {name}")
            print(f"   Exception: {str(e)}")
            import traceback
            traceback.print_exc()
            failed += 1

    # 总结
    print("\n" + "="*80)
    print("📊 TEST SUMMARY")
    print("="*80)
    print(f"✅ Passed: {passed}/{len(tests)}")
    print(f"❌ Failed: {failed}/{len(tests)}")

    if failed == 0:
        print("\n🎉 All tests passed! Sandbox system is ready for production.")
    else:
        print(f"\n⚠️ {failed} test(s) failed. Please review the errors above.")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
