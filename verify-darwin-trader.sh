#!/bin/bash
# Darwin Trader Skill - 部署验证脚本

echo "🧬 Darwin Trader Skill - Deployment Verification"
echo "================================================"
echo ""

BASE_URL="${DARWIN_URL:-https://www.darwinx.fun}"

echo "🔍 Testing endpoints on: $BASE_URL"
echo ""

# Test 1: SKILL.md
echo "1️⃣ Testing SKILL.md endpoint..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/skill/darwin-trader.md")
if [ "$STATUS" = "200" ]; then
    echo "   ✅ SKILL.md accessible"
else
    echo "   ❌ SKILL.md failed (HTTP $STATUS)"
fi

# Test 2: darwin_trader.py
echo "2️⃣ Testing darwin_trader.py endpoint..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/skill/darwin-trader/darwin_trader.py")
if [ "$STATUS" = "200" ]; then
    echo "   ✅ darwin_trader.py accessible"
else
    echo "   ❌ darwin_trader.py failed (HTTP $STATUS)"
fi

# Test 3: requirements.txt
echo "3️⃣ Testing requirements.txt endpoint..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/skill/darwin-trader/requirements.txt")
if [ "$STATUS" = "200" ]; then
    echo "   ✅ requirements.txt accessible"
else
    echo "   ❌ requirements.txt failed (HTTP $STATUS)"
fi

# Test 4: README.md
echo "4️⃣ Testing README.md endpoint..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/skill/darwin-trader/README.md")
if [ "$STATUS" = "200" ]; then
    echo "   ✅ README.md accessible"
else
    echo "   ❌ README.md failed (HTTP $STATUS)"
fi

# Test 5: Download and verify darwin_trader.py
echo "5️⃣ Verifying darwin_trader.py content..."
CONTENT=$(curl -s "$BASE_URL/skill/darwin-trader/darwin_trader.py" | head -5)
if echo "$CONTENT" | grep -q "Darwin Arena"; then
    echo "   ✅ darwin_trader.py content valid"
else
    echo "   ❌ darwin_trader.py content invalid"
fi

# Test 6: WebSocket endpoint (connection test)
echo "6️⃣ Testing WebSocket endpoint..."
WS_URL="${BASE_URL/https:/wss:}"
WS_URL="${WS_URL/http:/ws:}"
echo "   WebSocket URL: $WS_URL/ws/TestAgent"
echo "   (Manual test required - use darwin_trader.py connect)"

echo ""
echo "================================================"
echo "✅ Verification complete!"
echo ""
echo "📝 Next steps:"
echo "   1. Install in OpenClaw: /skill $BASE_URL/skill/darwin-trader.md"
echo "   2. Connect: darwin_trader(command=\"connect\", agent_id=\"MyTrader\")"
echo "   3. Trade: darwin_trader(command=\"trade\", action=\"buy\", symbol=\"DEGEN\", amount=100)"
echo ""
