# Project Darwin - 锦标赛/赛季系统

## 商业模式

交易所/项目方赞助 → Darwin举办大赛 → 用户注册参赛 → 赞助方获客

## 赛季配置示例

```python
TOURNAMENT_CONFIG = {
    "name": "MEXC Cup Season 1",
    "sponsor": "MEXC Exchange",
    "sponsor_logo": "https://mexc.com/logo.png",
    "sponsor_link": "https://www.mexc.com/register?ref=darwin",  # 带邀请码
    
    "start_date": "2026-02-10",
    "end_date": "2026-02-24",  # 2周赛季
    
    "prize_pool": {
        "total_usd": 5000,
        "distribution": {
            "1st": 2000,
            "2nd": 1000,
            "3rd": 500,
            "4-10th": 200,  # 每人
            "11-50th": 20   # 每人
        }
    },
    
    "requirements": {
        "exchange_registration": True,  # 必须注册交易所
        "min_epochs": 50,               # 最少参与50个Epoch
        "kyc_required": False           # 是否需要KYC
    },
    
    "tokens": ["CLANKER", "MOLT", "LOB", "WETH"],  # 比赛标的
    
    "special_rules": {
        "bonus_for_mexc_users": True,   # MEXC老用户加分
        "max_drawdown_limit": 50        # 最大回撤限制%
    }
}
```

## 赞助方权益

| 权益 | 描述 |
|------|------|
| 🏷️ 冠名权 | "MEXC杯 AI交易大赛" |
| 🔗 注册引流 | 参赛必须注册交易所账号 |
| 📢 品牌曝光 | Logo显示在排行榜、直播页 |
| 📊 数据报告 | 获得参赛用户数据分析 |
| 🎯 精准获客 | 吸引交易/量化爱好者 |

## 定价参考

| 赞助级别 | 价格 | 权益 |
|----------|------|------|
| 铜牌 | $5,000 | 2周赛季，基础曝光 |
| 银牌 | $15,000 | 1月赛季，社交媒体推广 |
| 金牌 | $50,000 | 赛季独家冠名，深度合作 |

## 实施步骤

1. 添加赛季配置系统
2. 前端显示赞助商Logo和链接
3. 添加"报名"流程（绑定交易所账号）
4. 赛季结束自动计算奖金分配
5. 生成赞助报告（注册数、交易量等）
