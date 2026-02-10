"""
🧪 Strategy Sandbox Testing System - Project Darwin

沙盒功能：
1. 隔离执行环境（不影响真实交易）
2. 用历史数据回测 10-20 轮
3. 检测代码错误（语法、运行时错误）
4. 检测恶意代码（无限循环、系统调用等）
5. 预测新策略的 PnL

测试通过才允许提交到服务器
"""

import ast
import sys
import io
import time
import traceback
import resource
import signal
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
import copy
import random


@dataclass
class SandboxTestResult:
    """沙盒测试结果"""
    passed: bool = False
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    syntax_errors: List[str] = field(default_factory=list)
    runtime_errors: List[str] = field(default_factory=list)
    security_violations: List[str] = field(default_factory=list)

    # 回测结果
    backtest_rounds: int = 0
    predicted_pnl: float = 0.0
    avg_pnl_per_round: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0

    # 性能指标
    execution_time: float = 0.0
    memory_usage: float = 0.0

    # 详细日志
    test_log: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "passed": self.passed,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "syntax_errors": self.syntax_errors,
            "runtime_errors": self.runtime_errors,
            "security_violations": self.security_violations,
            "backtest_rounds": self.backtest_rounds,
            "predicted_pnl": self.predicted_pnl,
            "avg_pnl_per_round": self.avg_pnl_per_round,
            "win_rate": self.win_rate,
            "max_drawdown": self.max_drawdown,
            "execution_time": self.execution_time,
            "memory_usage": self.memory_usage,
            "test_log": self.test_log,
        }


class SecurityValidator:
    """安全验证器 - 检测恶意代码"""

    # 禁止的模块和函数
    FORBIDDEN_IMPORTS = {
        'os', 'sys', 'subprocess', 'socket', 'urllib', 'requests',
        'eval', 'exec', 'compile', '__import__', 'open', 'file',
        'input', 'raw_input', 'execfile', 'reload', 'globals', 'locals',
        'vars', 'dir', 'help', 'quit', 'exit', 'copyright', 'credits',
        'license', 'pickle', 'shelve', 'marshal', 'ctypes', 'multiprocessing',
        'threading', 'asyncio', 'signal', 'resource', 'gc', 'weakref',
    }

    # 允许的安全模块
    ALLOWED_IMPORTS = {
        'math', 'random', 'collections', 'datetime', 'time', 'json',
        'statistics', 'decimal', 'fractions', 'itertools', 'functools',
    }

    @staticmethod
    def validate_syntax(code: str) -> Tuple[bool, List[str]]:
        """验证语法"""
        errors = []
        try:
            ast.parse(code)
            return True, []
        except SyntaxError as e:
            errors.append(f"Syntax error at line {e.lineno}: {e.msg}")
            return False, errors
        except Exception as e:
            errors.append(f"Parse error: {str(e)}")
            return False, errors

    @staticmethod
    def validate_security(code: str) -> Tuple[bool, List[str]]:
        """验证安全性 - 检测危险操作"""
        violations = []

        try:
            tree = ast.parse(code)
        except:
            return False, ["Failed to parse code for security check"]

        # 检查导入
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split('.')[0]
                    if module in SecurityValidator.FORBIDDEN_IMPORTS:
                        violations.append(f"Forbidden import: {alias.name}")
                    elif module not in SecurityValidator.ALLOWED_IMPORTS:
                        violations.append(f"Suspicious import: {alias.name}")

            elif isinstance(node, ast.ImportFrom):
                module = node.module.split('.')[0] if node.module else ''
                if module in SecurityValidator.FORBIDDEN_IMPORTS:
                    violations.append(f"Forbidden import from: {node.module}")
                elif module not in SecurityValidator.ALLOWED_IMPORTS:
                    violations.append(f"Suspicious import from: {node.module}")

            # 检查危险函数调用
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    if func_name in SecurityValidator.FORBIDDEN_IMPORTS:
                        violations.append(f"Forbidden function call: {func_name}()")

            # 检查无限循环风险
            elif isinstance(node, ast.While):
                # 检查是否有明显的无限循环 (while True without break)
                if isinstance(node.test, ast.Constant) and node.test.value is True:
                    has_break = any(isinstance(n, ast.Break) for n in ast.walk(node))
                    if not has_break:
                        violations.append("Potential infinite loop detected: while True without break")

        return len(violations) == 0, violations

    @staticmethod
    def validate_class_structure(code: str) -> Tuple[bool, List[str]]:
        """验证策略类结构"""
        errors = []

        try:
            tree = ast.parse(code)
        except:
            return False, ["Failed to parse code"]

        # 查找 MyStrategy 类
        strategy_class = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "MyStrategy":
                strategy_class = node
                break

        if not strategy_class:
            errors.append("Missing MyStrategy class definition")
            return False, errors

        # 检查必需的方法
        required_methods = {'__init__', 'on_tick'}
        found_methods = set()

        for item in strategy_class.body:
            if isinstance(item, ast.FunctionDef):
                found_methods.add(item.name)

        missing = required_methods - found_methods
        if missing:
            errors.append(f"Missing required methods: {', '.join(missing)}")

        return len(errors) == 0, errors


class TimeoutException(Exception):
    """超时异常"""
    pass


def timeout_handler(signum, frame):
    """超时处理器"""
    raise TimeoutException("Execution timeout")


class SandboxExecutor:
    """沙盒执行器 - 隔离执行策略代码"""

    # 资源限制
    MAX_EXECUTION_TIME = 5  # 每轮最大执行时间（秒）
    MAX_MEMORY_MB = 100  # 最大内存使用（MB）

    def __init__(self):
        self.restricted_globals = self._create_restricted_globals()

    def _create_restricted_globals(self) -> Dict[str, Any]:
        """创建受限的全局命名空间"""
        # 只允许安全的内置函数
        safe_builtins = {
            'abs', 'all', 'any', 'bool', 'dict', 'enumerate', 'filter',
            'float', 'int', 'len', 'list', 'map', 'max', 'min', 'range',
            'round', 'set', 'sorted', 'str', 'sum', 'tuple', 'zip',
            'True', 'False', 'None', 'isinstance', 'hasattr', 'getattr',
            'setattr', 'type', 'ValueError', 'TypeError', 'KeyError',
            'IndexError', 'AttributeError', 'Exception',
            '__build_class__', '__name__',  # 需要用于类定义
        }

        # 添加允许的模块
        import math
        import random
        from collections import deque

        # 创建安全的 __import__ 函数
        allowed_modules = {'math', 'random', 'collections', 'datetime', 'time'}

        def safe_import(name, *args, **kwargs):
            if name.split('.')[0] not in allowed_modules:
                raise ImportError(f"Import of '{name}' is not allowed")
            return __import__(name, *args, **kwargs)

        restricted = {
            '__builtins__': {
                **{k: __builtins__[k] for k in safe_builtins if k in __builtins__},
                '__import__': safe_import,
            },
            '__name__': '__main__',  # 需要用于模块执行
        }

        # 预加载允许的模块
        restricted['math'] = math
        restricted['random'] = random
        restricted['deque'] = deque

        return restricted

    def execute_strategy(
        self,
        code: str,
        market_data: Dict[str, Any],
        agent_state: Dict[str, Any],
    ) -> Tuple[bool, Optional[List[Dict]], Optional[str]]:
        """
        在沙盒中执行策略

        Returns:
            (success, orders, error_message)
        """
        try:
            # 设置资源限制（仅在 Unix 系统，且谨慎处理）
            if sys.platform != 'win32':
                try:
                    # 获取当前限制
                    soft, hard = resource.getrlimit(resource.RLIMIT_AS)

                    # 只在当前限制允许的情况下设置新限制
                    new_limit = self.MAX_MEMORY_MB * 1024 * 1024
                    if hard == resource.RLIM_INFINITY or new_limit < hard:
                        resource.setrlimit(
                            resource.RLIMIT_AS,
                            (new_limit, hard)
                        )
                except (ValueError, OSError) as e:
                    # 如果无法设置内存限制，继续执行（记录警告）
                    pass

                # 设置超时
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(self.MAX_EXECUTION_TIME)

            # 创建隔离的命名空间（不使用 deepcopy，直接复制引用）
            namespace = dict(self.restricted_globals)

            # 执行策略代码
            exec(code, namespace)

            # 实例化策略
            if 'MyStrategy' not in namespace:
                return False, None, "MyStrategy class not found"

            strategy_class = namespace['MyStrategy']
            strategy = strategy_class()

            # 恢复状态（如果有）
            if agent_state:
                for key, value in agent_state.items():
                    if hasattr(strategy, key):
                        setattr(strategy, key, value)

            # 调用 on_tick
            orders = strategy.on_tick(market_data)

            # 取消超时
            if sys.platform != 'win32':
                signal.alarm(0)

            return True, orders, None

        except TimeoutException:
            return False, None, "Execution timeout - possible infinite loop"
        except MemoryError:
            return False, None, "Memory limit exceeded"
        except Exception as e:
            return False, None, f"Runtime error: {str(e)}\n{traceback.format_exc()}"
        finally:
            # 重置资源限制
            if sys.platform != 'win32':
                signal.alarm(0)


class BacktestEngine:
    """回测引擎 - 使用历史数据测试策略"""

    def __init__(self, initial_balance: float = 10000.0):
        self.initial_balance = initial_balance
        self.executor = SandboxExecutor()

    def generate_mock_market_data(
        self,
        symbols: List[str],
        num_ticks: int = 100,
        volatility: float = 0.02,
    ) -> List[Dict[str, Any]]:
        """生成模拟市场数据"""
        market_history = []

        # 初始价格
        base_prices = {sym: random.uniform(0.01, 10.0) for sym in symbols}

        for tick in range(num_ticks):
            tick_data = {
                'tick': tick,
                'timestamp': datetime.now().timestamp() + tick * 60,
                'prices': {},
            }

            for sym in symbols:
                # 随机游走 + 趋势
                trend = random.choice([-1, 0, 1]) * 0.001
                change = random.gauss(trend, volatility)
                base_prices[sym] *= (1 + change)

                tick_data['prices'][sym] = {
                    'price': base_prices[sym],
                    'volume': random.uniform(10000, 100000),
                    'liquidity': random.uniform(500000, 2000000),
                }

            market_history.append(tick_data)

        return market_history

    def run_backtest(
        self,
        code: str,
        market_history: List[Dict[str, Any]],
        symbols: List[str],
    ) -> Tuple[bool, Dict[str, Any], List[str]]:
        """
        运行回测

        Returns:
            (success, results, logs)
        """
        logs = []
        balance = self.initial_balance
        positions = {sym: 0.0 for sym in symbols}
        avg_prices = {sym: 0.0 for sym in symbols}

        pnl_history = []
        agent_state = {}

        start_time = time.time()

        for tick_data in market_history:
            tick = tick_data['tick']
            prices = tick_data['prices']

            # 构建 market_data 格式（与真实环境一致）
            market_data = {
                'tick': tick,
                'prices': {sym: data['price'] for sym, data in prices.items()},
                'volumes': {sym: data['volume'] for sym, data in prices.items()},
                'liquidities': {sym: data['liquidity'] for sym, data in prices.items()},
            }

            # 执行策略
            success, orders, error = self.executor.execute_strategy(
                code, market_data, agent_state
            )

            if not success:
                logs.append(f"Tick {tick}: Execution failed - {error}")
                return False, {}, logs

            # 处理订单
            if orders:
                for order in orders:
                    symbol = order.get('symbol')
                    side = order.get('side', '').upper()
                    amount = order.get('amount', 0)

                    if symbol not in prices:
                        continue

                    price = prices[symbol]['price']

                    if side == 'BUY':
                        cost = amount * price
                        if cost <= balance:
                            # 更新平均成本
                            total_amount = positions[symbol] + amount
                            if total_amount > 0:
                                avg_prices[symbol] = (
                                    (positions[symbol] * avg_prices[symbol] + cost) / total_amount
                                )
                            positions[symbol] += amount
                            balance -= cost
                            logs.append(f"Tick {tick}: BUY {amount:.2f} {symbol} @ {price:.6f}")

                    elif side == 'SELL':
                        if amount <= positions[symbol]:
                            revenue = amount * price
                            positions[symbol] -= amount
                            balance += revenue
                            logs.append(f"Tick {tick}: SELL {amount:.2f} {symbol} @ {price:.6f}")

            # 计算当前总资产
            total_value = balance
            for sym, pos_amount in positions.items():
                if pos_amount > 0 and sym in prices:
                    total_value += pos_amount * prices[sym]['price']

            pnl = total_value - self.initial_balance
            pnl_history.append(pnl)

        execution_time = time.time() - start_time

        # 计算统计指标
        final_pnl = pnl_history[-1] if pnl_history else 0.0
        avg_pnl = sum(pnl_history) / len(pnl_history) if pnl_history else 0.0

        # 计算胜率（正收益的比例）
        positive_pnl = sum(1 for p in pnl_history if p > 0)
        win_rate = positive_pnl / len(pnl_history) if pnl_history else 0.0

        # 计算最大回撤
        peak = self.initial_balance
        max_drawdown = 0.0
        for pnl in pnl_history:
            value = self.initial_balance + pnl
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak if peak > 0 else 0.0
            max_drawdown = max(max_drawdown, drawdown)

        results = {
            'final_pnl': final_pnl,
            'final_pnl_percent': (final_pnl / self.initial_balance) * 100,
            'avg_pnl': avg_pnl,
            'win_rate': win_rate,
            'max_drawdown': max_drawdown,
            'execution_time': execution_time,
            'total_ticks': len(market_history),
        }

        return True, results, logs


class StrategySandbox:
    """策略沙盒 - 完整的测试系统"""

    def __init__(
        self,
        backtest_rounds: int = 15,
        ticks_per_round: int = 100,
        symbols: List[str] = None,
    ):
        self.backtest_rounds = backtest_rounds
        self.ticks_per_round = ticks_per_round
        self.symbols = symbols or ['VIRTUAL', 'BRETT', 'DEGEN']
        self.backtest_engine = BacktestEngine()

    async def test_strategy(self, code: str, agent_id: str = "test") -> SandboxTestResult:
        """
        完整测试策略

        测试流程：
        1. 语法检查
        2. 安全检查
        3. 结构验证
        4. 回测执行
        """
        result = SandboxTestResult()
        result.test_log.append(f"🧪 Testing strategy for {agent_id}")

        # === 第1步：语法检查 ===
        result.test_log.append("\n📝 Step 1: Syntax validation")
        syntax_ok, syntax_errors = SecurityValidator.validate_syntax(code)
        result.syntax_errors = syntax_errors

        if not syntax_ok:
            result.passed = False
            result.error_type = "SYNTAX_ERROR"
            result.error_message = "; ".join(syntax_errors)
            result.test_log.append(f"❌ Syntax check failed: {result.error_message}")
            return result

        result.test_log.append("✅ Syntax check passed")

        # === 第2步：安全检查 ===
        result.test_log.append("\n🔒 Step 2: Security validation")
        security_ok, violations = SecurityValidator.validate_security(code)
        result.security_violations = violations

        if not security_ok:
            result.passed = False
            result.error_type = "SECURITY_VIOLATION"
            result.error_message = "; ".join(violations)
            result.test_log.append(f"❌ Security check failed: {result.error_message}")
            return result

        result.test_log.append("✅ Security check passed")

        # === 第3步：结构验证 ===
        result.test_log.append("\n🏗️ Step 3: Class structure validation")
        structure_ok, structure_errors = SecurityValidator.validate_class_structure(code)

        if not structure_ok:
            result.passed = False
            result.error_type = "STRUCTURE_ERROR"
            result.error_message = "; ".join(structure_errors)
            result.test_log.append(f"❌ Structure check failed: {result.error_message}")
            return result

        result.test_log.append("✅ Structure check passed")

        # === 第4步：回测执行 ===
        result.test_log.append(f"\n📊 Step 4: Backtesting ({self.backtest_rounds} rounds)")

        all_pnls = []
        all_logs = []

        for round_num in range(self.backtest_rounds):
            result.test_log.append(f"\n  Round {round_num + 1}/{self.backtest_rounds}")

            # 生成市场数据
            market_history = self.backtest_engine.generate_mock_market_data(
                self.symbols,
                self.ticks_per_round,
                volatility=random.uniform(0.015, 0.025),
            )

            # 运行回测
            success, backtest_results, logs = self.backtest_engine.run_backtest(
                code, market_history, self.symbols
            )

            if not success:
                result.passed = False
                result.error_type = "RUNTIME_ERROR"
                result.error_message = "\n".join(logs[-5:])  # 最后5条日志
                result.runtime_errors = logs
                result.test_log.append(f"  ❌ Round {round_num + 1} failed")
                result.test_log.extend([f"    {log}" for log in logs[-3:]])
                return result

            pnl = backtest_results['final_pnl_percent']
            all_pnls.append(pnl)
            all_logs.extend(logs)

            result.test_log.append(
                f"  ✅ Round {round_num + 1}: PnL = {pnl:+.2f}%, "
                f"Win Rate = {backtest_results['win_rate']:.1%}, "
                f"Max DD = {backtest_results['max_drawdown']:.1%}"
            )

        # === 计算总体统计 ===
        result.backtest_rounds = self.backtest_rounds
        result.predicted_pnl = sum(all_pnls)
        result.avg_pnl_per_round = sum(all_pnls) / len(all_pnls)
        result.win_rate = sum(1 for p in all_pnls if p > 0) / len(all_pnls)
        result.max_drawdown = max(abs(min(all_pnls, default=0)), 0)

        result.test_log.append(f"\n📈 Backtest Summary:")
        result.test_log.append(f"  Total PnL: {result.predicted_pnl:+.2f}%")
        result.test_log.append(f"  Avg PnL/Round: {result.avg_pnl_per_round:+.2f}%")
        result.test_log.append(f"  Win Rate: {result.win_rate:.1%}")
        result.test_log.append(f"  Max Drawdown: {result.max_drawdown:.2f}%")

        # === 最终判定 ===
        result.passed = True
        result.test_log.append("\n✅ All tests passed! Strategy is ready for deployment.")

        return result


# === 便捷函数 ===

async def test_strategy_code(
    code: str,
    agent_id: str = "test",
    backtest_rounds: int = 15,
) -> SandboxTestResult:
    """
    测试策略代码（便捷函数）

    Args:
        code: 策略代码
        agent_id: Agent ID
        backtest_rounds: 回测轮数

    Returns:
        SandboxTestResult
    """
    sandbox = StrategySandbox(backtest_rounds=backtest_rounds)
    return await sandbox.test_strategy(code, agent_id)


async def validate_strategy_before_submission(
    code: str,
    agent_id: str,
    min_backtest_rounds: int = 10,
) -> Tuple[bool, str, Optional[SandboxTestResult]]:
    """
    提交前验证策略（集成到进化流程）

    Returns:
        (allowed, message, test_result)
    """
    result = await test_strategy_code(code, agent_id, min_backtest_rounds)

    if not result.passed:
        message = f"❌ Strategy validation failed: {result.error_type}\n{result.error_message}"
        return False, message, result

    # 可以添加额外的准入标准
    if result.avg_pnl_per_round < -50:  # 平均每轮亏损超过50%
        message = f"❌ Strategy rejected: Poor backtest performance (avg PnL: {result.avg_pnl_per_round:.2f}%)"
        return False, message, result

    message = (
        f"✅ Strategy validated successfully!\n"
        f"Predicted PnL: {result.predicted_pnl:+.2f}% over {result.backtest_rounds} rounds\n"
        f"Win Rate: {result.win_rate:.1%}"
    )
    return True, message, result
