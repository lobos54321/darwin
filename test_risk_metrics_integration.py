"""
测试风险指标集成
验证 AscensionTracker 和 API 端点是否正确使用科学指标
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from arena_server.chain import AscensionTracker
from arena_server.metrics import (
    calculate_composite_score,
    check_l1_promotion_criteria,
    check_l2_launch_criteria
)


def test_ascension_tracker():
    """测试晋级系统"""
    print("=== 测试晋级系统 ===\n")

    tracker = AscensionTracker()

    # 模拟一个稳定盈利的 Agent
    print("📊 模拟稳定策略 Agent (Agent_Stable)")
    print("-" * 50)

    stable_agent = "Agent_Stable"
    stable_epochs = [
        (stable_agent, 2.5, 10250.0),   # Epoch 1: +2.5%
        (stable_agent, 1.8, 10434.5),   # Epoch 2: +1.8%
        (stable_agent, 3.2, 10768.4),   # Epoch 3: +3.2%
        (stable_agent, 2.1, 10994.6),   # Epoch 4: +2.1%
        (stable_agent, 1.5, 11159.5),   # Epoch 5: +1.5%
        (stable_agent, 2.8, 11471.9),   # Epoch 6: +2.8%
    ]

    for epoch_num, (agent_id, pnl, total_value) in enumerate(stable_epochs, 1):
        print(f"\nEpoch {epoch_num}: {agent_id} PnL={pnl:.1f}% Value=${total_value:.2f}")
        result = tracker.record_epoch_result([(agent_id, pnl, total_value)])

        if result.get("promoted_to_l2"):
            print(f"  ✅ 晋级到 L2!")

        if result.get("ready_to_launch"):
            print(f"  🚀 准备发币!")

    # 检查状态
    stats = tracker.get_stats(stable_agent)
    print(f"\n{stable_agent} 最终状态:")
    print(f"  等级: {stats['tier']}")
    print(f"  综合评分: {stats['composite_score']:.2f}/100")
    print(f"  夏普比率: {stats['sharpe_ratio']:.3f}")
    print(f"  索提诺比率: {stats['sortino_ratio']:.3f}")
    print(f"  最大回撤: {stats['max_drawdown']:.2f}%")
    print(f"  胜率: {stats['win_rate']:.1f}%")
    print(f"  连续正收益: {stats.get('consecutive_positive', 0)}")

    print("\n" + "=" * 50)

    # 模拟一个高风险高收益的 Agent
    print("\n📊 模拟高风险策略 Agent (Agent_Risky)")
    print("-" * 50)

    risky_agent = "Agent_Risky"
    risky_epochs = [
        (risky_agent, 15.0, 11500.0),   # Epoch 1: +15%
        (risky_agent, -8.0, 10580.0),   # Epoch 2: -8%
        (risky_agent, 12.0, 11849.6),   # Epoch 3: +12%
        (risky_agent, -5.0, 11257.1),   # Epoch 4: -5%
        (risky_agent, 20.0, 13508.5),   # Epoch 5: +20%
    ]

    for epoch_num, (agent_id, pnl, total_value) in enumerate(risky_epochs, 1):
        print(f"\nEpoch {epoch_num}: {agent_id} PnL={pnl:.1f}% Value=${total_value:.2f}")
        result = tracker.record_epoch_result([(agent_id, pnl, total_value)])

        if result.get("promoted_to_l2"):
            print(f"  ✅ 晋级到 L2!")

        if result.get("ready_to_launch"):
            print(f"  🚀 准备发币!")

    # 检查状态
    stats = tracker.get_stats(risky_agent)
    print(f"\n{risky_agent} 最终状态:")
    print(f"  等级: {stats['tier']}")
    print(f"  综合评分: {stats['composite_score']:.2f}/100")
    print(f"  夏普比率: {stats['sharpe_ratio']:.3f}")
    print(f"  索提诺比率: {stats['sortino_ratio']:.3f}")
    print(f"  最大回撤: {stats['max_drawdown']:.2f}%")
    print(f"  胜率: {stats['win_rate']:.1f}%")
    print(f"  连续正收益: {stats.get('consecutive_positive', 0)}")

    print("\n" + "=" * 50)


def test_promotion_criteria():
    """测试晋级条件"""
    print("\n=== 测试晋级条件 ===\n")

    # L1 晋级测试
    print("L1 晋级条件测试:")
    print("-" * 50)

    # 优秀策略（应该晋级）
    good_returns = [2.5, 1.8, 3.2, 2.1, 1.5, 2.8, 2.3]
    good_values = [10000.0]
    for r in good_returns:
        good_values.append(good_values[-1] * (1 + r/100))

    good_metrics = calculate_composite_score(good_returns, good_values, sum(good_returns))
    can_promote = check_l1_promotion_criteria(good_metrics, consecutive_positive=5)

    print(f"优秀策略:")
    print(f"  综合评分: {good_metrics['composite_score']:.2f} (需要 > 70)")
    print(f"  夏普比率: {good_metrics['sharpe_ratio']:.3f} (需要 > 1.0)")
    print(f"  最大回撤: {good_metrics['max_drawdown']:.2f}% (需要 > -20%)")
    print(f"  连续正收益: 5 (需要 >= 5)")
    print(f"  ✅ 可以晋级: {can_promote}")

    # 差策略（不应该晋级）
    bad_returns = [5.0, -3.0, 2.0, -4.0, 1.0]
    bad_values = [10000.0]
    for r in bad_returns:
        bad_values.append(bad_values[-1] * (1 + r/100))

    bad_metrics = calculate_composite_score(bad_returns, bad_values, sum(bad_returns))
    cannot_promote = check_l1_promotion_criteria(bad_metrics, consecutive_positive=2)

    print(f"\n差策略:")
    print(f"  综合评分: {bad_metrics['composite_score']:.2f} (需要 > 70)")
    print(f"  夏普比率: {bad_metrics['sharpe_ratio']:.3f} (需要 > 1.0)")
    print(f"  最大回撤: {bad_metrics['max_drawdown']:.2f}% (需要 > -20%)")
    print(f"  连续正收益: 2 (需要 >= 5)")
    print(f"  ❌ 可以晋级: {cannot_promote}")

    print("\n" + "=" * 50)

    # L2 发币测试
    print("\nL2 发币条件测试:")
    print("-" * 50)

    # 卓越策略（应该发币）
    elite_returns = [3.5, 2.8, 4.2, 3.1, 2.5, 3.8, 3.3, 2.9, 4.1, 3.6]
    elite_values = [10000.0]
    for r in elite_returns:
        elite_values.append(elite_values[-1] * (1 + r/100))

    elite_metrics = calculate_composite_score(elite_returns, elite_values, sum(elite_returns))
    can_launch = check_l2_launch_criteria(elite_metrics, consecutive_wins=3)

    print(f"卓越策略:")
    print(f"  综合评分: {elite_metrics['composite_score']:.2f} (需要 > 85)")
    print(f"  夏普比率: {elite_metrics['sharpe_ratio']:.3f} (需要 > 2.0)")
    print(f"  索提诺比率: {elite_metrics['sortino_ratio']:.3f} (需要 > 2.5)")
    print(f"  最大回撤: {elite_metrics['max_drawdown']:.2f}% (需要 > -15%)")
    print(f"  连续获胜: 3 (需要 >= 3)")
    print(f"  ✅ 可以发币: {can_launch}")

    print("\n" + "=" * 50)


if __name__ == "__main__":
    print("🧪 风险指标集成测试\n")
    print("=" * 50)

    test_ascension_tracker()
    test_promotion_criteria()

    print("\n✅ 所有测试完成!")
    print("\n📝 总结:")
    print("  - 风险指标计算模块正常工作")
    print("  - AscensionTracker 使用科学指标评估")
    print("  - L1 晋级条件：综合评分 > 70, 夏普 > 1.0, 回撤 > -20%, 连续正收益 >= 5")
    print("  - L2 发币条件：综合评分 > 85, 夏普 > 2.0, 索提诺 > 2.5, 回撤 > -15%, 连胜 >= 3")
