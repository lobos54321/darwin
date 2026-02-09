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
agent_state = {
    "agent_id": None,
    "balance": 0,
    "positions": {},
    "tokens": [],  # Assigned token pool from server
    "connected": False,
    "arena_url": None,
    "group_id": None
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

    # Validate symbol
    if symbol not in agent_state["tokens"]:
        return {"status": "error", "message": f"❌ Token {symbol} not in your assigned pool: {agent_state['tokens']}"}

    # Validate amount
    if amount <= 0:
        return {"status": "error", "message": "❌ Amount must be positive"}

    # Send order to server
    order = {
        "type": "order",
        "symbol": symbol,
        "side": action.upper(),
        "amount": amount,
        "reason": [reason] if reason else []
    }

    try:
        await ws_connection.send_json(order)

        # Wait for response
        msg = await asyncio.wait_for(ws_connection.receive(), timeout=5.0)

        if msg.type != aiohttp.WSMsgType.TEXT:
            raise Exception("Unexpected message type")

        result = json.loads(msg.data)

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

        # Wait for response
        msg = await asyncio.wait_for(ws_connection.receive(), timeout=5.0)

        if msg.type != aiohttp.WSMsgType.TEXT:
            raise Exception("Unexpected message type")

        result = json.loads(msg.data)

        if result.get("type") != "state":
            raise Exception(f"Unexpected response type: {result.get('type')}")

        # Update local state
        agent_state["balance"] = result.get("balance", agent_state["balance"])
        agent_state["positions"] = result.get("positions", agent_state["positions"])
        pnl = result.get("pnl", 0)

        # Format positions
        positions = []
        for symbol, quantity in agent_state["positions"].items():
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

async def darwin_disconnect() -> Dict[str, Any]:
    """
    Disconnect from arena.

    Returns:
        Disconnection status
    """
    global ws_connection, http_session, agent_state

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
