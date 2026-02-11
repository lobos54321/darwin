"""
量化交易指标计算模块
计算夏普比率、索提诺比率、卡尔玛比率等风险调整后的收益指标
"""

import statistics
from typing import List, Dict, Optional


def calculate_sharpe_ratio(returns: List[float], risk_free_rate: float = 0.0) -> float:
    """
    计算夏普比率 (Sharpe Ratio)

    夏普比率 = (平均收益 - 无风险利率) / 收益标准差

    Args:
        returns: 收益率列表（百分比）
        risk_free_rate: 无风险利率（默认0）

    Returns:
        夏普比率（越高越好，>1为良好，>2为优秀）
    """
    if len(returns) < 2:
        return 0.0

    try:
        excess_returns = [r - risk_free_rate for r in returns]
        mean_return = statistics.mean(excess_returns)
        std_return = statistics.stdev(excess_returns)

        if std_return == 0:
            return 0.0

        return mean_return / std_return
    except Exception:
        return 0.0


def calculate_sortino_ratio(returns: List[float], risk_free_rate: float = 0.0) -> float:
    """
    计算索提诺比率 (Sortino Ratio)

    索提诺比率 = (平均收益 - 无风险利率) / 下行标准差
    只考虑负收益的波动，更符合投资者心理

    Args:
        returns: 收益率列表（百分比）
        risk_free_rate: 无风险利率（默认0）

    Returns:
        索提诺比率（越高越好，>2为良好，>3为优秀）
    """
    if len(returns) < 2:
        return 0.0

    try:
        excess_returns = [r - risk_free_rate for r in returns]
        mean_return = statistics.mean(excess_returns)

        # 只计算负收益的标准差（下行风险）
        downside_returns = [r for r in excess_returns if r < 0]

        if not downside_returns:
            # 没有负收益，说明策略非常稳定
            return 10.0  # 返回一个很高的值

        downside_std = statistics.stdev(downside_returns)

        if downside_std == 0:
            return 0.0

        return mean_return / downside_std
    except Exception:
        return 0.0


def calculate_max_drawdown(cumulative_values: List[float]) -> float:
    """
    计算最大回撤 (Maximum Drawdown)

    最大回撤 = (峰值 - 谷值) / 峰值
    衡量从最高点到最低点的最大跌幅

    Args:
        cumulative_values: 累计资产价值列表

    Returns:
        最大回撤百分比（负数，越接近0越好）
    """
    if not cumulative_values or len(cumulative_values) < 2:
        return 0.0

    try:
        peak = cumulative_values[0]
        max_dd = 0.0

        for value in cumulative_values:
            if value > peak:
                peak = value

            if peak > 0:
                dd = (peak - value) / peak
                max_dd = max(max_dd, dd)

        return -max_dd * 100  # 返回负数百分比
    except Exception:
        return 0.0


def calculate_calmar_ratio(cumulative_return: float, max_drawdown: float) -> float:
    """
    计算卡尔玛比率 (Calmar Ratio)

    卡尔玛比率 = 累计收益率 / |最大回撤|
    衡量收益与最坏情况的比率

    Args:
        cumulative_return: 累计收益率（百分比）
        max_drawdown: 最大回撤（负数百分比）

    Returns:
        卡尔玛比率（越高越好，>3为良好，>5为优秀）
    """
    if max_drawdown == 0:
        return 0.0

    try:
        return cumulative_return / abs(max_drawdown)
    except Exception:
        return 0.0


def calculate_win_rate(returns: List[float]) -> float:
    """
    计算胜率

    Args:
        returns: 收益率列表

    Returns:
        胜率百分比（0-100）
    """
    if not returns:
        return 0.0

    positive_count = sum(1 for r in returns if r > 0)
    return (positive_count / len(returns)) * 100


def calculate_volatility(returns: List[float]) -> float:
    """
    计算波动率（标准差）

    Args:
        returns: 收益率列表

    Returns:
        波动率百分比
    """
    if len(returns) < 2:
        return 0.0

    try:
        return statistics.stdev(returns)
    except Exception:
        return 0.0


def calculate_composite_score(
    returns: List[float],
    cumulative_values: List[float],
    cumulative_return: float
) -> Dict[str, float]:
    """
    计算综合评分和所有指标

    综合评分 = 30% 收益率 + 30% 夏普比率 + 20% 索提诺比率 + 10% 胜率 + 10% 卡尔玛比率

    Args:
        returns: 每个 Epoch 的收益率列表
        cumulative_values: 累计资产价值列表
        cumulative_return: 累计收益率

    Returns:
        包含所有指标的字典
    """
    if not returns:
        return {
            "composite_score": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown": 0.0,
            "calmar_ratio": 0.0,
            "win_rate": 0.0,
            "volatility": 0.0
        }

    # 计算各项指标
    sharpe = calculate_sharpe_ratio(returns)
    sortino = calculate_sortino_ratio(returns)
    max_dd = calculate_max_drawdown(cumulative_values)
    calmar = calculate_calmar_ratio(cumulative_return, max_dd)
    win_rate = calculate_win_rate(returns)
    volatility = calculate_volatility(returns)

    # 归一化到 0-100 分
    # 收益率：100% = 100分（更合理的基准）
    normalized_return = min(max(cumulative_return, 0), 100)

    # 夏普比率：3.0 = 100分（更现实的目标）
    normalized_sharpe = min(max(sharpe * 33.33, 0), 100)

    # 索提诺比率：4.0 = 100分（更现实的目标）
    normalized_sortino = min(max(sortino * 25, 0), 100)

    # 卡尔玛比率：5.0 = 100分
    normalized_calmar = min(max(calmar * 20, 0), 100)

    # 综合评分（加权平均）
    composite_score = (
        0.30 * normalized_return +      # 30% 权重：收益率
        0.30 * normalized_sharpe +       # 30% 权重：夏普比率
        0.20 * normalized_sortino +      # 20% 权重：索提诺比率
        0.10 * win_rate +                # 10% 权重：胜率
        0.10 * normalized_calmar         # 10% 权重：卡尔玛比率
    )

    return {
        "composite_score": round(composite_score, 2),
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "max_drawdown": round(max_dd, 2),
        "calmar_ratio": round(calmar, 3),
        "win_rate": round(win_rate, 1),
        "volatility": round(volatility, 2)
    }


def check_l1_promotion_criteria(metrics: Dict[str, float], consecutive_positive: int) -> bool:
    """
    检查是否满足 L1 晋级条件

    条件：
    1. 综合评分 > 70 分
    2. 夏普比率 > 1.0
    3. 最大回撤 > -20%（即回撤小于20%）
    4. 连续 5 个 Epoch 保持正收益

    Args:
        metrics: 指标字典
        consecutive_positive: 连续正收益次数

    Returns:
        是否满足晋级条件
    """
    return (
        metrics.get("composite_score", 0) > 70 and
        metrics.get("sharpe_ratio", 0) > 1.0 and
        metrics.get("max_drawdown", -100) > -20 and
        consecutive_positive >= 5
    )


def check_l2_launch_criteria(metrics: Dict[str, float], consecutive_wins: int) -> bool:
    """
    检查是否满足 L2 发币条件

    条件：
    1. 综合评分 > 85 分
    2. 夏普比率 > 2.0
    3. 索提诺比率 > 2.5
    4. 最大回撤 > -15%（即回撤小于15%）
    5. 连续 3 次排名第一

    Args:
        metrics: 指标字典
        consecutive_wins: 连续获胜次数

    Returns:
        是否满足发币条件
    """
    return (
        metrics.get("composite_score", 0) > 85 and
        metrics.get("sharpe_ratio", 0) > 2.0 and
        metrics.get("sortino_ratio", 0) > 2.5 and
        metrics.get("max_drawdown", -100) > -15 and
        consecutive_wins >= 3
    )


if __name__ == "__main__":
    # 测试代码
    print("=== 量化指标计算测试 ===\n")

    # 模拟一个稳定盈利的策略
    stable_returns = [2.5, 1.8, 3.2, 2.1, 1.5, 2.8, 2.3, 1.9, 2.6, 2.0]
    stable_values = [1000]
    for r in stable_returns:
        stable_values.append(stable_values[-1] * (1 + r/100))

    stable_cumulative = sum(stable_returns)
    stable_metrics = calculate_composite_score(stable_returns, stable_values, stable_cumulative)

    print("稳定策略:")
    print(f"  收益率: {stable_cumulative:.2f}%")
    print(f"  夏普比率: {stable_metrics['sharpe_ratio']:.3f}")
    print(f"  索提诺比率: {stable_metrics['sortino_ratio']:.3f}")
    print(f"  最大回撤: {stable_metrics['max_drawdown']:.2f}%")
    print(f"  卡尔玛比率: {stable_metrics['calmar_ratio']:.3f}")
    print(f"  胜率: {stable_metrics['win_rate']:.1f}%")
    print(f"  综合评分: {stable_metrics['composite_score']:.2f}/100")
    print()

    # 模拟一个高风险高收益的策略
    risky_returns = [15.0, -8.0, 12.0, -5.0, 20.0, -10.0, 18.0, -6.0, 14.0, -4.0]
    risky_values = [1000]
    for r in risky_returns:
        risky_values.append(risky_values[-1] * (1 + r/100))

    risky_cumulative = sum(risky_returns)
    risky_metrics = calculate_composite_score(risky_returns, risky_values, risky_cumulative)

    print("高风险策略:")
    print(f"  收益率: {risky_cumulative:.2f}%")
    print(f"  夏普比率: {risky_metrics['sharpe_ratio']:.3f}")
    print(f"  索提诺比率: {risky_metrics['sortino_ratio']:.3f}")
    print(f"  最大回撤: {risky_metrics['max_drawdown']:.2f}%")
    print(f"  卡尔玛比率: {risky_metrics['calmar_ratio']:.3f}")
    print(f"  胜率: {risky_metrics['win_rate']:.1f}%")
    print(f"  综合评分: {risky_metrics['composite_score']:.2f}/100")
    print()

    print("✅ 指标计算模块测试完成")
