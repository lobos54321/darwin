"""
Self-Coder Skill (Antigravity Proxy Edition)
让 Agent 能够重写自己的策略代码
对接: claude-proxy.zeabur.app (Gemini-3-Pro via Proxy)
"""

import os
import ast
import sys
import shutil
import ssl
import certifi
import json
import types
import random
import tempfile
import traceback
from datetime import datetime
from typing import Optional
import aiohttp

# === 配置 ===
# Proxy URL (兼容 Anthropic 格式)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://claude-proxy.zeabur.app")
# 模型名称 (Proxy 后端支持的模型)
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3-flash")
# API Key (Proxy 可能需要的验证，或者 test)
LLM_API_KEY = os.getenv("LLM_API_KEY", "test")
# 账号池 (Antigravity Proxy 核心)
ACCOUNTS_JSON = os.getenv("ACCOUNTS_JSON", "{}")

# 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # skills/
TEMPLATE_DIR = os.path.dirname(BASE_DIR)              # agent_template/
PROJECT_ROOT = os.path.dirname(TEMPLATE_DIR)           # project root
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
STRATEGY_FILE = os.path.join(TEMPLATE_DIR, "strategy.py")
BACKUP_DIR = os.path.join(TEMPLATE_DIR, "backups")

# SSL context
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

def get_strategy_path(agent_id: str) -> str:
    """获取特定 Agent 的策略文件路径"""
    # 优先检查 data/agents/{id}/strategy.py
    agent_dir = os.path.join(DATA_DIR, "agents", agent_id)
    return os.path.join(agent_dir, "strategy.py")

def read_strategy(agent_id: str) -> str:
    path = get_strategy_path(agent_id)
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read()
    # Fallback to template
    if os.path.exists(STRATEGY_FILE):
        with open(STRATEGY_FILE, "r") as f:
            return f.read()
    return ""

def write_strategy(agent_id: str, new_code: str) -> bool:
    path = get_strategy_path(agent_id)
    
    # 简单的语法检查
    try:
        ast.parse(new_code)
    except SyntaxError as e:
        print(f"❌ Syntax Error in generated code: {e}")
        return False
        
    # Ensure agent directory exists
    agent_dir = os.path.dirname(path)
    os.makedirs(agent_dir, exist_ok=True)
    
    # Backup
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(BACKUP_DIR, f"strategy_{agent_id}_{datetime.now().strftime('%H%M%S')}.py")
    if os.path.exists(path):
        shutil.copy2(path, backup_path)
    
    with open(path, "w") as f:
        f.write(new_code)
    
    print(f"💾 Strategy Saved to {path}")
    return True

def validate_strategy_code(code: str) -> bool:
    """
    Runtime validation gate: compile + execute the generated strategy
    against realistic arena price data to catch errors BEFORE deployment.
    Returns True only if 25 ticks complete without errors.
    """
    tmp_path = None
    try:
        # Step 1: Syntax check
        ast.parse(code)

        # Step 2: Write to temp file and import as module
        fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="strat_validate_")
        os.close(fd)
        with open(tmp_path, "w") as f:
            f.write(code)

        spec = __import__("importlib").util.spec_from_file_location("_test_strat", tmp_path)
        mod = __import__("importlib").util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Step 3: Find the Strategy class
        strategy_cls = None
        for name in dir(mod):
            obj = getattr(mod, name)
            if isinstance(obj, type) and hasattr(obj, "on_price_update") and name != "object":
                strategy_cls = obj
                break

        if strategy_cls is None:
            print("⚠️ Validation FAILED: No class with on_price_update() found")
            return False

        # Step 4: Instantiate
        try:
            strategy = strategy_cls()
        except Exception as e:
            print(f"⚠️ Validation FAILED (__init__): {e}")
            return False

        # Step 5: Run 25 ticks with realistic arena price data format
        symbols = ["CLANKER", "WETH", "LOB", "MOLT", "PEPE"]
        for tick in range(25):
            prices = {}
            for sym in symbols:
                base = random.uniform(0.01, 100.0)
                prices[sym] = {
                    "priceUsd": base + random.uniform(-1, 1),
                    "priceChange24h": random.uniform(-30, 30),
                    "volume24h": random.uniform(1000, 1000000),
                    "liquidity": random.uniform(10000, 5000000),
                    "dex": "uniswap_v3",
                    "pairAddress": f"0x{'ab' * 20}"
                }

            result = strategy.on_price_update(prices)

            # Validate return format
            if result is not None:
                if not isinstance(result, dict):
                    print(f"⚠️ Validation FAILED (tick {tick}): on_price_update returned {type(result).__name__}, expected dict or None")
                    return False
                for key in ("symbol", "side", "amount"):
                    if key not in result:
                        print(f"⚠️ Validation FAILED (tick {tick}): missing key '{key}' in result: {result}")
                        return False

        print("✅ Validation PASSED: 25 ticks completed without errors")
        return True

    except SyntaxError as e:
        print(f"⚠️ Validation FAILED (syntax): {e}")
        return False
    except Exception as e:
        print(f"⚠️ Validation FAILED (runtime): {e}")
        traceback.print_exc()
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


async def mutate_strategy(agent_id: str, penalty_tags: list, api_key: str = None, arena_url: str = None, winner_wisdom: str = "", winner_strategy: str = "") -> bool:
    """
    基于 Hive Mind 惩罚标签 + 赢家智慧进化策略
    使用的是 Agent 自己的 LLM (Antigravity Proxy / 用户自配)
    """
    print(f"🧬 Initiating True Evolution for {agent_id}. Penalty: {penalty_tags}")

    current_code = read_strategy(agent_id)
    if not current_code:
        print("❌ Could not read strategy code.")
        return False

    # Build prompt with winner context if available
    winner_section = ""
    if winner_wisdom:
        winner_section += f"\n## Winner's Wisdom:\n{winner_wisdom}\n"
    if winner_strategy:
        winner_section += f"\n## Winner's Strategy (reference):\n```python\n{winner_strategy[:2000]}\n```\n"

    prompt = f"""You are an elite High-Frequency Trading Quant Developer.
The current strategy has been PENALIZED by the Hive Mind for the following behaviors: {penalty_tags}.
{winner_section}
Your Goal: REWRITE the strategy code to fix these flaws and improve profitability.
Learn from the winner's approach but add your own unique mutations to avoid homogenization.

## Requirements:
1. **Fix the Penalized Logic**: If penalized for 'DIP_BUY', make the dip buying conditions stricter (e.g. lower RSI, deeper Z-score).
2. **Keep Essential Methods**: You MUST preserve `__init__` and `on_price_update(self, prices)`.
3. **Return Format**: `on_price_update` must return a dict like `{{'side': 'BUY', 'symbol': 'BTC', 'amount': 0.1, 'reason': ['TAG']}}` or None.
4. **Python Only**: Output ONLY valid Python code. No markdown, no explanations.
5. **Price Data Format**: The `prices` dict maps symbol strings to dicts. Each value is a dict with keys: `priceUsd` (float), `priceChange24h` (float), `volume24h` (float), `liquidity` (float), `dex` (str), `pairAddress` (str). Access price via `prices[symbol]["priceUsd"]`. Do NOT treat price values as plain floats.

## Current Strategy:
```python
{current_code}
```
"""
    # 构造请求头
    headers = {
        "x-api-key": LLM_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        # 关键：传递账号池给 Proxy
        "x-accounts": ACCOUNTS_JSON 
    }

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8192
    }

    print(f"📡 Calling Antigravity Proxy ({LLM_BASE_URL}) with {LLM_MODEL}...")
    
    try:
        connector = aiohttp.TCPConnector(ssl=SSL_CONTEXT)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                f"{LLM_BASE_URL}/v1/messages",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"❌ Proxy Error {resp.status}: {text}")
                    return False
                
                data = await resp.json()
                
                # 解析 Anthropic 格式响应
                try:
                    content_blocks = data.get("content", [])
                    raw_text = ""
                    for block in content_blocks:
                        if block.get("type") == "text":
                            raw_text += block.get("text", "")
                except Exception as e:
                    print(f"❌ Invalid Proxy response format: {e}")
                    return False
                
                # 提取代码
                code = raw_text
                if "```python" in code:
                    code = code.split("```python")[1].split("```")[0]
                elif "```" in code:
                    code = code.split("```")[1].split("```")[0]
                
                code = code.strip()

                # Validate before writing
                if not validate_strategy_code(code):
                    print(f"⚠️ Generated strategy for {agent_id} failed validation. Keeping old strategy.")
                    return False

                if write_strategy(agent_id, code):
                    print(f"✅ Evolution Successful! {agent_id} strategy updated.")
                    return True
                return False

    except Exception as e:
        print(f"❌ Exception during Proxy call: {e}")
        return False
