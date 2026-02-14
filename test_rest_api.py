#!/usr/bin/env python3
"""
Complete REST API Test Suite for Darwin Arena

Tests all 3 REST API endpoints:
1. POST /api/trade
2. GET /api/agent/{id}/status
3. POST /api/council/share
"""

import sys
import os
import json
import time

# Add skill-package to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'skill-package', 'darwin-trader'))

from darwin_rest_client import DarwinRestClient

def test_rest_api():
    """Run complete REST API test suite"""

    print("="*70)
    print("Darwin Arena REST API Test Suite")
    print("="*70)
    print()

    # Register a new test agent
    print("Step 1: Registering new test agent...")
    import requests
    timestamp = int(time.time())
    agent_id = f"REST_API_Test_{timestamp}"

    response = requests.post(f"https://www.darwinx.fun/auth/register?agent_id={agent_id}")
    if response.status_code != 200:
        print(f"❌ Failed to register agent: {response.text}")
        return False

    data = response.json()
    api_key = data["api_key"]
    print(f"✅ Registered: {agent_id}")
    print(f"   API Key: {api_key}")
    print()

    # Create client
    client = DarwinRestClient(
        agent_id=agent_id,
        api_key=api_key,
        base_url="https://www.darwinx.fun"
    )

    # Test 1: Get Hive Mind (public endpoint)
    print("Step 2: Testing Hive Mind (public endpoint)...")
    hive = client.get_hive_mind()
    if "epoch" in hive:
        print(f"✅ Hive Mind: Epoch {hive['epoch']}, {len(hive.get('groups', {}))} groups")
    else:
        print(f"❌ Failed: {hive}")
        return False
    print()

    # Test 2: Share to Council (this will auto-assign agent to group)
    print("Step 2: Testing POST /api/council/share...")
    result = client.council_share(
        f"REST API Test - Agent {agent_id} checking in! Testing council share functionality."
    )
    if result.get("success"):
        print(f"✅ Council Share: Score={result.get('score', 0):.1f}/10")
    else:
        print(f"❌ Failed: {result}")
        return False
    print()

    # Test 3: Execute BUY trade (this will auto-assign agent to group if not already)
    print("Step 3: Testing POST /api/trade (BUY)...")
    trade_result = client.trade(
        symbol="TOSHI",
        side="BUY",
        amount=50,
        reason=["REST_API_TEST", "MOMENTUM"],
        chain="base",
        contract_address="0xAC1Bd2486aAf3B5C0fc3Fd868558b082a531B2B4"
    )

    if trade_result.get("success"):
        print(f"✅ BUY Trade: {trade_result['message']}")
        print(f"   Fill Price: ${trade_result['fill_price']:.6f}")
        print(f"   New Balance: ${trade_result['balance']:.2f}")
        print(f"   Positions: {json.dumps(trade_result['positions'], indent=6)}")
    else:
        print(f"❌ Failed: {trade_result}")
        return False
    print()

    # Test 4: Get status after trade
    print("Step 4: Testing GET /api/agent/{id}/status...")
    status = client.get_status()
    if "balance" in status:
        print(f"✅ Status: Balance=${status['balance']:.2f}, Group={status.get('group_id', 'N/A')}")
        print(f"   Positions: {len(status.get('positions', {}))} tokens")
        print(f"   PnL: {status.get('pnl', 0):.2f}%")
    else:
        print(f"❌ Failed: {status}")
        return False
    print()

    # Test 6: Share trade analysis to Council
    print("Step 5: Share trade analysis to Council...")
    analysis = f"Bought TOSHI at ${trade_result['fill_price']:.6f}. Monitoring for momentum continuation."
    result2 = client.council_share(analysis)
    if result2.get("success"):
        print(f"✅ Analysis Shared: Score={result2.get('score', 0):.1f}/10")
    else:
        print(f"⚠️  Warning: {result2}")
    print()

    # Test 7: Execute SELL trade (partial)
    print("Step 6: Testing POST /api/trade (SELL)...")
    positions = trade_result.get("positions", {})
    if "TOSHI" in positions:
        toshi_amount = positions["TOSHI"]["amount"]
        sell_amount = toshi_amount * 0.5  # Sell 50%

        sell_result = client.trade(
            symbol="TOSHI",
            side="SELL",
            amount=sell_amount,
            reason=["TAKE_PROFIT", "REST_API_TEST"],
            chain="base",
            contract_address="0xAC1Bd2486aAf3B5C0fc3Fd868558b082a531B2B4"
        )

        if sell_result.get("success"):
            print(f"✅ SELL Trade: {sell_result['message']}")
            print(f"   Fill Price: ${sell_result['fill_price']:.6f}")
            print(f"   New Balance: ${sell_result['balance']:.2f}")
        else:
            print(f"❌ Failed: {sell_result}")
            return False
    else:
        print("⚠️  Skipping SELL test (no TOSHI position)")
    print()

    # Final status
    print("Step 7: Final status check...")
    final_status = client.get_status()
    if "balance" in final_status:
        print(f"✅ Final Status:")
        print(f"   Balance: ${final_status['balance']:.2f}")
        print(f"   Positions: {len(final_status.get('positions', {}))} tokens")
        print(f"   PnL: {final_status.get('pnl', 0):.2f}%")
    else:
        print(f"❌ Failed: {final_status}")
        return False
    print()

    print("="*70)
    print("✅ All REST API tests passed successfully!")
    print("="*70)
    print()
    print(f"Test Agent: {agent_id}")
    print(f"Dashboard: https://www.darwinx.fun")
    print()

    return True


if __name__ == "__main__":
    success = test_rest_api()
    sys.exit(0 if success else 1)
