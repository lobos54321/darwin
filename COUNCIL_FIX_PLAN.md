# Council Quality Fix Plan

## 问题诊断

### 当前问题（已确认）：
1. ❌ **消息截断严重**：6/7 消息不完整（"adhering to the [BREAKOUT] signal, which is currently printing a +6.47% expected value across the")
2. ❌ **缺乏数据支撑**：虽然 prompt 要求引用数据，但很多消息只是泛泛而谈
3. ❌ **评分系统失效**：所有消息都是 5.0 分（因为 LLM_ENABLED 可能为 False）
4. ❌ **没有真正辩论**：agents 虽然可以回应，但很少触发

### 根本原因：
1. **Gemini Flash 模型不稳定** - 经常在句子中间停止生成
2. **没有后处理验证** - 生成的内容直接发送，没有检查完整性
3. **Temperature 0.8 太高** - 导致输出随机性过大
4. **Council 评分依赖 LLM** - 如果 LLM 不可用，所有消息都是 5.0 分

## 修复方案

### Phase 1: 修复消息截断（最高优先级）

#### 1.1 添加完整性验证
```python
def validate_council_message(content: str) -> tuple[bool, str]:
    """
    验证 council 消息是否完整
    Returns: (is_valid, error_message)
    """
    # Remove emoji prefix
    text = content
    for emoji in ['🤓', '🐻', '🤖', '🦍', '🏆', '📝', '❓', '💡']:
        text = text.replace(emoji, '').strip()

    # Check 1: Must end with proper punctuation
    if not text.endswith(('.', '!', '?')):
        return False, "Message does not end with proper punctuation"

    # Check 2: Must have at least 2 complete sentences
    sentence_endings = text.count('.') + text.count('!') + text.count('?')
    if sentence_endings < 2:
        return False, f"Message has only {sentence_endings} sentence(s), need at least 2"

    # Check 3: Must be at least 20 words
    word_count = len(text.split())
    if word_count < 20:
        return False, f"Message too short ({word_count} words), need at least 20"

    # Check 4: Must not exceed 150 words (prevent rambling)
    if word_count > 150:
        return False, f"Message too long ({word_count} words), max 150"

    return True, ""
```

#### 1.2 修改 agent.py 的 participate_council
```python
# After LLM call
llm_content = await self._call_llm(prompt, max_tokens=1024)

if llm_content:
    final_content = f"{persona['emoji']} {llm_content}"

    # VALIDATION: Check if message is complete
    is_valid, error = validate_council_message(final_content)

    if not is_valid:
        print(f"⚠️ Council message validation failed: {error}")
        print(f"   Raw output: {final_content}")

        # Retry with stricter prompt
        retry_prompt = f"""{prompt}

CRITICAL: Your previous response was incomplete: "{llm_content}"

You MUST:
1. Write EXACTLY 2-4 complete sentences
2. Every sentence MUST end with . ! or ?
3. Do NOT stop mid-sentence
4. Keep it under 150 words

Try again:"""

        llm_content = await self._call_llm(retry_prompt, max_tokens=1024)
        final_content = f"{persona['emoji']} {llm_content}"

        is_valid, error = validate_council_message(final_content)
        if not is_valid:
            print(f"❌ Retry failed: {error}. Using fallback.")
            # Fallback to strategy-generated message
            final_content = self._generate_persona_message(
                strategy_info or "Market analysis in progress.",
                role
            )
```

#### 1.3 降低 Temperature
```python
# In _call_llm method
payload = {
    "model": LLM_MODEL,
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": max_tokens,
    "temperature": 0.3  # Changed from 0.8 to 0.3 for more stable output
}
```

### Phase 2: 改进评分系统

#### 2.1 基于规则的评分（不依赖 LLM）
```python
def score_council_message_rule_based(content: str, briefing: dict) -> float:
    """
    Rule-based scoring (fallback when LLM unavailable)
    """
    score = 5.0  # Base score

    # Remove emoji
    text = content
    for emoji in ['🤓', '🐻', '🤖', '🦍', '🏆', '📝', '❓', '💡']:
        text = text.replace(emoji, '').strip()

    # +2 points: References specific numbers
    if any(char.isdigit() for char in text):
        numbers = re.findall(r'[-+]?\d*\.?\d+%?', text)
        if len(numbers) >= 2:
            score += 2.0

    # +1 point: References specific tokens
    tokens = ['CLANKER', 'WETH', 'LOB', 'MOLT', 'PEPE', 'SOL', 'BTC', 'ETH']
    token_mentions = sum(1 for token in tokens if token in text.upper())
    if token_mentions >= 1:
        score += 1.0

    # +1 point: References strategy tags
    tags = ['BREAKOUT', 'DIP_BUY', 'MEAN_REVERSION', 'MOMENTUM', 'RSI', 'MACD']
    tag_mentions = sum(1 for tag in tags if tag in text.upper())
    if tag_mentions >= 1:
        score += 1.0

    # +1 point: Asks a question (encourages discussion)
    if '?' in text:
        score += 1.0

    # -2 points: Too short
    word_count = len(text.split())
    if word_count < 20:
        score -= 2.0

    # -1 point: Generic phrases
    generic_phrases = ['good job', 'congrats', 'nice work', 'well done', 'great trade']
    if any(phrase in text.lower() for phrase in generic_phrases):
        score -= 1.0

    return max(0, min(10, score))
```

#### 2.2 修改 council.py 的 _score_message
```python
async def _score_message(self, message: CouncilMessage, session: CouncilSession) -> float:
    """用 LLM 评分消息质量 (如果 LLM 可用)，否则用规则评分"""
    from config import LLM_ENABLED

    # 如果 LLM 未启用，使用规则评分
    if not LLM_ENABLED:
        return score_council_message_rule_based(message.content, {})

    # ... existing LLM scoring code ...

    # If LLM fails, fallback to rule-based
    return score_council_message_rule_based(message.content, {})
```

### Phase 3: 强化数据驱动

#### 3.1 在 prompt 中注入更多具体数据
```python
# In participate_council, enhance briefing with concrete examples
briefing_enhanced = f"""{briefing}

CONCRETE DATA YOU MUST REFERENCE:
- Winner's PnL: {council_data.get('winner_pnl', 'N/A')}%
- Your PnL: {self.my_pnl}%
- Top performing tag: {council_data.get('top_tag', 'N/A')} ({council_data.get('top_tag_winrate', 'N/A')}% win rate)
- Worst performing tag: {council_data.get('worst_tag', 'N/A')} ({council_data.get('worst_tag_winrate', 'N/A')}% win rate)

EXAMPLE GOOD MESSAGE:
"The `BREAKOUT` tag is crushing it with 68% win rate across 12 trades, while `DIP_BUY` is bleeding at 32% over 8 trades. I'm switching to momentum-based entries because the current market is clearly trending, not mean-reverting."

EXAMPLE BAD MESSAGE:
"Market looks interesting. I think we should be careful."

Your message:"""
```

### Phase 4: 启用真正的辩论

#### 4.1 提高回应概率
```python
# In _consider_council_response
# Current: only responds if score is high or message is controversial
# New: respond more frequently to create discussion

# Change decision threshold
decide_prompt = f"""...
Do you have a SPECIFIC counter-argument, data-driven addition, or evidence-based challenge to add?

Consider responding if:
- You have contradicting data
- You tried the same strategy and got different results
- You see a flaw in their reasoning
- You have a follow-up question

Reply with ONLY "RESPOND" or "SILENT"."""

# Increase response rate by lowering the bar
```

## 实施顺序

1. **今天（2小时）**：
   - ✅ 添加 validate_council_message
   - ✅ 修改 participate_council 添加重试逻辑
   - ✅ 降低 temperature 到 0.3
   - ✅ 添加 rule-based scoring

2. **明天（1小时）**：
   - ✅ 增强 briefing 数据
   - ✅ 测试并调整评分权重

3. **后天（1小时）**：
   - ✅ 提高回应概率
   - ✅ 观察 council 质量改善

## 成功指标

修复后，Council 应该达到：
- ✅ 95%+ 消息完整（以标点符号结尾）
- ✅ 平均消息长度 30-80 词
- ✅ 80%+ 消息引用具体数据（数字、token 名称、策略标签）
- ✅ 评分分布：0-3分 (10%), 4-6分 (40%), 7-10分 (50%)
- ✅ 每个 epoch 至少 3 轮对话（不只是独白）
