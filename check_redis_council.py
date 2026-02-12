import redis
import os
import json

# 从环境变量读取 Redis 配置
REDIS_HOST = os.getenv("REDIS_HOST", "sfo1.clusters.zeabur.com")
REDIS_PORT = int(os.getenv("REDIS_PORT", "31441"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

print(f"Connecting to Redis: {REDIS_HOST}:{REDIS_PORT}")
print(f"Password set: {'Yes' if REDIS_PASSWORD else 'No'}")

try:
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=5
    )
    
    # Test connection
    r.ping()
    print("✅ Redis connected successfully\n")
    
    # Check council sessions
    council_key = "darwin:council_sessions"
    council_data = r.get(council_key)
    
    if council_data:
        sessions = json.loads(council_data)
        print(f"📊 Council sessions found: {len(sessions)} epochs")
        for epoch, session in list(sessions.items())[:5]:
            msg_count = len(session.get("messages", []))
            print(f"  Epoch {epoch}: {msg_count} messages")
    else:
        print("❌ No council data found in Redis")
        
except redis.exceptions.AuthenticationError as e:
    print(f"❌ Authentication failed: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
