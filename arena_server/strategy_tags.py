"""
策略标签定义
所有Agents使用统一的标签体系，用于归因分析和集体学习
"""

# 入场策略标签 (Entry Strategy Tags)
ENTRY_TAGS = {
    "VOL_SPIKE": "成交量突破 (24h volume > 3x average)",
    "MOMENTUM": "动量策略 (价格24h涨幅 > 5%)",
    "RSI_OVERSOLD": "RSI超卖 (RSI < 30)",
    "RSI_OVERBOUGHT": "RSI超买 (RSI > 70)",
    "BREAKOUT": "价格突破 (突破阻力位)",
    "MEAN_REVERSION": "均值回归 (价格偏离均线)",
    "LIQUIDITY_HIGH": "高流动性 (流动性 > $100k)",
    "LIQUIDITY_LOW": "低流动性 (流动性 < $50k)",
    "SOCIAL_BUZZ": "社交媒体热度",
    "WHALE_ACTIVITY": "巨鲸活动",
    "NEW_LISTING": "新上市代币",
    "TREND_FOLLOWING": "趋势跟随",
    "SUPPORT_BOUNCE": "支撑位反弹",
    "FOMO": "FOMO追涨",
    "DEGEN_PLAY": "高风险投机",
}

# 出场策略标签 (Exit Strategy Tags)
EXIT_TAGS = {
    "TAKE_PROFIT": "止盈",
    "STOP_LOSS": "止损",
    "TRAILING_STOP": "移动止损",
    "TIME_DECAY": "持仓时间过长",
    "MOMENTUM_LOSS": "动量消失",
    "VOLUME_DRY": "成交量枯竭",
    "RESISTANCE_HIT": "触及阻力位",
    "PROFIT_TARGET": "达到目标收益",
    "RISK_MANAGEMENT": "风险管理",
    "REBALANCE": "仓位再平衡",
}

# 所有标签
ALL_TAGS = {**ENTRY_TAGS, **EXIT_TAGS}

# 标签分类
TAG_CATEGORIES = {
    "technical": ["VOL_SPIKE", "MOMENTUM", "RSI_OVERSOLD", "RSI_OVERBOUGHT", "BREAKOUT", "MEAN_REVERSION"],
    "fundamental": ["LIQUIDITY_HIGH", "LIQUIDITY_LOW", "NEW_LISTING"],
    "sentiment": ["SOCIAL_BUZZ", "WHALE_ACTIVITY", "FOMO"],
    "risk_management": ["TAKE_PROFIT", "STOP_LOSS", "TRAILING_STOP", "RISK_MANAGEMENT"],
}


def validate_tags(tags: list) -> list:
    """
    验证并过滤标签

    Args:
        tags: 标签列表

    Returns:
        有效的标签列表
    """
    if not tags:
        return []

    if isinstance(tags, str):
        tags = [tags]

    return [tag for tag in tags if tag in ALL_TAGS]


def get_tag_description(tag: str) -> str:
    """
    获取标签描述

    Args:
        tag: 标签名称

    Returns:
        标签描述
    """
    return ALL_TAGS.get(tag, "Unknown tag")


def get_tag_category(tag: str) -> str:
    """
    获取标签分类

    Args:
        tag: 标签名称

    Returns:
        分类名称
    """
    for category, tags in TAG_CATEGORIES.items():
        if tag in tags:
            return category
    return "other"


def get_recommended_tags(market_condition: str) -> list:
    """
    根据市场状况推荐标签

    Args:
        market_condition: "bullish", "bearish", "sideways", "volatile"

    Returns:
        推荐的标签列表
    """
    recommendations = {
        "bullish": ["MOMENTUM", "BREAKOUT", "TREND_FOLLOWING", "VOL_SPIKE"],
        "bearish": ["RSI_OVERSOLD", "SUPPORT_BOUNCE", "MEAN_REVERSION"],
        "sideways": ["MEAN_REVERSION", "SUPPORT_BOUNCE", "RESISTANCE_HIT"],
        "volatile": ["VOL_SPIKE", "MOMENTUM", "QUICK_PROFIT"],
    }

    return recommendations.get(market_condition, [])


def format_tags_for_display(tags: list) -> str:
    """
    格式化标签用于显示

    Args:
        tags: 标签列表

    Returns:
        格式化的字符串
    """
    if not tags:
        return "No tags"

    return ", ".join(tags)


def get_tag_emoji(tag: str) -> str:
    """
    获取标签对应的emoji

    Args:
        tag: 标签名称

    Returns:
        emoji字符
    """
    emoji_map = {
        "VOL_SPIKE": "📊",
        "MOMENTUM": "🚀",
        "RSI_OVERSOLD": "📉",
        "RSI_OVERBOUGHT": "📈",
        "BREAKOUT": "💥",
        "MEAN_REVERSION": "↩️",
        "LIQUIDITY_HIGH": "💧",
        "LIQUIDITY_LOW": "🏜️",
        "SOCIAL_BUZZ": "📱",
        "WHALE_ACTIVITY": "🐋",
        "NEW_LISTING": "🆕",
        "TAKE_PROFIT": "💰",
        "STOP_LOSS": "🛑",
        "TRAILING_STOP": "🎯",
        "TIME_DECAY": "⏰",
        "MOMENTUM_LOSS": "📉",
        "VOLUME_DRY": "🏜️",
    }

    return emoji_map.get(tag, "🏷️")


# 预定义的标签组合（经过验证的有效组合）
PROVEN_COMBOS = [
    ["VOL_SPIKE", "MOMENTUM"],
    ["RSI_OVERSOLD", "SUPPORT_BOUNCE"],
    ["BREAKOUT", "VOL_SPIKE"],
    ["LIQUIDITY_HIGH", "MOMENTUM"],
    ["WHALE_ACTIVITY", "VOL_SPIKE"],
]


def is_proven_combo(tags: list) -> bool:
    """
    检查是否是经过验证的标签组合

    Args:
        tags: 标签列表

    Returns:
        是否是经过验证的组合
    """
    sorted_tags = sorted(tags)

    for combo in PROVEN_COMBOS:
        if sorted(combo) == sorted_tags:
            return True

    return False


# 导出
__all__ = [
    "ENTRY_TAGS",
    "EXIT_TAGS",
    "ALL_TAGS",
    "TAG_CATEGORIES",
    "validate_tags",
    "get_tag_description",
    "get_tag_category",
    "get_recommended_tags",
    "format_tags_for_display",
    "get_tag_emoji",
    "PROVEN_COMBOS",
    "is_proven_combo",
]
