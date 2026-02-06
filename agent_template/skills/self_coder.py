"""
Self-Coder Skill
让 Agent 能够重写自己的策略代码

⚠️ 这是 Darwin 进化的核心能力
"""

import os
import re
import random
import shutil
import ssl
import certifi
import aiohttp
from datetime import datetime

# 配置
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com") # 默认 Google 官方 API
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.0-flash-exp") # 使用当前最强的 2.0 预览版或 1.5 Pro
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

# 路径计算 (相对于当前文件位置: agent_template/skills/self_coder.py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # skills/
TEMPLATE_DIR = os.path.dirname(BASE_DIR)              # agent_template/
STRATEGY_FILE = os.path.join(TEMPLATE_DIR, "strategy.py")
BACKUP_DIR = os.path.join(TEMPLATE_DIR, "backups")

# SSL context
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

def get_strategy_path(agent_id: str) -> str:
    """获取特定 Agent 的策略文件路径"""
    # 始终返回专属路径，不管文件是否存在
    return os.path.join(TEMPLATE_DIR, f"strategy_{agent_id}.py")

def read_strategy(agent_id: str) -> str:
    path = get_strategy_path(agent_id)
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read()
            
    # Fallback to template (read-only mode)
    if os.path.exists(STRATEGY_FILE):
        with open(STRATEGY_FILE, "r") as f:
            return f.read()
    return ""

def write_strategy(agent_id: str, new_code: str) -> bool:
    path = get_strategy_path(agent_id)
    
    # 简单的语法检查
    if "class MyStrategy" not in new_code:
        print("❌ Invalid code: Missing class definition")
        return False
        
    # Backup
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(BACKUP_DIR, f"strategy_{agent_id}_{datetime.now().strftime('%H%M%S')}.py")
    if os.path.exists(path):
        shutil.copy2(path, backup_path)
    
    with open(path, "w") as f:
        f.write(new_code)
    
    print(f"💾 Strategy Saved to {path}")
    return True

async def upload_strategy_to_server(agent_id: str, code: str, api_key: str, arena_url: str):
    """上传策略到服务器，用于 Champion Strategy 功能"""
    if not api_key or not arena_url:
        return
        
    print(f"☁️ Uploading strategy to {arena_url}...")
    try:
        # 去掉 ws:// 前缀，改为 http/https
        http_url = arena_url.replace("ws://", "http://").replace("wss://", "https://")
        endpoint = f"{http_url}/agent/strategy"
        
        headers = {
            "x-agent-id": agent_id,
            "x-api-key": api_key,
            "Content-Type": "application/json"
        }
        
        payload = {"code": code}
        
        connector = aiohttp.TCPConnector(ssl=SSL_CONTEXT)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(endpoint, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    print("✅ Strategy uploaded to server successfully!")
                else:
                    text = await resp.text()
                    print(f"⚠️ Failed to upload strategy: {resp.status} - {text}")
    except Exception as e:
        print(f"⚠️ Upload exception: {e}")

async def mutate_strategy(agent_id: str, penalty_tags: list, api_key: str = None, arena_url: str = None) -> bool:
    """
    基于 Hive Mind 惩罚标签进化策略
    
    🔥 TRUE EVOLUTION MODE: ONLY USES LLM.
    """
    print(f"🧬 Initiating True Evolution for {agent_id}. Penalty: {penalty_tags}")
    
    current_code = read_strategy(agent_id)
    if not current_code:
        print("❌ Could not read strategy code.")
        return False

    # 检查 API Key
    if not LLM_API_KEY or LLM_API_KEY == "test":
        print("❌ CRITICAL: No LLM_API_KEY found. Evolution aborted.")
        print("👉 Please set LLM_API_KEY in your environment to enable AI coding.")
        return False

    # 调用 LLM 进行真正的代码重写
    success = await call_llm_mutation(agent_id, current_code, penalty_tags, api_key, arena_url)
    return success

async def call_llm_mutation(agent_id: str, current_code: str, tags: list, api_key: str = None, arena_url: str = None) -> bool:
    """调用 Google Gemini API 重写代码"""
    print(f"📡 Calling LLM ({LLM_MODEL}) to refactor strategy...")
    
    prompt = f"""You are an elite High-Frequency Trading Quant Developer.
The current strategy has been PENALIZED by the Hive Mind for the following behaviors: {tags}.

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

    try:
        url = f"{LLM_BASE_URL}/v1beta/models/{LLM_MODEL}:generateContent?key={LLM_API_KEY}"
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }
        
        connector = aiohttp.TCPConnector(ssl=SSL_CONTEXT)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(url, json=payload, timeout=60) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"❌ LLM Error {resp.status}: {text}")
                    return False
                
                data = await resp.json()
                try:
                    # Handle Gemini structure
                    raw_text = data['candidates'][0]['content']['parts'][0]['text']
                except (KeyError, IndexError):
                    print("❌ Invalid LLM response format")
                    return False
                
                # Extract Code
                code = raw_text
                if "```python" in code:
                    code = code.split("```python")[1].split("```")[0]
                elif "```" in code:
                    code = code.split("```")[1].split("```")[0]
                
                code = code.strip()
                
                if write_strategy(agent_id, code):
                    # 如果保存成功，尝试上传到服务器
                    if api_key and arena_url:
                        await upload_strategy_to_server(agent_id, code, api_key, arena_url)
                    return True
                return False

    except Exception as e:
        print(f"❌ Exception during LLM call: {e}")
        return False
