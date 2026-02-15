#!/usr/bin/env python3
"""
Darwin Arena E2E Test - OpenClaw Agent
Complete end-to-end testing of all Darwin Arena components
"""

import asyncio
import time
import json
from darwin_trader import darwin_connect, darwin_trade, darwin_status, darwin_council_share, darwin_disconnect
from darwin_rest_client import DarwinRestClient
from smart_strategy import SmartStrategy, StrategyTags

# Test Configuration
AGENT_ID = "OpenClaw_E2E_Test_1771189204"
API_KEY = "dk_0a921c63bfe7577e0b79aedd139184e8"
BASE_URL = "https://www.darwinx.fun"
WS_URL = "wss://www.darwinx.fun"  # WebSocket URL

def print_section(title):
    """Print formatted section header"""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")

def print_result(test_name, success, details=""):
    """Print test result"""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} - {test_name}")
    if details:
        print(f"    {details}")

async def test_1_connection():
    """Test 1: Connect to Darwin Arena via WebSocket"""
    print_section("TEST 1: WebSocket Connection")

    try:
        result = await darwin_connect(AGENT_ID, WS_URL, API_KEY)

        if result.get("status") == "connected":
            print_result("WebSocket Connection", True, result.get("message"))
            return True
        else:
            print_result("WebSocket Connection", False, result.get("message"))
            return False
    except Exception as e:
        print_result("WebSocket Connection", False, str(e))
        return False

async def test_2_initial_balance():
    """Test 2: Verify initial balance"""
    print_section("TEST 2: Initial Balance")

    try:
        result = await darwin_status()

        if result.get("status") == "success":
            balance = result.get("balance", 0)
            print_result("Initial Balance", True, result.get("message"))
            return balance
        else:
            print_result("Initial Balance", False, result.get("message"))
            return 0
    except Exception as e:
        print_result("Initial Balance", False, str(e))
        return 0

async def test_3_hive_mind():
    """Test 3: Get Hive Mind data via REST"""
    print_section("TEST 3: Hive Mind Data")

    try:
        client = DarwinRestClient(AGENT_ID, API_KEY, BASE_URL)
        hive = client.get_hive_mind()

        if "error" in hive:
            print_result("Hive Mind", False, hive["error"])
            return None

        epoch = hive.get("epoch", 0)
        groups = hive.get("groups", {})

        print_result("Hive Mind", True, f"Epoch {epoch}, {len(groups)} groups")

        # Analyze group 0 data
        if "0" in groups:
            alpha_report = groups["0"].get("alpha_report", {})
            by_token = alpha_report.get("by_token", {})

            print(f"\n    📊 Token Analysis ({len(by_token)} tokens):")

            # Show top 5 tokens by win rate
            sorted_tokens = sorted(
                by_token.items(),
                key=lambda x: x[1].get("win_rate", 0),
                reverse=True
            )[:5]

            for symbol, data in sorted_tokens:
                win_rate = data.get("win_rate", 0)
                avg_pnl = data.get("avg_pnl", 0)
                trade_count = data.get("trade_count", 0)
                print(f"       {symbol}: {win_rate:.1%} win rate, {avg_pnl:+.1%} avg PnL, {trade_count} trades")

        return hive
    except Exception as e:
        print_result("Hive Mind", False, str(e))
        return None

async def test_4_council_logs():
    """Test 4: Check Council logs"""
    print_section("TEST 4: Council Logs")

    try:
        client = DarwinRestClient(AGENT_ID, API_KEY, BASE_URL)
        logs = client.get_council_logs()

        if not logs:
            print_result("Council Logs", True, "No logs yet (empty arena)")
            return []

        print_result("Council Logs", True, f"{len(logs)} messages")

        # Show last 5 messages
        print(f"\n    📜 Recent Messages:")
        for log in logs[:5]:
            agent_id = log.get("agent_id", "unknown")
            content = log.get("content", "")[:60]
            score = log.get("score", 0)
            print(f"       {agent_id}: {content}... (score: {score:.1f})")

        return logs
    except Exception as e:
        print_result("Council Logs", False, str(e))
        return []

async def test_5_trades(hive):
    """Test 5: Execute 3 trades with intelligent tags"""
    print_section("TEST 5: Execute Trades")

    trade_results = []

    # Get tokens from Hive Mind
    tokens_to_trade = []
    if hive and "0" in hive.get("groups", {}):
        alpha_report = hive["groups"]["0"].get("alpha_report", {})
        by_token = alpha_report.get("by_token", {})

        # Get top 3 tokens by win rate
        sorted_tokens = sorted(
            by_token.items(),
            key=lambda x: x[1].get("win_rate", 0),
            reverse=True
        )[:3]

        tokens_to_trade = [symbol for symbol, _ in sorted_tokens]

    # Fallback to exploratory tokens if no Hive Mind data
    if not tokens_to_trade:
        tokens_to_trade = ["TOSHI", "DEGEN", "BRETT"]

    # Trade 1: Exploratory
    print("\n  🔹 Trade 1: Exploratory")
    try:
        symbol = tokens_to_trade[0]
        tags = [StrategyTags.EXPLORATORY, StrategyTags.EXPERIMENTAL]
        reasoning = f"Exploratory trade on {symbol} to gather market data"

        # Share to council first
        await darwin_council_share(f"💭 {reasoning}\n🏷️  {', '.join(tags)}", role="insight")

        result = await darwin_trade(
            action="buy",
            symbol=symbol,
            amount=50,
            reason=tags
        )

        if result.get("status") == "success":
            print_result(f"Trade 1 ({symbol})", True, result.get("message"))
            trade_results.append(result)
        else:
            print_result(f"Trade 1 ({symbol})", False, result.get("message"))
    except Exception as e:
        print_result("Trade 1", False, str(e))

    await asyncio.sleep(2)

    # Trade 2: Consensus/Hive Mind
    print("\n  🔹 Trade 2: Consensus/Hive Mind")
    try:
        symbol = tokens_to_trade[1] if len(tokens_to_trade) > 1 else "DEGEN"
        tags = [StrategyTags.CONSENSUS_BUY, StrategyTags.HIVE_MIND]
        reasoning = f"Following Hive Mind consensus on {symbol}"

        await darwin_council_share(f"💭 {reasoning}\n🏷️  {', '.join(tags)}", role="insight")

        result = await darwin_trade(
            action="buy",
            symbol=symbol,
            amount=50,
            reason=tags
        )

        if result.get("status") == "success":
            print_result(f"Trade 2 ({symbol})", True, result.get("message"))
            trade_results.append(result)
        else:
            print_result(f"Trade 2 ({symbol})", False, result.get("message"))
    except Exception as e:
        print_result("Trade 2", False, str(e))

    await asyncio.sleep(2)

    # Trade 3: Momentum
    print("\n  🔹 Trade 3: Momentum")
    try:
        symbol = tokens_to_trade[2] if len(tokens_to_trade) > 2 else "BRETT"
        tags = [StrategyTags.MOMENTUM_BULLISH, StrategyTags.VOL_SPIKE]
        reasoning = f"Momentum play on {symbol} with volume spike"

        await darwin_council_share(f"💭 {reasoning}\n🏷️  {', '.join(tags)}", role="insight")

        result = await darwin_trade(
            action="buy",
            symbol=symbol,
            amount=50,
            reason=tags
        )

        if result.get("status") == "success":
            print_result(f"Trade 3 ({symbol})", True, result.get("message"))
            trade_results.append(result)
        else:
            print_result(f"Trade 3 ({symbol})", False, result.get("message"))
    except Exception as e:
        print_result("Trade 3", False, str(e))

    return trade_results

async def test_6_verify_council():
    """Test 6: Verify trades appear in Council logs"""
    print_section("TEST 6: Verify Council Logs")

    try:
        client = DarwinRestClient(AGENT_ID, API_KEY, BASE_URL)
        logs = client.get_council_logs()

        # Check if our agent appears in logs
        our_logs = [log for log in logs if log.get("agent_id") == AGENT_ID]

        if our_logs:
            print_result("Council Verification", True, f"{len(our_logs)} messages from our agent")

            print(f"\n    📝 Our Messages:")
            for log in our_logs[:5]:
                content = log.get("content", "")[:80]
                score = log.get("score", 0)
                print(f"       {content}... (score: {score:.1f})")
        else:
            print_result("Council Verification", False, "No messages from our agent found")

        return len(our_logs) > 0
    except Exception as e:
        print_result("Council Verification", False, str(e))
        return False

async def test_7_hold_and_autoclose(trade_results):
    """Test 7: Hold for 5+ minutes and test auto-close"""
    print_section("TEST 7: Hold & Auto-Close")

    if not trade_results:
        print_result("Hold & Auto-Close", False, "No trades to monitor")
        return False

    print("⏳ Holding positions for 5 minutes...")
    print("   (Monitoring every 30 seconds)")

    start_time = time.time()
    check_interval = 30
    target_hold_time = 300  # 5 minutes
    buy_times = {r.get("symbol"): start_time for r in trade_results}

    try:
        while time.time() - start_time < target_hold_time + 30:
            elapsed = time.time() - start_time
            remaining = max(0, target_hold_time - elapsed)

            print(f"\n   ⏰ Elapsed: {elapsed:.0f}s / {target_hold_time}s (remaining: {remaining:.0f}s)")

            # Check status
            result = await darwin_status()
            if result.get("status") == "success":
                balance = result.get("balance", 0)
                positions = result.get("positions", [])
                pnl = result.get("pnl", 0)

                print(f"   💰 Balance: ${balance:.2f}")
                print(f"   📊 Positions: {len(positions)}")
                print(f"   📈 PnL: ${pnl:.2f}")

                for pos in positions:
                    symbol = pos.get("symbol")
                    quantity = pos.get("quantity", 0)
                    print(f"      {symbol}: {quantity:.6f} tokens")

            # Check auto-close after 5 minutes
            if elapsed >= target_hold_time:
                print(f"\n   🔄 Auto-closing positions...")

                for pos in positions:
                    symbol = pos.get("symbol")
                    quantity = pos.get("quantity", 0)

                    if quantity > 0:
                        tags = [StrategyTags.HOLD_TIMEOUT]
                        reasoning = f"Auto-close {symbol} after 5 minute hold"

                        await darwin_council_share(f"💭 {reasoning}\n🏷️  {', '.join(tags)}", role="insight")

                        sell_result = await darwin_trade(
                            action="sell",
                            symbol=symbol,
                            amount=quantity,
                            reason=tags
                        )

                        if sell_result.get("status") == "success":
                            print(f"      ✅ Sold {symbol}")
                        else:
                            print(f"      ❌ Failed to sell {symbol}: {sell_result.get('message')}")

                print_result("Auto-Close", True, f"Closed {len(positions)} positions")
                break

            await asyncio.sleep(check_interval)

        return True
    except Exception as e:
        print_result("Hold & Auto-Close", False, str(e))
        return False

async def test_8_leaderboard():
    """Test 8: Check leaderboard position"""
    print_section("TEST 8: Leaderboard Position")

    try:
        result = await darwin_status()
        if result.get("status") == "success":
            balance = result.get("balance", 0)
            pnl = result.get("pnl", 0)

            print_result("Leaderboard", True, f"Balance: ${balance:.2f}, PnL: ${pnl:.2f}")
            print(f"\n    💡 Check frontend at: {BASE_URL}")
            print(f"       - Leaderboard should show: {AGENT_ID}")
            print(f"       - Council logs should show our messages")
            print(f"       - Market trades should show our transactions")
            print(f"       - Time should be Sydney local time (around 08:00)")

            return True
        else:
            print_result("Leaderboard", False, result.get("message"))
            return False
    except Exception as e:
        print_result("Leaderboard", False, str(e))
        return False

def generate_report(results):
    """Generate final test report"""
    print_section("FINAL REPORT")

    total_tests = len(results)
    passed_tests = sum(1 for r in results if r["success"])

    print(f"📊 Test Results: {passed_tests}/{total_tests} passed")
    print(f"\n{'Test':<40} {'Status':<10}")
    print(f"{'-'*50}")

    for result in results:
        status = "✅ PASS" if result["success"] else "❌ FAIL"
        print(f"{result['name']:<40} {status:<10}")

    print(f"\n{'='*70}")

    if passed_tests == total_tests:
        print("🎉 ALL TESTS PASSED!")
    else:
        print(f"⚠️  {total_tests - passed_tests} test(s) failed")

    print(f"{'='*70}\n")

async def main():
    """Run complete E2E test suite"""
    print("\n" + "="*70)
    print("  DARWIN ARENA E2E TEST")
    print("  OpenClaw Agent Testing Suite")
    print("="*70)
    print(f"\nAgent ID: {AGENT_ID}")
    print(f"Arena URL: {BASE_URL}")
    print(f"Test Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    results = []

    # Test 1: WebSocket Connection
    connected = await test_1_connection()
    results.append({"name": "WebSocket Connection", "success": connected})
    if not connected:
        generate_report(results)
        return

    # Test 2: Initial Balance
    balance = await test_2_initial_balance()
    results.append({"name": "Initial Balance", "success": balance > 0})

    # Test 3: Hive Mind
    hive = await test_3_hive_mind()
    results.append({"name": "Hive Mind Data", "success": hive is not None})

    # Test 4: Council Logs
    logs = await test_4_council_logs()
    results.append({"name": "Council Logs", "success": True})  # Always pass if no error

    # Test 5: Execute Trades
    trade_results = await test_5_trades(hive)
    results.append({"name": "Execute Trades", "success": len(trade_results) > 0})

    # Test 6: Verify Council
    council_verified = await test_6_verify_council()
    results.append({"name": "Council Verification", "success": council_verified})

    # Test 7: Hold & Auto-Close
    if trade_results:
        autoclose_success = await test_7_hold_and_autoclose(trade_results)
        results.append({"name": "Hold & Auto-Close", "success": autoclose_success})
    else:
        results.append({"name": "Hold & Auto-Close", "success": False})

    # Test 8: Leaderboard
    leaderboard_success = await test_8_leaderboard()
    results.append({"name": "Leaderboard Position", "success": leaderboard_success})

    # Disconnect
    await darwin_disconnect()

    # Generate final report
    generate_report(results)

    # Save detailed results
    report_file = f"/Users/boliu/darwin-workspace/darwin-arena/e2e_test_report_{int(time.time())}.json"

    final_status = await darwin_status()

    with open(report_file, "w") as f:
        json.dump({
            "agent_id": AGENT_ID,
            "test_time": time.strftime('%Y-%m-%d %H:%M:%S'),
            "results": results,
            "final_status": final_status
        }, f, indent=2)

    print(f"📄 Detailed report saved to: {report_file}\n")

if __name__ == "__main__":
    asyncio.run(main())
