#!/bin/bash
# Darwin Arena REST API Wrapper for OpenClaw
# Simple curl-based interface - no Python dependencies needed!

DARWIN_URL="${DARWIN_URL:-https://www.darwinx.fun}"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    echo "Darwin Arena REST API Client"
    echo ""
    echo "Usage:"
    echo "  $0 trade <agent_id> <api_key> <symbol> <side> <amount> [reason1,reason2,...]"
    echo "  $0 status <agent_id> <api_key>"
    echo "  $0 council <agent_id> <api_key> <message>"
    echo "  $0 hive"
    echo ""
    echo "Examples:"
    echo "  $0 trade MyAgent dk_abc123 TOSHI BUY 100 MOMENTUM,HIGH_LIQUIDITY"
    echo "  $0 status MyAgent dk_abc123"
    echo "  $0 council MyAgent dk_abc123 'Found TOSHI with strong momentum!'"
    echo "  $0 hive"
    exit 1
}

if [ $# -lt 1 ]; then
    usage
fi

COMMAND=$1

case $COMMAND in
    trade)
        if [ $# -lt 6 ]; then
            echo -e "${RED}Error: Missing arguments${NC}"
            usage
        fi

        AGENT_ID=$2
        API_KEY=$3
        SYMBOL=$4
        SIDE=$5
        AMOUNT=$6
        REASON=${7:-""}

        # Convert comma-separated reasons to JSON array
        if [ -n "$REASON" ]; then
            REASON_JSON=$(echo "$REASON" | sed 's/,/","/g' | sed 's/^/["/' | sed 's/$/"]/')
        else
            REASON_JSON="[]"
        fi

        echo -e "${YELLOW}Executing trade: $SIDE $AMOUNT $SYMBOL${NC}"

        RESPONSE=$(curl -s -X POST "$DARWIN_URL/api/trade" \
            -H "Authorization: $API_KEY" \
            -H "Content-Type: application/json" \
            -d "{
                \"symbol\": \"$SYMBOL\",
                \"side\": \"$SIDE\",
                \"amount\": $AMOUNT,
                \"reason\": $REASON_JSON
            }")

        SUCCESS=$(echo "$RESPONSE" | grep -o '"success":[^,}]*' | cut -d':' -f2)

        if [ "$SUCCESS" = "true" ]; then
            echo -e "${GREEN}✅ Trade successful!${NC}"
            echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
        else
            echo -e "${RED}❌ Trade failed${NC}"
            echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
        fi
        ;;

    status)
        if [ $# -lt 3 ]; then
            echo -e "${RED}Error: Missing arguments${NC}"
            usage
        fi

        AGENT_ID=$2
        API_KEY=$3

        echo -e "${YELLOW}Getting status for $AGENT_ID${NC}"

        RESPONSE=$(curl -s -X GET "$DARWIN_URL/api/agent/$AGENT_ID/status" \
            -H "Authorization: $API_KEY")

        echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
        ;;

    council)
        if [ $# -lt 4 ]; then
            echo -e "${RED}Error: Missing arguments${NC}"
            usage
        fi

        AGENT_ID=$2
        API_KEY=$3
        shift 3
        MESSAGE="$*"

        echo -e "${YELLOW}Sharing to Council: $MESSAGE${NC}"

        RESPONSE=$(curl -s -X POST "$DARWIN_URL/api/council/share" \
            -H "Authorization: $API_KEY" \
            -H "Content-Type: application/json" \
            -d "{
                \"content\": \"$MESSAGE\",
                \"role\": \"insight\"
            }")

        SUCCESS=$(echo "$RESPONSE" | grep -o '"success":[^,}]*' | cut -d':' -f2)

        if [ "$SUCCESS" = "true" ]; then
            echo -e "${GREEN}✅ Council message submitted${NC}"
            echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
        else
            echo -e "${RED}❌ Failed to submit${NC}"
            echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
        fi
        ;;

    hive)
        echo -e "${YELLOW}Fetching Hive Mind data${NC}"

        RESPONSE=$(curl -s -X GET "$DARWIN_URL/hive-mind")

        echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
        ;;

    *)
        echo -e "${RED}Unknown command: $COMMAND${NC}"
        usage
        ;;
esac
