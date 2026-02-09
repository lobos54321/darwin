"""
Baseline to Skill Sync
将Darwin Arena的最新baseline策略同步到darwin-trader SKILL.md

功能：
1. 从baseline_manager获取最新策略
2. 提取策略的核心思路（用LLM总结）
3. 更新SKILL.md的"Recommended Strategy"部分
4. 让新进入的OpenClaw agents获得最新策略指导
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class BaselineToSkillSync:
    """将baseline策略同步到SKILL.md"""

    def __init__(self, baseline_manager, skill_md_path: str = None):
        """
        初始化同步器

        Args:
            baseline_manager: BaselineManager实例
            skill_md_path: SKILL.md文件路径
        """
        self.baseline_manager = baseline_manager

        if skill_md_path is None:
            skill_md_path = os.path.join(
                os.path.dirname(__file__),
                "..",
                "skill-package",
                "darwin-trader",
                "SKILL.md"
            )

        self.skill_md_path = Path(skill_md_path)
        self.last_synced_version = -1

    def should_sync(self) -> bool:
        """检查是否需要同步"""
        current_version = self.baseline_manager.get_current_version()
        return current_version > self.last_synced_version

    def sync_to_skill(self) -> bool:
        """
        同步baseline到SKILL.md

        Returns:
            是否成功同步
        """
        try:
            # 获取当前baseline
            baseline = self.baseline_manager.current_baseline
            if not baseline:
                logger.warning("No baseline available to sync")
                return False

            # 提取策略摘要
            strategy_summary = self._extract_strategy_summary(baseline)

            # 更新SKILL.md
            success = self._update_skill_md(strategy_summary, baseline)

            if success:
                self.last_synced_version = baseline["version"]
                logger.info(f"✅ Synced baseline v{baseline['version']} to SKILL.md")
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to sync baseline to skill: {e}")
            return False

    def _extract_strategy_summary(self, baseline: Dict) -> Dict:
        """
        从baseline中提取策略摘要

        Args:
            baseline: baseline数据

        Returns:
            策略摘要
        """
        hive_data = baseline.get("hive_data", {})
        performance = baseline.get("performance", {})

        # 提取关键信息
        boost_tokens = hive_data.get("boost", [])
        penalize_tokens = hive_data.get("penalize", [])
        alpha_factors = hive_data.get("alpha_factors", {})

        # 生成��略描述
        strategy_tips = []

        if boost_tokens:
            strategy_tips.append(f"**Favor these tokens**: {', '.join(boost_tokens[:3])}")

        if penalize_tokens:
            strategy_tips.append(f"**Avoid these tokens**: {', '.join(penalize_tokens[:3])}")

        if alpha_factors:
            top_factors = sorted(
                alpha_factors.items(),
                key=lambda x: abs(x[1]),
                reverse=True
            )[:3]
            if top_factors:
                factor_desc = ", ".join([f"{k} ({v:+.2f})" for k, v in top_factors])
                strategy_tips.append(f"**Key factors**: {factor_desc}")

        return {
            "version": baseline["version"],
            "epoch": baseline["epoch"],
            "timestamp": baseline["timestamp"],
            "performance": performance,
            "tips": strategy_tips,
            "boost_tokens": boost_tokens,
            "penalize_tokens": penalize_tokens
        }

    def _update_skill_md(self, strategy_summary: Dict, baseline: Dict) -> bool:
        """
        更新SKILL.md文件

        在文件末尾添加或更新"Current Winning Strategy"部分

        Args:
            strategy_summary: 策略摘要
            baseline: 完整baseline数据

        Returns:
            是否成功更新
        """
        try:
            # 读取现有内容
            if not self.skill_md_path.exists():
                logger.error(f"SKILL.md not found at {self.skill_md_path}")
                return False

            with open(self.skill_md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 生成新的策略部分
            strategy_section = self._generate_strategy_section(strategy_summary)

            # 查找并替换现有的策略部分
            marker_start = "## 🏆 Current Winning Strategy"
            marker_end = "---\n\n**Ready to compete?"

            if marker_start in content:
                # 替换现有部分
                start_idx = content.find(marker_start)
                end_idx = content.find(marker_end, start_idx)

                if end_idx != -1:
                    # 保留marker_end之后的内容
                    new_content = (
                        content[:start_idx] +
                        strategy_section + "\n\n" +
                        content[end_idx:]
                    )
                else:
                    # 如果找不到结束标记，就追加
                    new_content = content + "\n\n" + strategy_section
            else:
                # 在最后的"Ready to compete?"之前插入
                if marker_end in content:
                    end_idx = content.find(marker_end)
                    new_content = (
                        content[:end_idx] +
                        strategy_section + "\n\n" +
                        content[end_idx:]
                    )
                else:
                    # 追加到文件末尾
                    new_content = content + "\n\n" + strategy_section

            # 写回文件
            with open(self.skill_md_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            logger.info(f"📝 Updated SKILL.md with baseline v{strategy_summary['version']}")
            return True

        except Exception as e:
            logger.error(f"Failed to update SKILL.md: {e}")
            return False

    def _generate_strategy_section(self, summary: Dict) -> str:
        """
        生成策略部分的markdown内容

        Args:
            summary: 策略摘要

        Returns:
            markdown内容
        """
        perf = summary["performance"]
        version = summary["version"]
        epoch = summary["epoch"]

        section = f"""## 🏆 Current Winning Strategy

**Updated**: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}
**Baseline Version**: v{version} (Epoch {epoch})
**Performance**: PnL {perf.get('avg_pnl', 0):.2f}% | Win Rate {perf.get('win_rate', 0):.1f}% | Sharpe {perf.get('sharpe_ratio', 0):.2f}

### Strategy Insights from Champions

The following insights are extracted from the collective intelligence of top-performing agents:

"""

        # 添加策略提示
        if summary["tips"]:
            for tip in summary["tips"]:
                section += f"- {tip}\n"
        else:
            section += "- No specific recommendations yet. Explore and discover!\n"

        section += f"""
### How to Use This Strategy

1. **Connect to Arena**
   ```python
   darwin_trader(command="connect", agent_id="YourTrader")
   ```

2. **Research the Recommended Tokens**
   - Use web tools to fetch prices from DexScreener
   - Analyze market conditions with your LLM
   - Consider the champion insights above

3. **Make Your Decision**
   - Your LLM analyzes all data
   - Decides whether to follow or deviate from baseline
   - Executes trades based on your analysis

4. **Execute Trades**
   ```python
   darwin_trader(command="trade", action="buy", symbol="TOKEN", amount=100)
   ```

### Remember

- **Baseline is a starting point**, not a rule
- **Your LLM makes the final decision**
- **Explore and mutate** - innovation wins!
- **Monitor performance** and adapt

"""

        return section


def create_sync_task(baseline_manager, interval_seconds: int = 600):
    """
    创建定期同步任务

    Args:
        baseline_manager: BaselineManager实例
        interval_seconds: 同步间隔（秒）

    Returns:
        asyncio Task
    """
    import asyncio

    syncer = BaselineToSkillSync(baseline_manager)

    async def sync_loop():
        while True:
            try:
                if syncer.should_sync():
                    syncer.sync_to_skill()
                await asyncio.sleep(interval_seconds)
            except Exception as e:
                logger.error(f"Sync task error: {e}")
                await asyncio.sleep(interval_seconds)

    return asyncio.create_task(sync_loop())


# 测试代码
if __name__ == "__main__":
    from baseline_manager import BaselineManager

    # 创建测试实例
    manager = BaselineManager()
    syncer = BaselineToSkillSync(manager)

    # 测试同步
    if syncer.should_sync():
        success = syncer.sync_to_skill()
        print(f"Sync result: {'✅ Success' if success else '❌ Failed'}")
    else:
        print("No sync needed")
