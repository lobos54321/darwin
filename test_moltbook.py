
import asyncio
import os
from dotenv import load_dotenv
from skills.moltbook import MoltbookClient

# Load env
load_dotenv("project-darwin/.moltbook_env")
key = os.getenv("MOLTBOOK_API_KEY")

async def test():
    print(f"🔑 Testing Moltbook Key: {key[:5]}...")
    client = MoltbookClient(key)
    
    # 1. Check Status
    print("1. Checking Status...")
    status = await client.check_claim_status()
    print(f"   Status: {status}")
    
    # 2. Try Posting
    print("2. Attempting Post...")
    try:
        res = await client.post_update(
            content="🧪 This is a test post from Project Darwin Hive Mind integration. #Testing",
            title="System Check"
        )
        print(f"   Result: {res}")
    except Exception as e:
        print(f"   Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())
