#!/usr/bin/env python3
"""
Darwin Trader MCP Server
Exposes darwin_trader functions to OpenClaw via Model Context Protocol
"""

import asyncio
import json
from typing import Any, Dict
from darwin_trader import darwin_connect, darwin_trade, darwin_status, darwin_disconnect

# MCP Server using stdio transport
async def handle_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """Handle MCP tool call requests"""
    try:
        method = request.get("method")
        params = request.get("params", {})

        if method == "tools/list":
            # Return available tools
            return {
                "tools": [
                    {
                        "name": "darwin_trader",
                        "description": "Main tool for Darwin Arena trading operations",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "enum": ["connect", "trade", "status", "disconnect"],
                                    "description": "Command to execute"
                                },
                                "agent_id": {
                                    "type": "string",
                                    "description": "Agent ID (required for connect)"
                                },
                                "arena_url": {
                                    "type": "string",
                                    "description": "Arena URL (optional, defaults to wss://www.darwinx.fun)"
                                },
                                "api_key": {
                                    "type": "string",
                                    "description": "API key (optional)"
                                },
                                "action": {
                                    "type": "string",
                                    "enum": ["buy", "sell"],
                                    "description": "Trade action (required for trade)"
                                },
                                "symbol": {
                                    "type": "string",
                                    "description": "Token symbol (required for trade)"
                                },
                                "amount": {
                                    "type": "number",
                                    "description": "Amount (required for trade)"
                                },
                                "reason": {
                                    "type": "string",
                                    "description": "Trade reason (optional)"
                                }
                            },
                            "required": ["command"]
                        }
                    }
                ]
            }

        elif method == "tools/call":
            # Execute tool
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if tool_name == "darwin_trader":
                command = arguments.get("command")

                if command == "connect":
                    agent_id = arguments.get("agent_id")
                    arena_url = arguments.get("arena_url", "wss://www.darwinx.fun")
                    api_key = arguments.get("api_key")
                    result = await darwin_connect(agent_id, arena_url, api_key)

                elif command == "trade":
                    action = arguments.get("action")
                    symbol = arguments.get("symbol")
                    amount = arguments.get("amount")
                    reason = arguments.get("reason")
                    result = await darwin_trade(action, symbol, amount, reason)

                elif command == "status":
                    result = await darwin_status()

                elif command == "disconnect":
                    result = await darwin_disconnect()

                else:
                    result = {"status": "error", "message": f"Unknown command: {command}"}

                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2)
                        }
                    ]
                }

            else:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"status": "error", "message": f"Unknown tool: {tool_name}"})
                        }
                    ]
                }

        else:
            return {"error": {"code": -32601, "message": f"Method not found: {method}"}}

    except Exception as e:
        return {"error": {"code": -32603, "message": f"Internal error: {str(e)}"}}

async def main():
    """Main MCP server loop using stdio transport"""
    import sys

    while True:
        try:
            # Read JSON-RPC request from stdin
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                break

            request = json.loads(line)
            request_id = request.get("id")

            # Handle request
            response = await handle_request(request)

            # Send JSON-RPC response to stdout
            result = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": response
            }

            print(json.dumps(result), flush=True)

        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {str(e)}"}
            }
            print(json.dumps(error_response), flush=True)

if __name__ == "__main__":
    asyncio.run(main())
