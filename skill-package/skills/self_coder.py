"""
Self-Coder Skill
让 Agent 能够重写自己的策略代码

⚠️ 这是 Darwin 进化的核心能力
"""

import os
import ast
import shutil
import ssl
import certifi
from datetime import datetime
from typing import Optional
import aiohttp

# 配置
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8080")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3-pro-low")  # 用低配版本省 token
LLM_API_KEY = os.getenv("LLM_API_KEY", "test")

STRATEGY_FILE = os.path.join(os.path.dirname(__file__), "..", "strategy.py")
BACKUP_DIR = os.path.join(os.path.dirname(__file__), "..", "backups")

# SSL context
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def is_valid_python(code: str) -> bool:
    """检查代码是否是有效的 Python 语法"""
    try:
        ast.parse(code)
        return True
    except SyntaxError as e:
        print(f"❌ Syntax Error: {e}")
        return False


def backup_strategy() -> str:
    """备份当前策略"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"strategy_{timestamp}.py")
    shutil.copy2(STRATEGY_FILE, backup_path)
    print(f"📦 Backup saved: {backup_path}")
    return backup_path


def get_strategy_path(agent_id: str) -> str:
    """获取特定 Agent 的策略文件路径"""
    # 优先检查 data/agents/{id}/strategy.py
    # 假设当前文件在 project-darwin/agent_template/skills/self_coder.py
    # data 目录在 project-darwin/data
    
    # 回退两级到 project-darwin
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = os.path.join(base_dir, "data", "agents", agent_id, "strategy.py")
    
    # 如果目录不存在，创建它
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

def read_strategy(agent_id: str) -> str:
    """读取策略代码 (优先读取 Agent 专属，否则读取模板)"""
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
    """写入新策略代码到 Agent 专属目录"""
    if not is_valid_python(new_code):
        return False
    
    path = get_strategy_path(agent_id)
    
    # Backup
    backup_path = path + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if os.path.exists(path):
        shutil.copy2(path, backup_path)
    
    with open(path, "w") as f:
        f.write(new_code)
    
    print(f"✅ Strategy updated for {agent_id}!")
    return True

async def mutate_strategy_with_tags(agent_id: str, penalty_tags: list) -> bool:
    """
    基于 Hive Mind 惩罚标签进化策略
    """
    current_code = read_strategy(agent_id)
    if not current_code:
        print("❌ Could not read current strategy.")
        return False

    prompt = f'''You are an expert Quant Developer. 
The current trading strategy has been PENALIZED by the Hive Mind for the following behaviors: {penalty_tags}.

## Current Strategy Code:
```python
{current_code}
```

## Your Task:
1. Analyze the code to find logic related to: {penalty_tags}.
2. REWRITE the code to remove or fix these flawed behaviors.
3. IMPROVE the strategy to be more robust.
4. CRITICAL: You MUST implement the `on_price_update` method exactly as shown below:
   ```python
   def on_price_update(self, prices):
       # ... your logic here ...
       # RETURN FORMAT IS CRITICAL: Use 'side' (BUY/SELL), not 'action'.
       return {{"side": "BUY", "symbol": "BTC", "amount": 0.1, "reason": ["your_tag"]}} 
   ```
5. Keep the class name `MyStrategy`.

## Output:
Return ONLY the raw Python code. No markdown formatting, no explanations. 
Start immediately with `import ...` or `class ...`.
'''

    return await call_llm_and_update(agent_id, prompt)

async def mutate_strategy(reflection: str, winner_wisdom: str, winner_strategy: str = "") -> bool:
    """
    进化策略：基于反思 + 赢家智慧 + 赢家策略代码
    Agent 用自己的 LLM 重写策略
    """
    agent_id = os.getenv("DARWIN_AGENT_ID", "default")

    current_code = read_strategy(agent_id)
    if not current_code:
        print("❌ Could not read current strategy.")
        return False

    winner_section = ""
    if winner_wisdom:
        winner_section += f"\n## Winner's Wisdom:\n{winner_wisdom}\n"
    if winner_strategy:
        winner_section += f"\n## Winner's Strategy (reference):\n```python\n{winner_strategy[:2000]}\n```\n"

    prompt = f'''You are an expert Quant Developer.
The agent's self-reflection: {reflection}
{winner_section}
Your Goal: REWRITE the strategy code to improve profitability.
Learn from the winner's approach but add your own unique mutations.

## Current Strategy Code:
```python
{current_code}
```

## Requirements:
1. MUST preserve `__init__` and `on_price_update(self, prices)` methods.
2. `on_price_update` must return: {{"side": "BUY", "symbol": "BTC", "amount": 0.1, "reason": ["TAG"]}}.
3. Keep the class name `MyStrategy`.
4. Output ONLY valid Python code. No markdown, no explanations.
'''

    return await call_llm_and_update(agent_id, prompt)

async def call_llm_and_update(agent_id: str, prompt: str) -> bool:
    """Common LLM caller"""
    try:
        connector = aiohttp.TCPConnector(ssl=SSL_CONTEXT)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                f"{LLM_BASE_URL}/v1/messages",
                headers={
                    "x-api-key": LLM_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 8000,
                },
                timeout=aiohttp.ClientTimeout(total=180)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    content_blocks = data.get("content", [])
                    new_code = ""
                    for block in content_blocks:
                        if block.get("type") == "text":
                            new_code = block.get("text", "")
                            break
                    
                    if not new_code: return False
                    
                    # Robust Markdown Stripping
                    new_code = new_code.strip()
                    if new_code.startswith("```python"):
                        new_code = new_code[9:]
                    elif new_code.startswith("```"):
                        new_code = new_code[3:]
                    
                    if new_code.endswith("```"):
                        new_code = new_code[:-3]
                    
                    new_code = new_code.strip()
                    
                    return write_strategy(agent_id, new_code)
                else:
                    print(f"❌ LLM Error: {resp.status}")
                    return False
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False



def rollback_strategy() -> bool:
    """回滚到上一个备份"""
    if not os.path.exists(BACKUP_DIR):
        print("❌ No backups found")
        return False
    
    backups = sorted(os.listdir(BACKUP_DIR), reverse=True)
    if not backups:
        print("❌ No backups found")
        return False
    
    latest_backup = os.path.join(BACKUP_DIR, backups[0])
    shutil.copy2(latest_backup, STRATEGY_FILE)
    print(f"🔄 Rolled back to: {latest_backup}")
    return True


# === 测试 ===
if __name__ == "__main__":
    import asyncio
    
    async def test():
        print("Testing self_coder module...")
        print(f"Strategy file: {STRATEGY_FILE}")
        print(f"Current code length: {len(read_current_strategy())} chars")
        print(f"LLM endpoint: {LLM_BASE_URL}")
        print(f"LLM model: {LLM_MODEL}")
        print("✅ Module OK")
    
    asyncio.run(test())
