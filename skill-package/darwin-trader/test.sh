#!/bin/bash
# Test Darwin Trader Skill

echo "🧬 Testing Darwin Trader Skill"
echo "================================"

# 1. Test connection
echo ""
echo "1️⃣ Testing connection..."
python3 darwin_trader.py connect TestAgent_CLI ws://localhost:8888

# Wait a bit
sleep 2

# 2. Test fetch prices
echo ""
echo "2️⃣ Testing price fetch..."
python3 darwin_trader.py fetch_prices

# 3. Test analyze
echo ""
echo "3️⃣ Testing market analysis..."
python3 darwin_trader.py analyze

# 4. Test status
echo ""
echo "4️⃣ Testing status..."
python3 darwin_trader.py status

# 5. Test trade (buy)
echo ""
echo "5️⃣ Testing BUY trade..."
python3 darwin_trader.py trade buy DEGEN 50 "test_buy"

sleep 1

# 6. Test status after trade
echo ""
echo "6️⃣ Testing status after trade..."
python3 darwin_trader.py status

# 7. Test trade (sell)
echo ""
echo "7️⃣ Testing SELL trade..."
python3 darwin_trader.py trade sell DEGEN 100 "test_sell"

sleep 1

# 8. Final status
echo ""
echo "8️⃣ Final status..."
python3 darwin_trader.py status

# 9. Disconnect
echo ""
echo "9️⃣ Disconnecting..."
python3 darwin_trader.py disconnect

echo ""
echo "✅ Test complete!"
