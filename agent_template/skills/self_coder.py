"""
Self-Coder Skill (OpenAI-Compatible Proxy Edition)
让 Agent 能够重写自己的策略代码
对接: claude-proxy.zeabur.app (OpenAI-compatible format)
"""

import os
import ast
import shutil
import ssl
import certifi
import json
from datetime import datetime
from typing import Optional
import aiohttp

# === 配置 ===
# Proxy URL (OpenAI-compatible: already includes /v1)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://claude-proxy.zeabur.app/v1")
# 模型名称 (Proxy 后端支持的模型)
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3-pro-high")
# API Key
LLM_API_KEY = os.getenv("LLM_API_KEY", "test")

# 路径配置 — matches agent.py _load_strategy() which reads from data/agents/{id}/strategy.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # skills/
TEMPLATE_DIR = os.path.dirname(BASE_DIR)              # agent_template/
PROJECT_ROOT = os.path.dirname(TEMPLATE_DIR)           # project root
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
STRATEGY_FILE = os.path.join(TEMPLATE_DIR, "strategy.py")
BACKUP_DIR = os.path.join(TEMPLATE_DIR, "backups")

# SSL context
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

def get_strategy_path(agent_id: str) -> str:
    """获取特定 Agent 的策略文件路径 — matches agent.py _load_strategy()"""
    agent_dir = os.path.join(DATA_DIR, "agents", agent_id)
    return os.path.join(agent_dir, "strategy.py")

def read_strategy(agent_id: str) -> str:
    path = get_strategy_path(agent_id)
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read()
    # Fallback to default template
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

async def mutate_strategy(agent_id: str, penalty_tags: list, api_key: str = None, arena_url: str = None) -> bool:
    """
    基于 Hive Mind 惩罚标签进化策略
    使用的是 Antigravity Proxy (Gemini 3 Pro)
    """
    print(f"🧬 Initiating True Evolution for {agent_id}. Penalty: {penalty_tags}")
    
    current_code = read_strategy(agent_id)
    if not current_code:
        print("❌ Could not read strategy code.")
        return False

    prompt = f"""You are an elite High-Frequency Trading Quant Developer.
The current strategy has been PENALIZED by the Hive Mind for the following behaviors: {penalty_tags}.

Your Goal: REWRITE the strategy code to fix these flaws and improve profitability.

## Requirements:
1. **Fix the Penalized Logic**: If penalized for 'DIP_BUY', make the dip buying conditions stricter (e.g. lower RSI, deeper Z-score).
2. **Keep Essential Methods**: You MUST preserve `__init__` and `on_price_update(self, prices)`.
3. **Return Format**: `on_price_update` must return a dict like `{{'side': 'BUY', 'symbol': 'BTC', 'amount': 0.1, 'reason': ['TAG']}}`.
4. **Python Only**: Output ONLY valid Python code. No markdown, no explanations.

## Current Strategy:
```python
{current_code}
```
"""
    # OpenAI-compatible headers
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are an elite HFT quant developer. Output ONLY valid Python code, no markdown fences, no explanations."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 8192,
        "temperature": 0.7
    }

    print(f"📡 Calling LLM Proxy ({LLM_BASE_URL}) with {LLM_MODEL}...")

    try:
        connector = aiohttp.TCPConnector(ssl=SSL_CONTEXT)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"❌ Proxy Error {resp.status}: {text}")
                    return False

                data = await resp.json()

                # Parse OpenAI-compatible response
                try:
                    raw_text = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError) as e:
                    print(f"❌ Invalid response format: {e}")
                    return False

                # 提取代码
                code = raw_text
                if "```python" in code:
                    code = code.split("```python")[1].split("```")[0]
                elif "```" in code:
                    code = code.split("```")[1].split("```")[0]

                code = code.strip()

                if write_strategy(agent_id, code):
                    print(f"✅ Evolution Successful! {agent_id} strategy updated.")
                    return True
                return False

    except Exception as e:
        print(f"❌ Exception during Proxy call: {e}")
        return False
