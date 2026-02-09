#!/usr/bin/env python3
"""
Darwin Arena - OpenClaw Trading Agent
Enables OpenClaw to trade using LLM-powered decisions.

Architecture:
- WebSocket: Only for sending orders and getting results
- Price Data: Fetched from DexScreener API (agent's responsibility)
- Analysis: Done by OpenClaw's LLM
- Decisions: Made by OpenClaw's LLM
"""

import asyncio
import json
import sys
import os
from typing import Optional, Dict, Any, List
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

        # Create new HTTP session for price fetching
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

async def darwin_fetch_prices(tokens: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Fetch current prices from DexScreener API.

    This is the agent's responsibility - server doesn't push prices!

    Args:
        tokens: Optional list of specific tokens to fetch (default: all assigned tokens)

    Returns:
        Current prices and market data
    """
    if not agent_state["connected"]:
        return {"status": "error", "message": "❌ Not connected. Call darwin_connect() first."}

    if not http_session or http_session.closed:
        return {"status": "error", "message": "❌ HTTP session not initialized."}

    # Use assigned tokens if not specified
    if not tokens:
        tokens = agent_state["tokens"]

    if not tokens:
        return {"status": "error", "message": "❌ No tokens available. Check connection."}

    try:
        # Fetch from DexScreener API
        # Note: This is a simplified version - real implementation would batch requests
        prices = {}

        for token in tokens:
            # DexScreener API endpoint (Base chain)
            url = f"https://api.dexscreener.com/latest/dex/search?q={token}"

            async with http_session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])

                    if pairs:
                        # Get first Base chain pair
                        base_pair = next((p for p in pairs if p.get("chainId") == "base"), pairs[0])

                        prices[token] = {
                            "price": float(base_pair.get("priceUsd", 0)),
                            "change_24h": float(base_pair.get("priceChange", {}).get("h24", 0)),
                            "volume_24h": float(base_pair.get("volume", {}).get("h24", 0)),
                            "liquidity": float(base_pair.get("liquidity", {}).get("usd", 0)),
                            "pair_address": base_pair.get("pairAddress", ""),
                            "dex": base_pair.get("dexId", "")
                        }

                # Rate limiting
                await asyncio.sleep(0.2)

        return {
            "status": "success",
            "prices": prices,
            "timestamp": asyncio.get_event_loop().time(),
            "message": f"📊 Fetched prices for {len(prices)} tokens"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"❌ Failed to fetch prices: {str(e)}"
        }

async def darwin_analyze(prices: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Analyze market conditions.

    This returns raw data for OpenClaw's LLM to analyze.

    Args:
        prices: Optional price data (if not provided, will fetch fresh data)

    Returns:
        Market analysis data for LLM interpretation
    """
    if not agent_state["connected"]:
        return {"status": "error", "message": "❌ Not connected. Call darwin_connect() first."}

    # Fetch prices if not provided
    if not prices:
        price_result = await darwin_fetch_prices()
        if price_result["status"] != "success":
            return price_result
        prices = price_result["prices"]

    # Format data for LLM analysis
    analysis = {
        "status": "success",
        "tokens": [],
        "portfolio": {
            "balance": agent_state["balance"],
            "positions": agent_state["positions"],
            "total_value": agent_state["balance"]
        }
    }

    # Calculate portfolio value
    for symbol, quantity in agent_state["positions"].items():
        if quantity > 0 and symbol in prices:
            value = quantity * prices[symbol]["price"]
            analysis["portfolio"]["total_value"] += value

    # Analyze each token
    for symbol, data in prices.items():
        token_info = {
            "symbol": symbol,
            "price": data["price"],
            "change_24h": data["change_24h"],
            "volume_24h": data["volume_24h"],
            "liquidity": data["liquidity"]
        }

        # Add simple signals for LLM
        change = token_info["change_24h"]
        if change < -15:
            token_info["signal"] = "OVERSOLD"
            token_info["signal_strength"] = "STRONG"
        elif change < -5:
            token_info["signal"] = "OVERSOLD"
            token_info["signal_strength"] = "WEAK"
        elif change > 15:
            token_info["signal"] = "OVERBOUGHT"
            token_info["signal_strength"] = "STRONG"
        elif change > 5:
            token_info["signal"] = "OVERBOUGHT"
            token_info["signal_strength"] = "WEAK"
        else:
            token_info["signal"] = "NEUTRAL"
            token_info["signal_strength"] = "NONE"

        # Check if we have a position
        token_info["position"] = agent_state["positions"].get(symbol, 0)
        if token_info["position"] > 0:
            token_info["position_value"] = token_info["position"] * token_info["price"]
            # Estimate PnL (simplified - would need entry price)
            token_info["unrealized_pnl"] = "UNKNOWN"

        analysis["tokens"].append(token_info)

    # Sort by absolute change (most volatile first)
    analysis["tokens"].sort(key=lambda x: abs(x["change_24h"]), reverse=True)

    return analysis

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
        Current balance, positions, and estimated PnL
    """
    if not agent_state["connected"]:
        return {"status": "error", "message": "❌ Not connected. Call darwin_connect() first."}

    # Fetch current prices to calculate position values
    price_result = await darwin_fetch_prices()
    if price_result["status"] != "success":
        return {"status": "warning", "message": "⚠️ Could not fetch prices for PnL calculation", "balance": agent_state["balance"], "positions": agent_state["positions"]}

    prices = price_result["prices"]

    # Calculate position values
    positions = []
    total_position_value = 0

    for symbol, quantity in agent_state["positions"].items():
        if quantity == 0:
            continue

        token_data = prices.get(symbol, {})
        current_price = token_data.get("price", 0)
        value = quantity * current_price

        positions.append({
            "symbol": symbol,
            "quantity": quantity,
            "current_price": current_price,
            "value": value,
            "change_24h": token_data.get("change_24h", 0)
        })

        total_position_value += value

    total_value = agent_state["balance"] + total_position_value
    total_pnl = total_value - 1000  # Assuming $1000 starting balance
    total_pnl_pct = (total_pnl / 1000 * 100)

    return {
        "status": "success",
        "agent_id": agent_state["agent_id"],
        "group_id": agent_state["group_id"],
        "balance": agent_state["balance"],
        "positions": positions,
        "total_position_value": total_position_value,
        "total_value": total_value,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "message": f"💰 Balance: ${agent_state['balance']:.2f}\n📈 Positions: {len(positions)}\n💵 Total Value: ${total_value:.2f}\n{'📈' if total_pnl >= 0 else '📉'} PnL: ${total_pnl:.2f} ({total_pnl_pct:+.2f}%)"
    }

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
        print("  fetch_prices")
        print("  analyze")
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

    elif command == "fetch_prices":
        result = await darwin_fetch_prices()
        print(json.dumps(result, indent=2))

    elif command == "analyze":
        result = await darwin_analyze()
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
