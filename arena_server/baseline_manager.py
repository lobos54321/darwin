"""
Baseline Manager (基线策略管理器)
集体进化的核心：管理和更新全局最优策略

核心功能：
1. 存储当前最优 baseline 策略
2. 融合 Hive Mind 数据 + 赢家策略
3. 定期更新 baseline
4. 为新 Agent 提供最新 baseline

进化流程：
所有人从最新 baseline 出发 → 各自变异探索 → Hive Mind 学习 →
融合成新 baseline → 循环
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)


class BaselineManager:
    def __init__(self, data_dir: str = None):
        """
        初始化 Baseline Manager

        Args:
            data_dir: 数据存储目录
        """
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(__file__), "..", "data", "baselines")

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 当前 baseline
        self.current_baseline: Optional[Dict] = None

        # Baseline 历史
        self.baseline_history: List[Dict] = []

        # 加载已有数据
        self._load_from_disk()

        # 如果没有 baseline，创建初始版本
        if self.current_baseline is None:
            self._create_initial_baseline()

    def _load_from_disk(self):
        """从磁盘加载 baseline 数据"""
        current_file = self.data_dir / "current_baseline.json"
        history_file = self.data_dir / "baseline_history.json"

        try:
            if current_file.exists():
                with open(current_file, 'r') as f:
                    self.current_baseline = json.load(f)
                logger.info(f"📥 Loaded current baseline v{self.current_baseline.get('version', 0)}")

            if history_file.exists():
                with open(history_file, 'r') as f:
                    self.baseline_history = json.load(f)
                logger.info(f"📥 Loaded {len(self.baseline_history)} historical baselines")

        except Exception as e:
            logger.error(f"Failed to load baseline data: {e}")

    def _save_to_disk(self):
        """保存 baseline 数据到磁盘"""
        current_file = self.data_dir / "current_baseline.json"
        history_file = self.data_dir / "baseline_history.json"

        try:
            with open(current_file, 'w') as f:
                json.dump(self.current_baseline, f, indent=2)

            with open(history_file, 'w') as f:
                json.dump(self.baseline_history, f, indent=2)

            logger.info(f"💾 Saved baseline v{self.current_baseline.get('version', 0)}")

        except Exception as e:
            logger.error(f"Failed to save baseline data: {e}")

    def _create_initial_baseline(self):
        """创建初始 baseline（从 Agent_001 的策略）"""
        agent_001_strategy = os.path.join(
            os.path.dirname(__file__),
            "..",
            "data",
            "agents",
            "OpenClaw_Agent_001",
            "strategy.py"
        )

        try:
            with open(agent_001_strategy, 'r') as f:
                strategy_code = f.read()

            self.current_baseline = {
                "version": 0,
                "epoch": 0,
                "timestamp": datetime.now().isoformat(),
                "strategy_code": strategy_code,
                "hive_data": {
                    "boost": [],
                    "penalize": [],
                    "alpha_factors": {}
                },
                "performance": {
                    "avg_pnl": 0.0,
                    "win_rate": 0.0,
                    "sharpe_ratio": 0.0
                },
                "source": "initial_agent_001"
            }

            self._save_to_disk()
            logger.info("✅ Created initial baseline v0 from Agent_001")

        except Exception as e:
            logger.error(f"Failed to create initial baseline: {e}")
            # 创建一个最小可用的 baseline
            self.current_baseline = {
                "version": 0,
                "epoch": 0,
                "timestamp": datetime.now().isoformat(),
                "strategy_code": self._get_minimal_strategy(),
                "hive_data": {"boost": [], "penalize": [], "alpha_factors": {}},
                "performance": {"avg_pnl": 0.0, "win_rate": 0.0, "sharpe_ratio": 0.0},
                "source": "minimal_fallback"
            }
            self._save_to_disk()

    def _get_minimal_strategy(self) -> str:
        """返回一个最小可用的策略代码"""
        return '''"""
Minimal Strategy - Baseline v0
"""

class Strategy:
    def __init__(self):
        self.name = "Minimal Baseline"

    def on_price_update(self, prices: dict):
        """最小策略：不交易"""
        return None
'''

    def get_baseline_for_agent(self, agent_id: str) -> Dict:
        """
        为新 Agent 提供最新 baseline

        所有 Agent 都获得相同的最新 baseline
        但每个 Agent 会基于此做不同的变异

        Returns:
            {
                "version": int,
                "strategy_code": str,
                "hive_data": dict,
                "timestamp": str,
                "message": str
            }
        """
        if self.current_baseline is None:
            self._create_initial_baseline()

        return {
            "version": self.current_baseline["version"],
            "strategy_code": self.current_baseline["strategy_code"],
            "hive_data": self.current_baseline["hive_data"],
            "timestamp": self.current_baseline["timestamp"],
            "performance": self.current_baseline["performance"],
            "message": f"Welcome! You have baseline v{self.current_baseline['version']}. Mutate and explore!"
        }

    def update_baseline(
        self,
        epoch: int,
        hive_data: Dict,
        winner_strategy: Optional[str] = None,
        performance: Optional[Dict] = None
    ) -> Dict:
        """
        更新 baseline 策略

        融合逻辑：
        1. 保留当前 baseline 的核心结构
        2. 融入 Hive Mind 的 boost/penalize 信号
        3. 如果有赢家策略，提取其成功元素
        4. 生成新的 baseline

        Args:
            epoch: 当前 epoch
            hive_data: Hive Mind 分析数据
            winner_strategy: 赢家的策略代码（可选）
            performance: 当前 baseline 的表现数据

        Returns:
            新的 baseline
        """
        # 保存当前 baseline 到历史
        if self.current_baseline:
            self.baseline_history.append({
                "version": self.current_baseline["version"],
                "epoch": self.current_baseline["epoch"],
                "timestamp": self.current_baseline["timestamp"],
                "performance": self.current_baseline.get("performance", {}),
                "archived_at": datetime.now().isoformat()
            })

        # 创建新版本
        new_version = self.current_baseline["version"] + 1

        # 策略代码更新逻辑
        new_strategy_code = self.current_baseline["strategy_code"]

        if winner_strategy:
            # 尝试使用 LLM 融合赢家策略
            try:
                fused_code = self._fuse_with_winner_strategy_sync(
                    current_code=new_strategy_code,
                    winner_code=winner_strategy,
                    hive_data=hive_data
                )
                if fused_code:
                    new_strategy_code = fused_code
                    logger.info(f"🧬 Successfully fused winner strategy elements!")
                else:
                    logger.info(f"📝 Winner strategy received but fusion skipped (LLM unavailable)")
            except Exception as e:
                logger.warning(f"⚠️ Strategy fusion failed: {e} - keeping current baseline")

        # 更新 baseline
        self.current_baseline = {
            "version": new_version,
            "epoch": epoch,
            "timestamp": datetime.now().isoformat(),
            "strategy_code": new_strategy_code,
            "hive_data": hive_data,
            "performance": performance or {"avg_pnl": 0.0, "win_rate": 0.0, "sharpe_ratio": 0.0},
            "source": f"evolution_epoch_{epoch}"
        }

        # 保存到磁盘
        self._save_to_disk()

        logger.info(f"🧬 Baseline evolved: v{new_version} (epoch {epoch})")
        logger.info(f"   Boost: {hive_data.get('boost', [])}")
        logger.info(f"   Penalize: {hive_data.get('penalize', [])}")

        return self.current_baseline

    def get_current_version(self) -> int:
        """获取当前 baseline 版本号"""
        if self.current_baseline:
            return self.current_baseline["version"]
        return 0

    def get_baseline_history(self) -> List[Dict]:
        """获取 baseline 历史"""
        return self.baseline_history

    def rollback_to_version(self, version: int) -> bool:
        """
        回滚到指定版本（如果新版本表现不好）

        Args:
            version: 要回滚到的版本号

        Returns:
            是否成功回滚
        """
        # 从历史中查找
        for baseline in self.baseline_history:
            if baseline["version"] == version:
                # 重新加载该版本的完整数据
                version_file = self.data_dir / f"baseline_v{version}.json"
                if version_file.exists():
                    with open(version_file, 'r') as f:
                        self.current_baseline = json.load(f)

                    self._save_to_disk()
                    logger.warning(f"⏪ Rolled back to baseline v{version}")
                    return True

        logger.error(f"❌ Cannot rollback: version {version} not found")
        return False

    def _fuse_with_winner_strategy_sync(
        self,
        current_code: str,
        winner_code: str,
        hive_data: Dict
    ) -> Optional[str]:
        """
        使用 LLM 融合赢家策略的成功元素 (同步版本)
        
        融合策略:
        1. 分析赢家策略的关键参数和逻辑
        2. 结合 Hive Mind 的 boost/penalize 信号
        3. 生成融合后的策略代码
        
        Returns:
            融合后的策略代码，失败返回 None
        """
        try:
            from llm_client import call_llm
            import asyncio
            
            boost_tags = hive_data.get("boost", [])
            penalize_tags = hive_data.get("penalize", [])
            
            # 构建融合提示
            prompt = f"""You are a Python trading strategy expert. Your task is to intelligently merge the best elements from a winning strategy into the baseline strategy.

## Current Baseline Strategy (to be improved):
```python
{current_code[:3000]}
```

## Winner Strategy (contains successful patterns):
```python
{winner_code[:3000]}
```

## Hive Mind Signals:
- BOOST (proven profitable): {boost_tags}
- PENALIZE (losing patterns): {penalize_tags}

## Your Task:
1. Identify the KEY SUCCESS FACTORS in the winner strategy (parameters, entry/exit logic, risk management)
2. Extract those elements and merge them into the baseline structure
3. Ensure the merged strategy BOOSTS the successful patterns and AVOIDS the penalized patterns
4. Keep the code clean and functional

## Output:
Return ONLY the complete Python strategy code (starting with `import` and including the full `MyStrategy` class).
Do NOT include explanations or markdown - just the raw Python code."""

            # Run async call synchronously
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            
            if loop and loop.is_running():
                # We're in an async context - can't use run_until_complete
                # Return None to skip fusion this time
                logger.info("⏭️ Skipping LLM fusion (async context)")
                return None
            else:
                # Sync context - can run async code
                result = asyncio.run(call_llm(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=4000,
                    temperature=0.2  # Low temperature for code generation
                ))
            
            if result and "class MyStrategy" in result:
                # Basic validation - ensure it looks like valid Python
                if "def on_price_update" in result and "def __init__" in result:
                    logger.info(f"✅ Strategy fusion generated {len(result)} chars of code")
                    return result
                else:
                    logger.warning("⚠️ Fused strategy missing required methods")
                    return None
            else:
                logger.warning("⚠️ LLM returned invalid strategy code")
                return None
                
        except ImportError:
            logger.warning("⚠️ llm_client not available for strategy fusion")
            return None
        except Exception as e:
            logger.error(f"❌ Strategy fusion error: {e}")
            return None

    def get_performance_comparison(self) -> List[Dict]:
        """
        获取所有版本的性能对比

        Returns:
            [{version, epoch, avg_pnl, win_rate, sharpe_ratio}, ...]
        """
        comparison = []

        for baseline in self.baseline_history:
            comparison.append({
                "version": baseline["version"],
                "epoch": baseline["epoch"],
                "performance": baseline.get("performance", {})
            })

        # 添加当前版本
        if self.current_baseline:
            comparison.append({
                "version": self.current_baseline["version"],
                "epoch": self.current_baseline["epoch"],
                "performance": self.current_baseline.get("performance", {})
            })

        return comparison


# 全局实例
baseline_manager = BaselineManager()


if __name__ == "__main__":
    # 测试
    manager = BaselineManager()

    print("\n📊 Current Baseline:")
    baseline = manager.get_baseline_for_agent("test_agent")
    print(f"Version: {baseline['version']}")
    print(f"Timestamp: {baseline['timestamp']}")
    print(f"Message: {baseline['message']}")

    print("\n🧬 Simulating baseline update...")
    hive_data = {
        "boost": ["DIP_BUY", "VOL_SPIKE"],
        "penalize": ["BREAKOUT"],
        "alpha_factors": {}
    }
    performance = {
        "avg_pnl": 5.2,
        "win_rate": 62.5,
        "sharpe_ratio": 1.8
    }

    new_baseline = manager.update_baseline(
        epoch=10,
        hive_data=hive_data,
        performance=performance
    )

    print(f"\n✅ New baseline v{new_baseline['version']} created")
    print(f"Boost: {new_baseline['hive_data']['boost']}")
    print(f"Penalize: {new_baseline['hive_data']['penalize']}")

    print("\n📈 Performance History:")
    for item in manager.get_performance_comparison():
        print(f"  v{item['version']} (epoch {item['epoch']}): {item['performance']}")
