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


def read_current_strategy() -> str:
    """读取当前策略代码"""
    with open(STRATEGY_FILE, "r") as f:
        return f.read()


def write_strategy(new_code: str) -> bool:
    """写入新策略代码"""
    if not is_valid_python(new_code):
        return False
    
    backup_strategy()
    
    with open(STRATEGY_FILE, "w") as f:
        f.write(new_code)
    
    print(f"✅ Strategy updated!")
    return True


def build_mutation_prompt(current_code: str, reflection: str, winner_wisdom: str) -> str:
    """构建 mutation prompt"""
    return f'''你是一个专业的量化交易策略开发者。你需要改进以下 Python 策略代码。

## 当前策略代码:
```python
{current_code}
```

## Agent 的自我反思:
{reflection}

## 赢家的策略分享:
{winner_wisdom}

## 你的任务:
1. 分析当前策略的问题
2. 参考赢家的思路
3. 重写 on_price_update 方法来改进策略
4. 可以调整参数 (risk_level, momentum_threshold, stop_loss, take_profit)
5. 可以添加新的逻辑

## 要求:
- 保持类结构不变 (DarwinStrategy)
- 保持所有方法签名不变
- 代码必须是有效的 Python
- 添加注释说明改进点

## 输出:
只输出完整的 Python 代码，不要其他解释。以三引号开始的文档字符串开头。'''


async def mutate_strategy(reflection: str, winner_wisdom: str) -> bool:
    """
    核心进化函数: 让 LLM 基于反思和赢家智慧重写策略
    使用 Anthropic Messages API 格式
    """
    
    current_code = read_current_strategy()
    prompt = build_mutation_prompt(current_code, reflection, winner_wisdom)

    try:
        connector = aiohttp.TCPConnector(ssl=SSL_CONTEXT)
        async with aiohttp.ClientSession(connector=connector) as session:
            # 使用 Anthropic Messages API
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
                    
                    # 提取内容 (Anthropic 格式)
                    content_blocks = data.get("content", [])
                    new_code = ""
                    for block in content_blocks:
                        if block.get("type") == "text":
                            new_code = block.get("text", "")
                            break
                    
                    if not new_code:
                        print("❌ No text content in response")
                        return False
                    
                    # 清理代码 (移除 markdown 标记)
                    if "```python" in new_code:
                        new_code = new_code.split("```python")[1].split("```")[0]
                    elif "```" in new_code:
                        parts = new_code.split("```")
                        if len(parts) >= 2:
                            new_code = parts[1]
                    
                    new_code = new_code.strip()
                    
                    # 验证并写入
                    if write_strategy(new_code):
                        print("🧬 Mutation successful! Strategy evolved.")
                        return True
                    else:
                        print("❌ Mutation failed: Invalid code generated")
                        return False
                else:
                    error_text = await resp.text()
                    print(f"❌ LLM API error: {resp.status} - {error_text[:200]}")
                    return False
                    
    except Exception as e:
        print(f"❌ Mutation error: {e}")
        import traceback
        traceback.print_exc()
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
