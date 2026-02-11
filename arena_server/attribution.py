"""
归因分析器 (Attribution Analyzer)
分析策略标签的有效性，识别哪些策略在当前市场有效
"""

import time
from typing import Dict, List, Optional
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class TagPerformance:
    """标签表现"""
    tag: str
    trades: List[Dict] = field(default_factory=list)  # 已完成的交易
    pending: List[Dict] = field(default_factory=list)  # 待复盘的交易
    
    # 统计数据
    total_trades: int = 0
    winning_trades: int = 0
    avg_pnl: float = 0.0
    win_rate: float = 0.0
    
    # 状态
    status: str = "NEUTRAL"  # EFFECTIVE, INEFFECTIVE, NEUTRAL
    weight: float = 0.5  # 推荐权重
    
    def update_stats(self):
        """更新统计数据"""
        if not self.trades:
            return
        
        self.total_trades = len(self.trades)
        self.winning_trades = sum(1 for t in self.trades if t["pnl_pct"] > 0)
        self.avg_pnl = sum(t["pnl_pct"] for t in self.trades) / self.total_trades
        self.win_rate = self.winning_trades / self.total_trades
        
        # 判断有效性
        if self.avg_pnl > 5 and self.win_rate > 0.6:
            self.status = "EFFECTIVE"
            self.weight = 1.0
        elif self.avg_pnl < -3 or self.win_rate < 0.4:
            self.status = "INEFFECTIVE"
            self.weight = 0.2
        else:
            self.status = "NEUTRAL"
            self.weight = 0.5


class AttributionAnalyzer:
    """归因分析器"""
    
    def __init__(self, review_interval: int = 3600):
        """
        Args:
            review_interval: 复盘间隔（秒），默认 1 小时
        """
        self.review_interval = review_interval
        self.tag_performance: Dict[str, TagPerformance] = {}
        self.last_review_time = time.time()
        
        # 预定义标签
        self.known_tags = [
            "VOL_SPIKE",      # 成交量突破
            "MOMENTUM",       # 动量
            "RSI_OVERSOLD",   # RSI 超卖
            "RSI_OVERBOUGHT", # RSI 超买
            "LIQUIDITY_HIGH", # 高流动性
            "LIQUIDITY_LOW",  # 低流动性
            "BREAKOUT",       # 突破
            "MEAN_REVERSION", # 均值回归
            "TREND_FOLLOWING",# 趋势跟随
            "TAKE_PROFIT",    # 止盈
            "STOP_LOSS",      # 止损
        ]
        
        # 初始化所有标签
        for tag in self.known_tags:
            self.tag_performance[tag] = TagPerformance(tag=tag)
    
    def record_trade(self, trade: Dict):
        """
        记录交易
        
        Args:
            trade: {
                "agent_id": str,
                "symbol": str,
                "side": "BUY" | "SELL",
                "amount": float,
                "price": float,
                "value": float,
                "reason": List[str],  # 策略标签
                "time": str,
                "trade_pnl": float (SELL only)
            }
        """
        # 只记录 BUY 交易到 pending（等待复盘）
        if trade["side"] == "BUY":
            for tag in trade.get("reason", []):
                if tag not in self.tag_performance:
                    self.tag_performance[tag] = TagPerformance(tag=tag)
                
                self.tag_performance[tag].pending.append({
                    "agent_id": trade["agent_id"],
                    "symbol": trade["symbol"],
                    "entry_price": trade["price"],
                    "entry_time": time.time(),
                    "amount": trade["amount"],
                    "value": trade["value"]
                })
        
        # SELL 交易直接记录结果
        elif trade["side"] == "SELL" and trade.get("trade_pnl") is not None:
            for tag in trade.get("reason", []):
                if tag not in self.tag_performance:
                    self.tag_performance[tag] = TagPerformance(tag=tag)
                
                self.tag_performance[tag].trades.append({
                    "symbol": trade["symbol"],
                    "pnl_pct": trade["trade_pnl"],
                    "exit_time": time.time()
                })
                
                # 更新统计
                self.tag_performance[tag].update_stats()
    
    def review_pending_trades(self, current_prices: Dict[str, float]):
        """
        复盘待评估的交易
        
        Args:
            current_prices: 当前价格字典 {symbol: price}
        """
        now = time.time()
        
        # 检查是否到了复盘时间
        if now - self.last_review_time < self.review_interval:
            return
        
        self.last_review_time = now
        
        print(f"\n🔍 归因分析 - 复盘 {self.review_interval}s 前的交易")
        print("=" * 60)
        
        reviewed_count = 0
        
        for tag, perf in self.tag_performance.items():
            if not perf.pending:
                continue
            
            # 检查每个待复盘的交易
            for trade in list(perf.pending):
                # 如果超过复盘间隔
                if now - trade["entry_time"] >= self.review_interval:
                    symbol = trade["symbol"]
                    current_price = current_prices.get(symbol)
                    
                    if current_price is None:
                        # 价格不可用，跳过
                        continue
                    
                    # 计算收益
                    pnl_pct = (current_price - trade["entry_price"]) / trade["entry_price"] * 100
                    
                    # 记录结果
                    perf.trades.append({
                        "symbol": symbol,
                        "pnl_pct": pnl_pct,
                        "exit_time": now
                    })
                    
                    # 从 pending 移除
                    perf.pending.remove(trade)
                    reviewed_count += 1
            
            # 更新统计
            if perf.trades:
                perf.update_stats()
        
        if reviewed_count > 0:
            print(f"✅ 复盘了 {reviewed_count} 笔交易")
            self.print_summary()
        else:
            print("⏳ 没有需要复盘的交易")
    
    def get_strategy_update(self) -> Dict:
        """
        生成策略更新消息（用于热更新）
        
        Returns:
            {
                "boost": List[str],  # 提升权重的标签
                "penalize": List[str],  # 降低权重的标签
                "new_weights": Dict[str, float],  # 新权重
                "reasoning": str  # 原因说明
            }
        """
        boost = []
        penalize = []
        new_weights = {}
        
        for tag, perf in self.tag_performance.items():
            new_weights[tag] = perf.weight
            
            if perf.status == "EFFECTIVE":
                boost.append(tag)
            elif perf.status == "INEFFECTIVE":
                penalize.append(tag)
        
        # 生成原因说明
        reasoning_parts = []
        if boost:
            reasoning_parts.append(f"有效策略: {', '.join(boost)}")
        if penalize:
            reasoning_parts.append(f"失效策略: {', '.join(penalize)}")
        
        reasoning = "; ".join(reasoning_parts) if reasoning_parts else "市场稳定，策略权重不变"
        
        return {
            "boost": boost,
            "penalize": penalize,
            "new_weights": new_weights,
            "reasoning": reasoning
        }
    
    def analyze(self) -> Dict:
        """
        分析所有策略标签的表现
        
        Returns:
            {
                "total_trades": int,
                "top_performers": List[Dict],
                "bottom_performers": List[Dict],
                "tag_stats": Dict
            }
        """
        # 更新所有标签的统计数据
        for perf in self.tag_performance.values():
            if perf.trades:
                perf.update_stats()
        
        # 收集有交易数据的标签
        active_tags = [(tag, perf) for tag, perf in self.tag_performance.items() 
                      if perf.total_trades > 0]
        
        if not active_tags:
            return {
                "total_trades": 0,
                "top_performers": [],
                "bottom_performers": [],
                "tag_stats": {}
            }
        
        # 按平均收益排序
        sorted_by_pnl = sorted(active_tags, key=lambda x: x[1].avg_pnl, reverse=True)
        
        # Top 5 和 Bottom 5
        top_performers = [
            {
                "tag": tag,
                "total_trades": perf.total_trades,
                "win_rate": round(perf.win_rate * 100, 1),
                "avg_pnl": round(perf.avg_pnl, 2),
                "status": perf.status
            }
            for tag, perf in sorted_by_pnl[:5]
        ]
        
        bottom_performers = [
            {
                "tag": tag,
                "total_trades": perf.total_trades,
                "win_rate": round(perf.win_rate * 100, 1),
                "avg_pnl": round(perf.avg_pnl, 2),
                "status": perf.status
            }
            for tag, perf in sorted_by_pnl[-5:]
        ]
        
        # 总交易数
        total_trades = sum(perf.total_trades for _, perf in active_tags)
        
        # 所有标签统计
        tag_stats = {
            tag: {
                "total_trades": perf.total_trades,
                "winning_trades": perf.winning_trades,
                "avg_pnl": round(perf.avg_pnl, 2),
                "win_rate": round(perf.win_rate * 100, 1),
                "status": perf.status,
                "weight": perf.weight
            }
            for tag, perf in active_tags
        }
        
        return {
            "total_trades": total_trades,
            "top_performers": top_performers,
            "bottom_performers": bottom_performers,
            "tag_stats": tag_stats
        }
    
    def generate_hot_patch(self) -> Dict:
        """
        生成热更新补丁（简化版 get_strategy_update）
        
        Returns:
            {
                "boost": List[str],
                "penalize": List[str]
            }
        """
        boost = []
        penalize = []
        
        for tag, perf in self.tag_performance.items():
            if perf.total_trades < 3:  # 至少 3 笔交易才有统计意义
                continue
            
            if perf.status == "EFFECTIVE":
                boost.append(tag)
            elif perf.status == "INEFFECTIVE":
                penalize.append(tag)
        
        return {
            "boost": boost,
            "penalize": penalize
        }
    
    def get_champion_strategy(self, agent_trades: List[Dict]) -> Dict:
        """
        分析冠军使用的策略
        
        Args:
            agent_trades: 冠军的所有交易记录
        
        Returns:
            {
                "top_tags": List[tuple],  # [(tag, count), ...]
                "avg_pnl": float,
                "win_rate": float
            }
        """
        tag_counts = defaultdict(int)
        total_pnl = 0
        winning_trades = 0
        total_trades = 0
        
        for trade in agent_trades:
            if trade.get("trade_pnl") is not None:
                total_pnl += trade["trade_pnl"]
                if trade["trade_pnl"] > 0:
                    winning_trades += 1
                total_trades += 1
            
            for tag in trade.get("reason", []):
                tag_counts[tag] += 1
        
        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
        
        return {
            "top_tags": top_tags,
            "avg_pnl": total_pnl / total_trades if total_trades > 0 else 0,
            "win_rate": winning_trades / total_trades if total_trades > 0 else 0
        }
    
    def print_summary(self):
        """打印归因分析摘要"""
        print("\n📊 策略标签表现")
        print("=" * 80)
        
        # 按状态分组
        effective = []
        ineffective = []
        neutral = []
        
        for tag, perf in self.tag_performance.items():
            if perf.total_trades == 0:
                continue
            
            if perf.status == "EFFECTIVE":
                effective.append((tag, perf))
            elif perf.status == "INEFFECTIVE":
                ineffective.append((tag, perf))
            else:
                neutral.append((tag, perf))
        
        # 打印有效策略
        if effective:
            print("\n⭐ 有效策略 (EFFECTIVE)")
            print("-" * 80)
            for tag, perf in sorted(effective, key=lambda x: x[1].avg_pnl, reverse=True):
                print(f"  {tag:20s} | 权重: {perf.weight:.1f} | "
                      f"交易: {perf.total_trades:3d} | "
                      f"胜率: {perf.win_rate*100:5.1f}% | "
                      f"平均收益: {perf.avg_pnl:+6.2f}%")
        
        # 打印失效策略
        if ineffective:
            print("\n⚠️  失效策略 (INEFFECTIVE)")
            print("-" * 80)
            for tag, perf in sorted(ineffective, key=lambda x: x[1].avg_pnl):
                print(f"  {tag:20s} | 权重: {perf.weight:.1f} | "
                      f"交易: {perf.total_trades:3d} | "
                      f"胜率: {perf.win_rate*100:5.1f}% | "
                      f"平均收益: {perf.avg_pnl:+6.2f}%")
        
        # 打印中性策略
        if neutral:
            print("\n➡️  中性策略 (NEUTRAL)")
            print("-" * 80)
            for tag, perf in sorted(neutral, key=lambda x: x[1].avg_pnl, reverse=True):
                print(f"  {tag:20s} | 权重: {perf.weight:.1f} | "
                      f"交易: {perf.total_trades:3d} | "
                      f"胜率: {perf.win_rate*100:5.1f}% | "
                      f"平均收益: {perf.avg_pnl:+6.2f}%")
        
        print("=" * 80)
    
    def get_report(self) -> Dict:
        """
        获取完整报告（用于 API）
        
        Returns:
            {
                "tag": {
                    "total_trades": int,
                    "winning_trades": int,
                    "avg_pnl": float,
                    "win_rate": float,
                    "status": str,
                    "weight": float
                }
            }
        """
        report = {}
        
        for tag, perf in self.tag_performance.items():
            if perf.total_trades > 0:
                report[tag] = {
                    "total_trades": perf.total_trades,
                    "winning_trades": perf.winning_trades,
                    "avg_pnl": round(perf.avg_pnl, 2),
                    "win_rate": round(perf.win_rate, 2),
                    "status": perf.status,
                    "weight": perf.weight
                }
        
        return report


# 测试
if __name__ == "__main__":
    analyzer = AttributionAnalyzer(review_interval=10)  # 10 秒复盘
    
    # 模拟交易
    analyzer.record_trade({
        "agent_id": "Agent_001",
        "symbol": "DEGEN",
        "side": "BUY",
        "amount": 1000,
        "price": 0.01,
        "value": 10,
        "reason": ["VOL_SPIKE", "MOMENTUM"],
        "time": "2024-01-01T00:00:00"
    })
    
    analyzer.record_trade({
        "agent_id": "Agent_002",
        "symbol": "BRETT",
        "side": "BUY",
        "amount": 500,
        "price": 0.05,
        "value": 25,
        "reason": ["RSI_OVERSOLD"],
        "time": "2024-01-01T00:00:00"
    })
    
    # 等待 10 秒
    time.sleep(11)
    
    # 复盘
    current_prices = {
        "DEGEN": 0.011,  # +10%
        "BRETT": 0.048   # -4%
    }
    
    analyzer.review_pending_trades(current_prices)
    
    # 获取策略更新
    update = analyzer.get_strategy_update()
    print(f"\n🔥 策略更新: {update}")
