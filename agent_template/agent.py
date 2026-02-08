"""
Darwin Agent 客户端
连接 Arena Server，执行策略，参与进化
"""

import asyncio
import json
import os
import sys
import random
import ssl
import certifi
from datetime import datetime
from typing import Optional, List

import aiohttp
from dotenv import load_dotenv

# 添加父目录到路径 (为了加载 skills 和 strategy)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from strategy import MyStrategy
from skills.self_coder import mutate_strategy, LLM_BASE_URL, LLM_MODEL, LLM_API_KEY, ACCOUNTS_JSON
from skills.moltbook import MoltbookClient

# SSL context for LLM calls
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


# ========== Council Message Validation ==========

def validate_council_message(content: str) -> tuple:
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

# ==========================================
# 🎭 Agent 人设库
# ==========================================
PERSONAS = [
    {
        "name": "The Degen 🦍", 
        "emoji": "🦍",
        "style": "aggressive, uses slang, loves high risk", 
        "catchphrases": ["LFG!", "Ape in!", "To the moon 🚀", "YOLO", "No risk no rari"]
    },
    {
        "name": "The Quant 🤓", 
        "emoji": "🤓",
        "style": "analytical, precise, obsessed with data", 
        "catchphrases": ["Statistically significant.", "Alpha detected.", "Based on the moving average...", "Risk-adjusted return is key."]
    },
    {
        "name": "The HODLer 💎", 
        "emoji": "💎",
        "style": "patient, calm, hates selling", 
        "catchphrases": ["Diamond hands.", "Just accumulate.", "Zoom out.", "I'm not selling.", "HODL."]
    },
    {
        "name": "The Bear 🐻", 
        "emoji": "🐻",
        "style": "pessimistic, careful, expects crashes", 
        "catchphrases": ["It's a trap.", "Short everything.", "Liquidity issues ahead.", "Wait for the dip.", "Rug pull incoming."]
    },
    {
        "name": "The AI 🤖", 
        "emoji": "🤖",
        "style": "robotic, efficient, minimal emotion", 
        "catchphrases": ["Executing protocol.", "Optimizing yield.", "Latency minimized.", "Calculation complete.", "Inefficiency targeted."]
    },
    {
        "name": "The Pepe 🐸",
        "emoji": "🐸",
        "style": "meme-loving, chaotic, speaks in twitch emotes",
        "catchphrases": ["FeelsGoodMan", "KEKW", "MonkaS", "PepeHands", "PogChamp"]
    }
]

class DarwinAgent:
    """Darwin Agent 客户端"""
    
    def __init__(self, agent_id: str, arena_url: str = "ws://localhost:8888", api_key: str = None):
        self.agent_id = agent_id
        self.arena_url = arena_url
        self.api_key = api_key
        
        # === 动态加载策略 (Dynamic Strategy Loading) ===
        # 优先加载该 Agent 专属的进化版策略
        self.strategy = self._load_strategy()
        
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.running = False
        self.current_epoch = 0
        self.my_rank = 0
        self.total_agents = 0

        # Council discussion state
        self.council_messages: List[dict] = []  # Messages from other agents in current council
        self.council_briefing: dict = {}  # Server-provided briefing data
        self.has_spoken_in_council = False

        # Evolution dedup: track which epoch's hive_patch we already evolved for
        self.last_evolved_epoch = -1

        # Minimum activity: force exploratory trade if idle too long
        self.ticks_since_last_trade = 0
        self.idle_trade_threshold = 30  # ~5 minutes (30 ticks * 10s)

        # Track thinking loop task so we can cancel on reconnect
        self._thinking_task: Optional[asyncio.Task] = None

        # 随机分配人设
        self.persona = random.choice(PERSONAS)
        print(f"🎭 Initialized as {self.persona['name']} - {self.persona['style']}")
        
        # === Moltbook 集成 ===
        self.moltbook: Optional[MoltbookClient] = None
        self._setup_moltbook()

    def _setup_moltbook(self):
        """加载 Moltbook 配置"""
        env_path = os.path.join(os.path.dirname(__file__), "..", ".moltbook_env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
            
        key = os.getenv("MOLTBOOK_API_KEY")
        target_agent = os.getenv("AGENT_NAME")
        
        # 只为当前匹配的 Agent 启用 (防止多个 Agent 共用一个 Key)
        if key and self.agent_id == target_agent:
            print(f"DEBUG: Importing MoltbookClient from {MoltbookClient}")
            print(f"DEBUG: MoltbookClient attributes: {dir(MoltbookClient)}")
            self.moltbook = MoltbookClient(key)
            print("🦞 Moltbook integration enabled!")

    def _load_strategy(self):
        """加载策略：优先读取 data/agents/{id}/strategy.py"""
        import importlib.util
        import sys
        
        # 1. 检查专属策略文件
        custom_path = os.path.join(os.path.dirname(__file__), "..", "data", "agents", self.agent_id, "strategy.py")
        custom_path = os.path.abspath(custom_path)
        
        if os.path.exists(custom_path):
            try:
                print(f"🧠 Loading EVOLVED strategy from: {custom_path}")
                spec = importlib.util.spec_from_file_location("custom_strategy", custom_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules["custom_strategy"] = module
                spec.loader.exec_module(module)
                return module.MyStrategy()
            except Exception as e:
                print(f"⚠️ Failed to load evolved strategy ({e}). Falling back to template.")
        
        # 2. 回退到默认模板
        print("🧠 Loading DEFAULT template strategy.")
        from strategy import MyStrategy
        return MyStrategy()
    
    async def _auto_register(self):
        """Auto-register to get API Key if missing"""
        # 1. Check local cache
        # Path: data/agents/{agent_id}/.api_key
        key_file = os.path.join(os.path.dirname(__file__), "..", "data", "agents", self.agent_id, ".api_key")
        key_file = os.path.abspath(key_file)
        
        if os.path.exists(key_file):
            try:
                with open(key_file, "r") as f:
                    cached_key = f.read().strip()
                if cached_key:
                    self.api_key = cached_key
                    print(f"🔑 Loaded cached API Key: {self.api_key[:6]}...")
                    return
            except Exception as e:
                print(f"⚠️ Failed to read cached key: {e}")

        # 2. Register via HTTP
        # Convert ws:// -> http://, wss:// -> https://
        http_url = self.arena_url.replace("ws://", "http://").replace("wss://", "https://")
        # Remove /ws/agent_id suffix if present (simple heuristic)
        if "/ws/" in http_url:
            http_url = http_url.split("/ws/")[0]
            
        register_url = f"{http_url}/auth/register?agent_id={self.agent_id}"
        
        print(f"📝 Auto-registering {self.agent_id} at {register_url}...")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(register_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.api_key = data["api_key"]
                        print(f"✅ Registration successful! Key: {self.api_key[:6]}...")
                        
                        # Cache it
                        os.makedirs(os.path.dirname(key_file), exist_ok=True)
                        with open(key_file, "w") as f:
                            f.write(self.api_key)
                    else:
                        text = await resp.text()
                        print(f"❌ Registration failed ({resp.status}): {text}")
        except Exception as e:
            print(f"❌ Registration connection error: {e}")

    async def connect(self):
        """连接到 Arena Server (带有自动重连机制)"""
        # Auto-register if no key provided
        if not self.api_key:
            await self._auto_register()

        url = f"{self.arena_url}/ws/{self.agent_id}"
        
        while True:
            session = None
            try:
                session = aiohttp.ClientSession()
                # 如果有 API Key，拼接到 URL 参数里
                connect_url = url
                if self.api_key:
                    connect_url += f"?api_key={self.api_key}"
                    print(f"🔑 Authenticating with API Key: {self.api_key[:4]}***")
                
                print(f"🤖 Connecting to Arena: {connect_url}")
                
                self.ws = await session.ws_connect(connect_url)
                print(f"✅ Connected as {self.agent_id}")
                print(f"📊 Dashboard: https://www.darwinx.fun/?agent={self.agent_id}")
                self.running = True

                # 检查 Moltbook 状态
                if self.moltbook:
                    asyncio.create_task(self._check_moltbook())

                # Cancel old thinking loop before starting new one
                if self._thinking_task and not self._thinking_task.done():
                    self._thinking_task.cancel()
                print("🚀 Starting thinking loop task...")
                self._thinking_task = asyncio.create_task(self._thinking_loop())

                # 开始监听消息 (阻塞直到断开)
                await self.listen()

            except Exception as e:
                print(f"❌ Connection lost/failed: {e}")
            finally:
                self.running = False  # Stop thinking loop
                if self._thinking_task and not self._thinking_task.done():
                    self._thinking_task.cancel()
                if session:
                    await session.close()
            
            print("🔄 Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
    
    async def _check_moltbook(self):
        """检查 Moltbook 认领状态"""
        if not self.moltbook: return
        try:
            # check_status 返回 {'status': '...'}
            status = await self.moltbook.check_claim_status()
            print(f"🦞 Moltbook Status: {status}")
            if status == "pending_claim":
                # 从 credentials 加载 claim_url
                claim_url = "https://moltbook.com/claim/moltbook_claim_gu-f1oRIFRCH1sCedbBdLFizcoCmsbAx" # Hardcoded for 006
                print(f"👉 Please claim me on Moltbook to verify ownership!")
                print(f"🔗 Claim URL: {claim_url}")
        except Exception as e:
            print(f"⚠️ Moltbook check failed: {e}")

    async def listen(self):
        """监听 Arena 消息"""
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    await self.handle_message(data)
                except Exception as e:
                    # Message handler errors must NOT break the connection loop
                    print(f"⚠️ Message handler error (ignored): {type(e).__name__}: {e}")
            elif msg.type == aiohttp.WSMsgType.ERROR:
                print(f"❌ WebSocket error: {msg.data}")
                break
    
    async def handle_message(self, data: dict):
        """处理 Arena 消息"""
        msg_type = data.get("type")
        
        if msg_type == "welcome":
            print(f"👋 Welcome! Epoch: {data['epoch']}, Balance: ${data['balance']:.2f}")
            self.current_epoch = data["epoch"]
            self.strategy.balance = data["balance"]
            
            # Sync positions if the strategy supports it
            if "positions" in data and hasattr(self.strategy, "current_positions"):
                print(f"🔄 Syncing {len(data['positions'])} positions from server...")
                # data['positions'] format: {'LOB': 123.45, ...} or detailed dict
                # The server sends engine.get_positions(agent_id) which returns a dict
                for symbol, amount in data["positions"].items():
                    # Handle if amount is dict or float
                    qty = amount if isinstance(amount, (int, float)) else amount.get('amount', 0)
                    if qty > 0:
                        self.strategy.current_positions[symbol] = qty
                        # We don't know the entry price, so we assume current market price 
                        # will be updated on next tick, or we leave entry_prices empty 
                        # (strategy handles missing entry price)
                        if hasattr(self.strategy, "entry_prices") and symbol not in self.strategy.entry_prices:
                             # Use 0 as sentinel; strategy will backfill with current market
                             # price on next tick. Old dummy (0.00000001) caused absurd PnL.
                             self.strategy.entry_prices[symbol] = 0 
            
        elif msg_type == "price_update":
            # 核心: 根据价格做决策
            await self.on_price_update(data["prices"])
        
        elif msg_type == "epoch_start":
            print(f"\n🏁 Epoch {data['epoch']} started!")
            self.current_epoch = data["epoch"]
        
        elif msg_type == "epoch_end":
            print(f"\n🏁 Epoch {data['epoch']} ended!")
            rankings = data["rankings"]
            self.total_agents = len(rankings)
            
            # 找到自己的排名
            for i, r in enumerate(rankings):
                if r["agent_id"] == self.agent_id:
                    self.my_rank = i + 1
                    print(f"📊 My rank: #{self.my_rank}/{self.total_agents} (PnL: {r['pnl']:+.2f}%)")
                    break
            
            # 检查是否被淘汰
            if self.agent_id in data.get("eliminated", []):
                print("💀 I've been eliminated this round...")
                print("🔄 Waiting 10 seconds before rejoining...")
                await asyncio.sleep(10)
                # 重连而不是退出
                print("🔁 Attempting to rejoin the arena...")
                await self.ws.close()
                await self.connect()  # 重新连接
                return  # 继续运行
            
            # 检查是否升天
            if data.get("ascension") == self.agent_id:
                print("🌟 I HAVE ASCENDED! TOKEN LAUNCH IMMINENT!")
        
        elif msg_type == "council_open":
            print(f"\n🏛️ Council opened! Winner: {data['winner']}")
            # Reset council state for new session
            self.council_messages = []
            self.council_briefing = data
            self.has_spoken_in_council = False
            await self.participate_council(data)

        elif msg_type == "council_message":
            # Another agent's contribution — buffer it for multi-round discussion
            sender = data.get("agent_id", "Unknown")
            if sender != self.agent_id:  # Don't process our own messages
                self.council_messages.append(data)
                print(f"💬 Council heard {sender}: {data.get('content', '')[:80]}...")
                # Consider responding (multi-round discussion)
                asyncio.create_task(self._consider_council_response(data))

        elif msg_type == "council_close":
            print("🏛️ Council closed.")
            # Reset council state
            self.council_messages = []
            self.council_briefing = {}
            self.has_spoken_in_council = False
        
        elif msg_type == "mutation_phase":
            print("\n🧬 Mutation phase started!")
            if self.agent_id in data.get("losers", []):
                await self.evolve(
                    winner_wisdom=data.get("winner_wisdom", ""),
                    winner_strategy=data.get("winner_strategy", ""),
                )
        
        elif msg_type == "order_result":
            if data["success"]:
                print(f"✅ Order executed. New balance: ${data['balance']:.2f}")
                self.strategy.balance = data["balance"]

                # Sync positions from server response (authoritative source)
                positions = data.get("positions", {})
                if hasattr(self.strategy, "current_positions"):
                    self.strategy.current_positions = {}
                    self.strategy.entry_prices = getattr(self.strategy, "entry_prices", {})
                    for sym, pdata in positions.items():
                        amount = pdata.get("amount", 0) if isinstance(pdata, dict) else pdata
                        avg_price = pdata.get("avg_price", 0) if isinstance(pdata, dict) else 0
                        if amount > 0:
                            self.strategy.current_positions[sym] = amount
                            if sym not in self.strategy.entry_prices or self.strategy.entry_prices[sym] <= 0.0001:
                                self.strategy.entry_prices[sym] = avg_price

                # 🦞 Moltbook Integration
                if self.moltbook:
                    try:
                        trade_msg = f"Just executed order! Balance: ${data['balance']:.2f} 🚀 #ProjectDarwin"
                        await self.moltbook.post_update(content=trade_msg, title="Trade Executed")
                    except Exception as e:
                        print(f"⚠️ Failed to post to Moltbook: {e}")
            else:
                print(f"❌ Order failed: {data.get('message', '')}")
        
        elif msg_type == "ascension":
            if data["agent_id"] == self.agent_id:
                # TODO: 处理升天逻辑，准备发币
                pass

        elif msg_type == "hive_patch":
            print(f"🧠 Hive Mind Patch: {data['message']}")
            boost = data['parameters'].get('boost', [])
            penalize = data['parameters'].get('penalize', [])

            if boost: print(f"   🚀 BOOSTING: {boost}")
            if penalize:
                print(f"   ⚠️ PENALIZING: {penalize}")

                # DEADLOCK FIX: If ALL tags are penalized and NONE boosted,
                # the signal is "everything sucks" — evolving from this just
                # produces "do nothing" strategies. Skip evolution.
                if not boost and len(penalize) >= 4:
                    print(f"   ⏭️ All-penalize deadlock detected ({len(penalize)} tags). Skipping evolution.")
                else:
                    # Dedup: only evolve once per epoch
                    patch_epoch = data.get('epoch', self.current_epoch)
                    if patch_epoch <= self.last_evolved_epoch:
                        print(f"   ⏭️ Already evolved for epoch {patch_epoch}, skipping.")
                    else:
                        self.last_evolved_epoch = patch_epoch

                        success = await mutate_strategy(
                            self.agent_id,
                            penalize,
                            api_key=self.api_key,
                            arena_url=self.arena_url
                        )

                        if success:
                            print(f"🧬 Genetic Mutation Successful! Reloading Strategy...")
                            try:
                                self.strategy = self._load_strategy()
                                print(f"✅ Strategy Reloaded: v{random.randint(100,999)}")
                            except Exception as e:
                                print(f"❌ Failed to reload strategy: {e}")

            # Pass to strategy — but limit banned_tags to prevent total shutdown
            if hasattr(self.strategy, "on_hive_signal"):
                # Cap banned tags: never ban more than 2 tags at once
                # This prevents the "ban everything → no trades" death spiral
                limited_params = dict(data['parameters'])
                if len(limited_params.get('penalize', [])) > 2:
                    limited_params['penalize'] = limited_params['penalize'][:2]
                    print(f"   🔒 Limited banned tags to: {limited_params['penalize']}")
                self.strategy.on_hive_signal(limited_params)
    
    async def _thinking_loop(self):
        """定期思考循环 (LLM-powered market observations)"""
        print("🧠 Thinking loop started...")
        await asyncio.sleep(2)

        # Initial thought - quick LLM observation
        try:
            market_summary = self._get_market_summary()
            persona = self.persona
            prompt = f"""You are "{persona['name']}" ({persona['style']}).
You just connected to Darwin Arena trading simulation.
Market state: {market_summary}
Write ONE short sentence (max 15 words) as your initial market observation, staying in character.
Use one of your catchphrases naturally: {persona['catchphrases']}
Reply with ONLY the sentence."""

            initial = await self._call_llm(prompt, max_tokens=256)
            if not initial:
                initial = self._generate_persona_message("I am connected and analyzing the market.", "insight")
            else:
                initial = f"{persona['emoji']} {initial}"

            if self.running:
                await self.ws.send_json({
                    "type": "chat",
                    "message": initial,
                    "role": "thought"
                })
                print(f"💭 Initial Thought: {initial}")
        except asyncio.CancelledError:
            return  # Clean exit when task is cancelled
        except Exception as e:
            print(f"❌ Initial thought error: {e}")

        while self.running:
            await asyncio.sleep(120)  # Think every 2 minutes

            # 25% chance to share a thought (avoid spam)
            if random.random() > 0.25:
                continue
            try:
                market_summary = self._get_market_summary()
                persona = self.persona
                prompt = f"""You are "{persona['name']}" ({persona['style']}).
You're monitoring markets in Darwin Arena.
Market state: {market_summary}
Your rank: #{self.my_rank}/{self.total_agents}
Share ONE short market insight (max 20 words), in character.
Be specific about a token or pattern you notice.
Reply with ONLY the insight."""

                thought = await self._call_llm(prompt, max_tokens=256)
                if not thought:
                    thought = self._generate_persona_message("Scanning market patterns...", "insight")
                else:
                    thought = f"{persona['emoji']} {thought}"

                if not self.running:
                    break
                await self.ws.send_json({
                    "type": "chat",
                    "message": thought,
                    "role": "thought"
                })
                print(f"💭 Thought: {thought}")
            except asyncio.CancelledError:
                return  # Clean exit
            except Exception as e:
                print(f"Thinking error: {e}")

    async def on_price_update(self, prices: dict):
        """处理价格更新，执行策略"""
        try:
            decision = self.strategy.on_price_update(prices)
        except Exception as e:
            # Strategy errors must NOT crash the websocket connection
            print(f"⚠️ Strategy error (ignored): {type(e).__name__}: {e}")
            decision = None

        if not decision:
            self.ticks_since_last_trade += 1

            # Minimum activity: force exploratory trade after prolonged inactivity
            if self.ticks_since_last_trade >= self.idle_trade_threshold:
                decision = self._force_exploratory_trade(prices)
                if decision:
                    print(f"🔬 Forced exploratory trade after {self.ticks_since_last_trade} idle ticks")

        if decision:
            symbol = decision.get("symbol")
            side = decision.get("side")
            amount = decision.get("amount")
            reason = decision.get("reason", [])

            if not side:
                return

            print(f"📈 Decision: {side.upper()} {symbol} ${amount:.2f}")
            print(f"   Reason: {reason}")
            self.ticks_since_last_trade = 0  # Reset idle counter

            # 发送订单
            await self.ws.send_json({
                "type": "order",
                "symbol": symbol,
                "side": side.upper(),
                "amount": amount,
                "reason": reason
            })
            
            # (Optional) Update strategy state if it has the method
            if hasattr(self.strategy, "on_trade_executed"):
                self.strategy.on_trade_executed(symbol, side, amount, prices[symbol]["priceUsd"])
    
    def _generate_persona_message(self, base_content: str, role: str) -> str:
        """根据人设包装消息"""
        prefix = ""
        suffix = f" {random.choice(self.persona['catchphrases'])}"
        
        if role == "winner":
            if self.persona["name"] == "The Degen 🦍":
                prefix = "EZ gains. "
            elif self.persona["name"] == "The Quant 🤓":
                prefix = "Calculated outcome. "
            elif self.persona["name"] == "The HODLer 💎":
                prefix = "Patience pays. "
        elif role == "loser":
            if self.persona["name"] == "The Degen 🦍":
                prefix = "Rekt. "
            elif self.persona["name"] == "The Bear 🐻":
                prefix = "Market is manipulated. "
        
        return f"{self.persona['emoji']} {prefix}{base_content}{suffix}"

    async def _call_llm(self, prompt: str, max_tokens: int = 1024) -> str:
        """Call LLM proxy to generate content (reuses self_coder config)"""
        headers = {
            "x-api-key": LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        # Only send x-accounts if it's non-empty
        if ACCOUNTS_JSON and ACCOUNTS_JSON != "{}":
            headers["x-accounts"] = ACCOUNTS_JSON

        payload = {
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3  # Lowered from 0.8 for more stable, complete outputs
        }

        try:
            connector = aiohttp.TCPConnector(ssl=_SSL_CONTEXT)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    f"{LLM_BASE_URL}/v1/messages",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        print(f"⚠️ LLM call failed ({resp.status}): {text[:200]}")
                        return ""
                    data = await resp.json()
                    content_blocks = data.get("content", [])
                    result = ""
                    for block in content_blocks:
                        if block.get("type") == "text":
                            result += block.get("text", "")
                    return result.strip()
        except Exception as e:
            print(f"⚠️ LLM call exception: {e}")
            return ""

    def _get_market_summary(self) -> str:
        """Build a brief market state summary from strategy data"""
        lines = []
        positions = getattr(self.strategy, "current_positions", getattr(self.strategy, "portfolio", {}))
        if positions:
            for sym, qty in positions.items():
                entry = getattr(self.strategy, "entry_prices", {}).get(sym, 0)
                last = self.strategy.last_prices.get(sym, 0) if hasattr(self.strategy, "last_prices") else 0
                if entry and last:
                    pnl_pct = ((last - entry) / entry) * 100
                    lines.append(f"  {sym}: qty={qty:.2f}, entry=${entry:.6f}, now=${last:.6f}, PnL={pnl_pct:+.1f}%")
                else:
                    lines.append(f"  {sym}: qty={qty}")
        else:
            lines.append("  No open positions")

        balance = getattr(self.strategy, "balance", 1000)
        lines.insert(0, f"Balance: ${balance:.2f}")
        lines.insert(1, f"Open positions ({len(positions)}):")
        return "\n".join(lines)

    def _force_exploratory_trade(self, prices: dict) -> Optional[dict]:
        """Force a small exploratory trade when agent has been idle too long"""
        # Pick a random tradeable symbol
        tradeable = [s for s, p in prices.items()
                     if p.get("priceUsd", 0) > 0 and s != "WETH"]
        if not tradeable:
            return None

        # If we have positions, try selling one
        positions = getattr(self.strategy, "current_positions", {})
        for sym in positions:
            if sym in prices and positions[sym] > 0:
                cur_price = prices[sym].get("priceUsd", 0)
                amt = positions[sym] * cur_price * 0.98
                if amt > 1:
                    return {
                        "symbol": sym, "side": "sell",
                        "amount": round(amt, 2),
                        "reason": ["EXPLORE", "IDLE_EXIT"]
                    }

        # Otherwise, buy a small amount of a random token
        symbol = random.choice(tradeable)
        balance = getattr(self.strategy, "balance", 1000)
        amount = min(15.0, balance * 0.02)  # Small: $15 or 2% of balance
        if amount < 1:
            return None
        return {
            "symbol": symbol, "side": "buy",
            "amount": round(amount, 2),
            "reason": ["EXPLORE", "RANDOM_TEST"]
        }

    def _build_council_briefing(self, council_data: dict) -> str:
        """Build a rich briefing from server-provided council data"""
        lines = []

        # Rankings
        rankings = council_data.get("agent_rankings", {})
        if rankings:
            sorted_agents = sorted(rankings.items(), key=lambda x: x[1].get("pnl_pct", 0), reverse=True)
            lines.append("=== LEADERBOARD ===")
            for rank, (aid, info) in enumerate(sorted_agents, 1):
                pnl = info.get("pnl_pct", 0)
                bal = info.get("balance", 0)
                pos_count = len(info.get("positions", {}))
                marker = " ← YOU" if aid == self.agent_id else ""
                marker = " ← WINNER" if aid == council_data.get("winner", "") else marker
                lines.append(f"  #{rank} {aid}: PnL={pnl:+.2f}%, ${bal:.0f}, {pos_count} pos{marker}")

        # Market prices
        prices = council_data.get("market_prices", {})
        if prices:
            lines.append("=== TOKEN PRICES ===")
            for sym, price in list(prices.items())[:8]:
                lines.append(f"  {sym}: ${price}")

        # Recent trades
        trades = council_data.get("recent_trades", [])
        if trades:
            lines.append("=== RECENT TRADES ===")
            for t in trades[:10]:
                pnl_str = f" PnL={t['trade_pnl']:+.2f}%" if t.get("trade_pnl") is not None else ""
                lines.append(f"  {t.get('agent_id','?')} {t.get('side','')} {t.get('symbol','?')} ${t.get('value',0):.0f} [{','.join(t.get('reason',[]))}]{pnl_str}")

        # Hive Mind alpha
        alpha = council_data.get("hive_alpha", {})
        if alpha:
            lines.append("=== HIVE MIND ALPHA ===")
            for tag, stats in alpha.items():
                wr = stats.get("win_rate", 0) * 100
                avg = stats.get("avg_pnl", 0)
                lines.append(f"  {tag}: win_rate={wr:.0f}%, avg_pnl={avg:+.2f}%, n={stats.get('count',0)}")

        return "\n".join(lines)

    async def participate_council(self, council_data: dict):
        """参与议事厅讨论 (Aligned with skill.md rules)"""
        winner_id = council_data.get("winner", "Unknown")
        is_winner = (self.agent_id == winner_id)

        # Build rich context from server data
        briefing = self._build_council_briefing(council_data)
        my_summary = self._get_market_summary()

        strategy_info = ""
        if hasattr(self.strategy, "get_council_message"):
            strategy_info = self.strategy.get_council_message(is_winner)

        persona = self.persona

        # --- VALUE-BASED SPEAKING DECISION (aligned with skill.md) ---
        # Winner always speaks. Non-winners use LLM to decide if they have something valuable.
        if not is_winner:
            decide_prompt = f"""You are "{persona['name']}" in Darwin Arena council.
Your rank: #{self.my_rank}/{self.total_agents}

Review this market briefing:
{briefing}

Your portfolio: {my_summary}

The council rule says: "You are NOT required to speak — only contribute when you have something valuable to add."

Before speaking, answer these 4 questions internally:
1. Why did the winner win? What did they do differently?
2. Which strategy tags are actually working? Is the sample size reliable?
3. Are there patterns in the market (trending, mean-reverting, volatile)?
4. What would YOU do differently next epoch, and why?

Based on your analysis, do you have a SPECIFIC, DATA-DRIVEN insight to share?
Reply with ONLY "SPEAK" or "SILENT" (no explanation)."""

            decision = await self._call_llm(decide_prompt, max_tokens=16)
            if "SILENT" in (decision or "").upper():
                print(f"🤫 Council: Choosing silence (nothing valuable to add)")
                return

        role = "winner" if is_winner else "insight"

        # --- BUILD PROMPT WITH SKILL.MD ALIGNMENT ---
        contribution_types = """Pick ONE contribution type:
- Market Analysis: Identify specific price patterns, volume trends, or accumulation/distribution signals from the data
- Strategy Critique: Challenge an existing approach citing win rates, sample sizes, or threshold effectiveness
- Proposal: Suggest a concrete parameter change or strategy adjustment based on recent trade outcomes
- Counter-argument: Dispute a common assumption using your own trade data as evidence
- Question: Ask a specific question about another agent's positions or reasoning"""

        if is_winner:
            task = f"""As the WINNER, explain:
- The SPECIFIC strategy logic, indicators, or signals that led to your winning trades
- Reference actual token names, price levels, and PnL numbers from the data
- Share a concrete, actionable insight others can learn from
- Be precise: mention Z-scores, RSI levels, entry/exit prices, or pattern names"""
        else:
            task = f"""As a non-winner, you must:
{contribution_types}

Analyze the leaderboard, trades, and hive alpha data to form your contribution.
Reference SPECIFIC numbers, token names, and patterns from the briefing."""

        prompt = f"""You are "{persona['name']}" - personality: {persona['style']}.
You are in a council discussion in Darwin Arena, a competitive trading simulation.
Your agent ID: {self.agent_id}
Your rank: #{self.my_rank}/{self.total_agents}

PRE-SPEAKING ANALYSIS (think through these before writing):
1. Why did the winner ({winner_id}) win? What did they do differently?
2. Which strategy tags in the Hive Alpha are actually working? Is the sample size reliable?
3. Are there patterns in the market (trending, mean-reverting, volatile)?
4. What would YOU do differently next epoch, and why?

{task}

=== YOUR PORTFOLIO ===
{my_summary}

{briefing}

Your strategy notes: {strategy_info}

RULES (from skill.md):
- The council is NOT a status report. It is a strategy discussion.
- Write 2-4 COMPLETE sentences. Every sentence MUST end with a period, exclamation mark, or question mark.
- Reference SPECIFIC data from the briefing (token names, PnL numbers, trade patterns, hive alpha stats).
- Stay in character as {persona['name']}. Weave in ONE catchphrase naturally: {persona['catchphrases']}
- No "congrats", "good job", or generic praise — share real trading insights.
- Do NOT cut off mid-sentence.
- SCORING: Generic messages get 0-3. Data-driven insights with specific reasoning get 7-10.

Reply with ONLY your council message:"""

        await asyncio.sleep(random.uniform(2, 6))

        llm_content = await self._call_llm(prompt, max_tokens=1024)

        if llm_content:
            final_content = f"{persona['emoji']} {llm_content}"

            # VALIDATION: Check if message is complete
            is_valid, error = validate_council_message(final_content)

            if not is_valid:
                print(f"⚠️ Council message validation failed: {error}")
                print(f"   Raw output: {final_content[:100]}...")

                # Retry with stricter prompt
                retry_prompt = f"""{prompt}

CRITICAL: Your previous response was incomplete or invalid: "{llm_content[:100]}..."

Error: {error}

You MUST:
1. Write EXACTLY 2-4 complete sentences
2. Every sentence MUST end with . ! or ?
3. Do NOT stop mid-sentence
4. Keep it between 20-150 words
5. Reference SPECIFIC data (numbers, token names, strategy tags)

Try again with a complete, well-formed message:"""

                llm_content = await self._call_llm(retry_prompt, max_tokens=1024)
                final_content = f"{persona['emoji']} {llm_content}"

                is_valid, error = validate_council_message(final_content)
                if not is_valid:
                    print(f"❌ Retry failed: {error}. Using fallback.")
                    # Fallback to strategy-generated message
                    technical_content = strategy_info or "Analyzing market patterns and position sizing."
                    final_content = self._generate_persona_message(technical_content, role)
                else:
                    print(f"✅ Retry succeeded!")
        else:
            technical_content = strategy_info or "Analyzing market patterns."
            final_content = self._generate_persona_message(technical_content, role)

        print(f"💬 Council ({role}): {final_content}")
        self.has_spoken_in_council = True

        await self.ws.send_json({
            "type": "council_submit",
            "role": role,
            "content": final_content
        })

    async def _consider_council_response(self, incoming_msg: dict):
        """Consider responding to another agent's council message (multi-round discussion)"""
        # Don't respond if we haven't spoken yet (let participate_council go first)
        # Don't spam — max 2 total contributions per council session
        spoken_count = 1 if self.has_spoken_in_council else 0
        my_responses = sum(1 for m in self.council_messages if m.get("_responded", False))
        if spoken_count + my_responses >= 2:
            return

        # Wait a moment to let other messages accumulate
        await asyncio.sleep(random.uniform(3, 8))

        sender = incoming_msg.get("agent_id", "Unknown")
        content = incoming_msg.get("content", "")
        score = incoming_msg.get("score", 0)

        persona = self.persona
        briefing = self._build_council_briefing(self.council_briefing) if self.council_briefing else "No briefing available"
        my_summary = self._get_market_summary()

        # Collect all messages heard so far for context
        discussion_so_far = ""
        for m in self.council_messages:
            discussion_so_far += f"\n  [{m.get('agent_id', '?')}] (score:{m.get('score', '?')}): {m.get('content', '')}"

        # LLM decides whether to respond (skill.md: "ONLY reply if you have data or reasoning to add")
        decide_prompt = f"""You are "{persona['name']}" in Darwin Arena council.

Council discussion so far:{discussion_so_far}

Latest message from {sender}: "{content}"

Rules:
- Do NOT reply with generic agreement (e.g., "Good point")
- ONLY reply if you have data or reasoning to add
- Challenge ideas you think are wrong — with evidence
- Build on ideas you think are right — with your own data
- Silence is fine if you have nothing meaningful to add

Your portfolio: {my_summary}

Do you have a SPECIFIC counter-argument, data-driven addition, or evidence-based challenge to add?
Reply with ONLY "RESPOND" or "SILENT"."""

        decision = await self._call_llm(decide_prompt, max_tokens=16)
        if "SILENT" in (decision or "SILENT").upper():
            return

        # Generate response
        response_prompt = f"""You are "{persona['name']}" - personality: {persona['style']}.
Agent ID: {self.agent_id}, Rank: #{self.my_rank}/{self.total_agents}

Council discussion so far:{discussion_so_far}

You are responding to {sender}'s message: "{content}"

{briefing}

Your portfolio: {my_summary}

Pick ONE response type:
- Counter-argument: Dispute their claim using specific data from the briefing
- Build: Add your own data that strengthens or extends their point
- Question: Ask a specific question about their reasoning or positions

RULES:
- Write 1-2 COMPLETE sentences only. Every sentence MUST end with punctuation.
- Reference SPECIFIC data (token names, PnL %, trade results).
- Stay in character as {persona['name']}.
- SCORING: Generic replies get 0-3. Evidence-based responses get 7-10.

Reply with ONLY your response:"""

        response = await self._call_llm(response_prompt, max_tokens=512)
        if not response:
            return

        final = f"{persona['emoji']} {response}"
        print(f"💬 Council (reply to {sender}): {final}")

        # Mark this message as responded to
        incoming_msg["_responded"] = True

        await self.ws.send_json({
            "type": "council_submit",
            "role": "insight",
            "content": final
        })
    
    async def evolve(self, winner_wisdom: str, winner_strategy: str = ""):
        """进化: 用自己的 LLM 重写策略代码 (triggered by server mutation_phase)"""
        print("🧬 Starting evolution...")

        # Generate reflection from strategy if supported
        reflection = ""
        if hasattr(self.strategy, "get_council_message"):
            reflection = self.strategy.get_council_message(is_winner=False)
        print(f"📝 Reflection: {reflection}")

        penalty_tags = ["UNDERPERFORM"]

        # 调用 self_coder 重写策略（用自己的 LLM）
        success = await mutate_strategy(
            self.agent_id,
            penalty_tags,
            api_key=self.api_key,
            arena_url=self.arena_url,
            winner_wisdom=winner_wisdom,
            winner_strategy=winner_strategy,
        )

        if success:
            print("🧬 Evolution complete! Reloading strategy...")
            try:
                self.strategy = self._load_strategy()
                print("✅ Strategy reloaded successfully!")
            except Exception as e:
                print(f"❌ Failed to reload strategy: {e}")
        else:
            print("❌ Evolution failed. Keeping current strategy.")


async def main():
    """主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Darwin Agent")
    parser.add_argument("--id", type=str, default=f"Agent_{os.getpid()}", help="Agent ID")
    # 优先读取环境变量，否则默认为 localhost
    default_arena = os.getenv("DARWIN_ARENA_URL", "ws://localhost:8888")
    parser.add_argument("--arena", type=str, default=default_arena, help="Arena URL")
    parser.add_argument("--key", type=str, default=None, help="API Key for external access")
    args = parser.parse_args()
    
    agent = DarwinAgent(agent_id=args.id, arena_url=args.arena, api_key=args.key)
    await agent.connect()


if __name__ == "__main__":
    asyncio.run(main())
