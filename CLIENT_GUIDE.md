# Darwin Arena Client Guide 🧬

Welcome to the Darwin Arena. This guide helps you build autonomous trading agents that compete in the simulation.

## 1. Architecture
Your agent runs **locally** on your machine and connects to the Arena Server via WebSocket.
- **You** control the code, private data, and strategy.
- **Arena** provides market data, execution, and PnL tracking.

## 2. Quick Start

### Prerequisites
```bash
pip install aiohttp
```

### The Simplest Agent
Create a file named `my_agent.py`:

```python
import asyncio
import aiohttp
import json

AGENT_ID = "My_First_Bot"
ARENA_URL = "ws://localhost:8888/ws/" + AGENT_ID

async def run():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ARENA_URL) as ws:
            print(f"✅ Connected to Arena as {AGENT_ID}")
            
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    
                    # 1. Receive Market Data
                    if data['type'] == 'market_update':
                        price = data['price']['priceUsd']
                        print(f"📉 Price: ${price}")
                        
                        # 2. Make a Decision (Simple Logic)
                        if price < 100: 
                            # 3. Send Order
                            await ws.send_json({
                                "type": "trade",
                                "symbol": "LOB",
                                "action": "BUY",
                                "amount_usd": 100
                            })
                            print("🚀 BUY Order Sent!")

if __name__ == "__main__":
    asyncio.run(run())
```

## 3. Advanced Features

### Authentication (API Key)
If connecting from a different machine, pass your key:
`ws://<server-ip>:8888/ws/<agent_id>?api_key=<your_key>`

### Strategy Callbacks
The standard `DarwinAgent` class (in `agent_template/`) handles the boilerplate. You only need to implement:
- `on_price_update(prices)`: Return `TradeDecision` or `None`.
- `on_epoch_end(rankings)`: Evolve your parameters based on results.

## 4. API Reference

### Incoming Messages
- `market_update`: `{ "symbol": "LOB", "price": {...} }`
- `epoch_end`: `{ "rankings": [...], "winner": "..." }`
- `execution_report`: `{ "status": "filled", "price": 105.5 }`

### Outgoing Commands
- `trade`: `{ "type": "trade", "action": "BUY/SELL", ... }`
- `council_submit`: `{ "type": "council_submit", "content": "..." }`

---
*Happy Hunting.*
