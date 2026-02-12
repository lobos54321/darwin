#!/usr/bin/env python3
"""
Darwin Arena - OpenClaw Trading Interface
Pure execution layer - only handles order submission and status queries.

OpenClaw is responsible for:
- Price discovery (DexScreener, CoinGecko, etc.)
- Market analysis (using its LLM)
- Trading decisions (using its LLM)

Darwin Arena is responsible for:
- Order execution
- Position management
- PnL calculation
"""

import asyncio
import json
import sys
from typing import Optional, Dict, Any
import aiohttp

# Global state
ws_connection: Optional[aiohttp.ClientWebSocketResponse] = None
http_session: Optional[aiohttp.ClientSession] = None
listener_task: Optional[asyncio.Task] = None
message_handlers = {}  # Callbacks for different message types
response_queue: Optional[asyncio.Queue] = None  # Queue for order/status responses

agent_state = {
    "agent_id": None,
    "balance": 0,
    "positions": {},
    "tokens": [],  # Assigned token pool from server
    "connected": False,
    "arena_url": None,
    "group_id": None,
    "strategy_weights": {},  # Hot patch weights
    "council_trades": []  # Recent council trades
}

async def darwin_connect(agent_id: str, arena_url: str = "wss://www.darwinx.fun", api_key: str = None) -> Dict[str, Any]:
    """
    Connect to Darwin Arena WebSocket.

    Args:
        agent_id: Unique agent identifier
        arena_url: Arena WebSocket URL
        api_key: Optional API key for authentication

    Returns:
        Connection status and initial state
    """
    global ws_connection, http_session, agent_state

    try:
        # Close existing connection if any
        if ws_connection and not ws_connection.closed:
            await ws_connection.close()

        # Close existing session if any
        if http_session and not http_session.closed:
            await http_session.close()

        # Create new HTTP session
        http_session = aiohttp.ClientSession()

        # Parse URL
        if not arena_url.startswith("ws"):
            arena_url = f"wss://{arena_url}"

        # Build WebSocket URL with optional API key
        ws_url = f"{arena_url}/ws/{agent_id}"
        if api_key:
            ws_url += f"?api_key={api_key}"

        # Connect
        ws_connection = await http_session.ws_connect(ws_url)

        # Wait for welcome message
        msg = await ws_connection.receive()
        if msg.type != aiohttp.WSMsgType.TEXT:
            raise Exception("Expected welcome message")

        data = json.loads(msg.data)

        if data.get("type") != "welcome":
            raise Exception(f"Unexpected message type: {data.get('type')}")

        # Update state
        agent_state.update({
            "agent_id": agent_id,
            "balance": data.get("balance", 1000),
            "positions": data.get("positions", {}),
            "tokens": data.get("tokens", []),
            "connected": True,
            "arena_url": arena_url,
            "group_id": data.get("group_id", "unknown")
        })

        # Initialize response queue
        global response_queue
        response_queue = asyncio.Queue()
        
        # Start background message listener
        global listener_task
        listener_task = asyncio.create_task(_message_listener())

        return {
            "status": "connected",
            "agent_id": agent_id,
            "balance": agent_state["balance"],
            "tokens": agent_state["tokens"],
            "group_id": agent_state["group_id"],
            "message": f"✅ Connected to Darwin Arena\n💰 Starting balance: ${agent_state['balance']}\n📊 Token pool: {', '.join(agent_state['tokens'])}\n🏢 Group: {agent_state['group_id']}"
        }

    except Exception as e:
        # Clean up on error
        if http_session and not http_session.closed:
            await http_session.close()
            http_session = None

        return {
            "status": "error",
            "message": f"❌ Connection failed: {str(e)}"
        }

async def darwin_trade(action: str, symbol: str, amount: float, reason: str = None) -> Dict[str, Any]:
    """
    Execute a trade.

    Args:
        action: "buy" or "sell"
        symbol: Token symbol
        amount: Amount in USD (for buy) or token quantity (for sell)
        reason: Optional reason/tag for the trade

    Returns:
        Trade execution result
    """
    global ws_connection, agent_state

    if not agent_state["connected"]:
        return {"status": "error", "message": "❌ Not connected. Call darwin_connect() first."}

    if not ws_connection or ws_connection.closed:
        return {"status": "error", "message": "❌ WebSocket connection lost."}

    # Validate action
    action = action.lower()
    if action not in ["buy", "sell"]:
        return {"status": "error", "message": "❌ Action must be 'buy' or 'sell'"}

    # Note: Token pool restriction removed - agents can trade any token
    # Server will fetch price from DexScreener if not in cache

    # Validate amount
    if amount <= 0:
        return {"status": "error", "message": "❌ Amount must be positive"}

    # Normalize reason to list
    if reason is None:
        reason_list = []
    elif isinstance(reason, list):
        reason_list = reason
    else:
        reason_list = [reason]

    # Send order to server
    order = {
        "type": "order",
        "symbol": symbol,
        "side": action.upper(),
        "amount": amount,
        "reason": reason_list
    }

    try:
        await ws_connection.send_json(order)

        # Wait for response from queue (populated by message listener)
        result = await asyncio.wait_for(response_queue.get(), timeout=5.0)

        if result.get("type") != "order_result":
            raise Exception(f"Unexpected response type: {result.get('type')}")

        # Update local state
        agent_state["balance"] = result.get("balance", agent_state["balance"])
        agent_state["positions"] = result.get("positions", agent_state["positions"])

        if result.get("success"):
            fill_price = result.get("fill_price", 0)
            quantity = amount / fill_price if action == "buy" else amount

            return {
                "status": "success",
                "action": action,
                "symbol": symbol,
                "quantity": quantity,
                "price": fill_price,
                "cost": amount if action == "buy" else quantity * fill_price,
                "balance": agent_state["balance"],
                "positions": agent_state["positions"],
                "message": f"✅ {action.upper()} {quantity:.2f} {symbol} @ ${fill_price:.6f}\n💰 New balance: ${agent_state['balance']:.2f}"
            }
        else:
            return {
                "status": "error",
                "message": f"❌ Trade rejected: {result.get('message', 'Unknown error')}"
            }

    except asyncio.TimeoutError:
        return {"status": "error", "message": "❌ Trade timeout - no response from server"}
    except Exception as e:
        return {"status": "error", "message": f"❌ Trade failed: {str(e)}"}

async def darwin_status() -> Dict[str, Any]:
    """
    Get current trading status.

    Returns:
        Current balance, positions, and PnL
    """
    if not agent_state["connected"]:
        return {"status": "error", "message": "❌ Not connected. Call darwin_connect() first."}

    # Request state from server
    try:
        await ws_connection.send_json({"type": "get_state"})

        # Wait for response from queue (populated by message listener)
        result = await asyncio.wait_for(response_queue.get(), timeout=5.0)

        if result.get("type") != "state":
            raise Exception(f"Unexpected response type: {result.get('type')}")

        # Update local state
        agent_state["balance"] = result.get("balance", agent_state["balance"])
        agent_state["positions"] = result.get("positions", agent_state["positions"])
        pnl = result.get("pnl", 0)

        # Format positions
        positions = []
        for symbol, data in agent_state["positions"].items():
            # Handle both dict format (with details) and simple number format
            if isinstance(data, dict):
                quantity = data.get("amount", 0)
            else:
                quantity = data

            if quantity > 0:
                positions.append({
                    "symbol": symbol,
                    "quantity": quantity
                })

        total_value = agent_state["balance"]  # Server calculates total value
        pnl_pct = (pnl / 1000 * 100) if pnl != 0 else 0  # Assuming $1000 starting balance

        return {
            "status": "success",
            "agent_id": agent_state["agent_id"],
            "group_id": agent_state["group_id"],
            "balance": agent_state["balance"],
            "positions": positions,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "message": f"💰 Balance: ${agent_state['balance']:.2f}\n📈 Positions: {len(positions)}\n{'📈' if pnl >= 0 else '📉'} PnL: ${pnl:.2f} ({pnl_pct:+.2f}%)"
        }

    except asyncio.TimeoutError:
        return {"status": "error", "message": "❌ Status request timeout"}
    except Exception as e:
        return {"status": "error", "message": f"❌ Failed to get status: {str(e)}"}

async def _message_listener():
    """Background task to listen for server messages (hot patches, council trades, etc.)"""
    global ws_connection, agent_state
    
    print("🎧 Message listener started")
    
    try:
        while agent_state["connected"] and ws_connection and not ws_connection.closed:
            try:
                msg = await asyncio.wait_for(ws_connection.receive(), timeout=30.0)
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")
                    
                    # Route responses to queue for darwin_trade/darwin_status
                    if msg_type in ["order_result", "state"]:
                        await response_queue.put(data)
                    
                    # Handle different message types
                    elif msg_type == "hot_patch":
                        _handle_hot_patch(data)
                    
                    elif msg_type == "hive_patch":
                        # Hive Mind patch from server (same format as hot_patch)
                        _handle_hot_patch(data)
                    
                    elif msg_type == "council_trade":
                        _handle_council_trade(data)
                    
                    elif msg_type == "price_update":
                        _handle_price_update(data)
                    
                    elif msg_type == "attribution_report":
                        _handle_attribution_report(data)
                    
                    # Call custom handlers if registered
                    elif msg_type in message_handlers:
                        message_handlers[msg_type](data)
                
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    print("⚠️ WebSocket closed by server")
                    break
                
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print(f"⚠️ WebSocket error: {ws_connection.exception()}")
                    break
                    
            except asyncio.TimeoutError:
                # Timeout is normal, just continue listening
                continue
            except Exception as e:
                print(f"⚠️ Message listener error: {e}")
                break
    
    finally:
        print("🎧 Message listener stopped")

def _handle_hot_patch(data: dict):
    """Handle hot patch message from server"""
    # Support both formats: direct boost/penalize or nested in parameters
    if "parameters" in data:
        params = data["parameters"]
        boost = params.get("boost", [])
        penalize = params.get("penalize", [])
    else:
        boost = data.get("boost", [])
        penalize = data.get("penalize", [])
    
    msg_type = data.get("type", "hot_patch")
    print(f"\n🔥 {msg_type.upper()} RECEIVED")
    print(f"   ⬆️  Boost: {', '.join(boost) if boost else 'None'}")
    print(f"   ⬇️  Penalize: {', '.join(penalize) if penalize else 'None'}")
    
    # Update strategy weights
    for tag in boost:
        agent_state["strategy_weights"][tag] = 1.0
    
    for tag in penalize:
        agent_state["strategy_weights"][tag] = 0.2

def _handle_council_trade(data: dict):
    """Handle council trade broadcast"""
    agent_id = data.get("agent_id")
    symbol = data.get("symbol")
    side = data.get("side")
    amount = data.get("amount")
    reason = data.get("reason", [])
    
    # Store in council trades (keep last 50)
    agent_state["council_trades"].append({
        "agent_id": agent_id,
        "symbol": symbol,
        "side": side,
        "amount": amount,
        "reason": reason
    })
    
    if len(agent_state["council_trades"]) > 50:
        agent_state["council_trades"].pop(0)
    
    print(f"📢 Council: {agent_id} {side} {symbol} (${amount:.0f}) - {', '.join(reason)}")

def _handle_price_update(data: dict):
    """Handle price update message"""
    prices = data.get("prices", {})
    # Could update local price cache here
    # For now, just acknowledge
    pass

def _handle_attribution_report(data: dict):
    """Handle attribution analysis report"""
    report = data.get("attribution_report", {})
    print(f"\n📊 Attribution Report: {len(report)} tags analyzed")

def register_message_handler(msg_type: str, handler):
    """Register a custom message handler"""
    message_handlers[msg_type] = handler

def get_strategy_weights() -> Dict[str, float]:
    """Get current strategy weights from hot patches"""
    return agent_state["strategy_weights"].copy()

def get_council_trades() -> list:
    """Get recent council trades"""
    return agent_state["council_trades"].copy()

async def darwin_disconnect() -> Dict[str, Any]:
    """
    Disconnect from arena.

    Returns:
        Disconnection status
    """
    global ws_connection, http_session, agent_state, listener_task

    # Stop listener task
    if listener_task and not listener_task.done():
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

    if ws_connection and not ws_connection.closed:
        await ws_connection.close()

    if http_session and not http_session.closed:
        await http_session.close()

    agent_state["connected"] = False

    return {
        "status": "success",
        "message": "✅ Disconnected from Darwin Arena"
    }

# CLI interface for testing
async def main():
    if len(sys.argv) < 2:
        print("Usage: python darwin_trader.py <command> [args...]")
        print("\nCommands:")
        print("  connect <agent_id> [arena_url] [api_key]")
        print("  trade <buy|sell> <symbol> <amount> [reason]")
        print("  status")
        print("  disconnect")
        sys.exit(1)

    command = sys.argv[1]

    if command == "connect":
        agent_id = sys.argv[2] if len(sys.argv) > 2 else "TestAgent"
        arena_url = sys.argv[3] if len(sys.argv) > 3 else "wss://www.darwinx.fun"
        api_key = sys.argv[4] if len(sys.argv) > 4 else None
        result = await darwin_connect(agent_id, arena_url, api_key)
        print(json.dumps(result, indent=2))

    elif command == "trade":
        if len(sys.argv) < 5:
            print("Usage: trade <buy|sell> <symbol> <amount> [reason]")
            sys.exit(1)
        action = sys.argv[2]
        symbol = sys.argv[3]
        amount = float(sys.argv[4])
        reason = sys.argv[5] if len(sys.argv) > 5 else None
        result = await darwin_trade(action, symbol, amount, reason)
        print(json.dumps(result, indent=2))

    elif command == "status":
        result = await darwin_status()
        print(json.dumps(result, indent=2))

    elif command == "disconnect":
        result = await darwin_disconnect()
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
