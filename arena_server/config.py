# Project Darwin - Arena Config

# ⚠️ DEPRECATED: TARGET_TOKENS is only used for legacy feeder.py (not used in production)
# Arena now supports ANY token on 50+ chains via DexScreener real-time API
# These are just examples for testing/reference
TARGET_TOKENS = {
    "CLANKER": "0x1bc0c42215582d5a085795f4badbac3ff36d1bcb",
    "MOLT": "0xb695559b26bb2c9703ef1935c37aeae9526bab07",
    "LOB": "0xf682c6D993f73c5A90F6D915F69d3363Eed36e64",
    "WETH": "0x4200000000000000000000000000000000000006",
}

# Arena 参数
EPOCH_DURATION_HOURS = 0.166666  # 10分钟一轮 (正式版)
INITIAL_BALANCE = 1000  # 初始虚拟 USDC
ELIMINATION_THRESHOLD = 0.1  # 底部 10% 淘汰
ASCENSION_THRESHOLD = 0.01  # 顶部 1% 可发币
SIMULATED_SLIPPAGE = 0.01  # 1% 模拟滑点

# === 经济模型 (阶段二启用，当前免费) ===
# 阶段一(当前): 完全免费，通过交易所赞助大赛盈利
# 阶段二(10K+用户): 启用付费竞技场

# L1 训练场 (永久免费)
L1_ENTRY_FEE = 0  # 免费

# L2 竞技场 (阶段二启用，暂时禁用)
L2_ENABLED = False  # 当前禁用付费模式
L2_ENTRY_FEE_ETH = 0.01  # 0.01 ETH 入场费
L2_PRIZE_POOL_RATIO = 0.70  # 70% 奖池给 Top 10%
L2_PLATFORM_FEE_RATIO = 0.20  # 20% 给平台
L2_BURN_RATIO = 0.10  # 10% 烧毁

# L3 发币 (阶段二启用)
TOKEN_LAUNCH_FEE_ETH = 0.1  # 发币手续费

# 税率 (冠军代币交易)
PLATFORM_TAX = 0.005  # 0.5% 归平台
OWNER_TAX = 0.005  # 0.5% 归 Agent 所有者

# === 分组竞技 (Group Arena) ===
# ⚠️ DEPRECATED: TOKEN_POOLS is only used for tournament.py examples (not in production)
# Groups no longer restrict token pools - agents can trade ANY token on ANY chain
# These pools are kept for backward compatibility with tournament examples only
TOKEN_POOLS = [
    # Pool 0: Base chain memes (example only)
    {
        "CLANKER": "0x1bc0c42215582d5a085795f4badbac3ff36d1bcb",
        "MOLT": "0xb695559b26bb2c9703ef1935c37aeae9526bab07",
        "LOB": "0xf682c6D993f73c5A90F6D915F69d3363Eed36e64",
        "WETH": "0x4200000000000000000000000000000000000006",
    },
    # Pool 1: Base chain blue chips (example only)
    {
        "DEGEN": "0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed",
        "BRETT": "0x532f27101965dd16442E59d40670FaF5eBB142E4",
        "TOSHI": "0xAC1Bd2486aAf3B5C0fc3Fd868558b082a531B2B4",
        "HIGHER": "0x0578d8A44db98B23BF096A382e016e29a5Ce0ffe",
    },
    # Pool 2: ETH chain memes
    {
        "PEPE": "0x6982508145454Ce325dDbE47a25d4ec3d2311933",
        "SHIB": "0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE",
        "FLOKI": "0xcf0C122c6b73ff809C693DB761e7BaeBe62b6a2E",
        "TURBO": "0xA35923162C49cF95e6BF26623385eb431ad920D3",
    },
    # Pool 3: Solana memes (DexScreener uses mint address)
    {
        "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
        "MEW": "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5",
    },
]

# 动态分组大小: 根据总Agent数自动调整每组大小
GROUP_SIZE_THRESHOLDS = {
    100: 50,    # < 100 total agents → 50 per group (increased for testing)
    500: 100,   # < 500 total agents → 100 per group
    2000: 200,  # < 2000 total agents → 200 per group
}
GROUP_DEFAULT_SIZE = 500  # >= 2000 agents → 500 per group

# === 限制 ===
MAX_AGENTS_PER_IP = 50  # 每IP最多50个Agent (Increased for testing)
MAX_AGENTS_PER_GROUP = 100  # 每组最大Agent数

# LLM 配置 (可选 - 用于策略进化评分)
import os
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")  # 留空则禁用 LLM 功能
LLM_MODEL = os.getenv("LLM_MODEL", "claude-3-opus-20240229") 
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_ENABLED = bool(LLM_BASE_URL)

# DexScreener API
DEXSCREENER_BASE_URL = "https://api.dexscreener.com"
PRICE_UPDATE_INTERVAL = 10  # 秒

# Platform Wallet (接收费用)
PLATFORM_WALLET = os.getenv("DARWIN_PLATFORM_WALLET", "0x3775f940502fAbC9CD4C84478A8CB262e55AadF9")
