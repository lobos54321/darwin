# Project Darwin - Arena Config

# 交易标的白名单
TARGET_TOKENS = {
    "CLANKER": "0x1bc0c42215582d5a085795f4badbac3ff36d1bcb",
    "MOLT": "0xb695559b26bb2c9703ef1935c37aeae9526bab07",
    "LOB": "0xf682c6D993f73c5A90F6D915F69d3363Eed36e64",
    "WETH": "0x4200000000000000000000000000000000000006",
}

# Arena 参数
EPOCH_DURATION_HOURS = 4  # 每轮时长
INITIAL_BALANCE = 1000  # 初始虚拟 USDC
ELIMINATION_THRESHOLD = 0.1  # 底部 10% 淘汰
ASCENSION_THRESHOLD = 0.01  # 顶部 1% 可发币
SIMULATED_SLIPPAGE = 0.01  # 1% 模拟滑点

# 税率 (冠军代币)
PLATFORM_TAX = 0.005  # 0.5% 归平台
OWNER_TAX = 0.005  # 0.5% 归 Agent 所有者

# LLM 配置
LLM_BASE_URL = "http://localhost:8080"
LLM_MODEL = "gemini-3-pro"
LLM_API_KEY = "test"  # 本地代理

# DexScreener API
DEXSCREENER_BASE_URL = "https://api.dexscreener.com"
PRICE_UPDATE_INTERVAL = 10  # 秒
