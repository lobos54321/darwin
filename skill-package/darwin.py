#!/usr/bin/env python3
import argparse
import os
import sys
import subprocess
import signal
import time
import json

# 配置路径
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_SCRIPT = os.path.join(SKILL_DIR, "agent_template", "agent.py")
PID_FILE = os.path.join(SKILL_DIR, "agent.pid")
LOG_FILE = os.path.join(SKILL_DIR, "agent.log")

def load_pid():
    if os.path.exists(PID_FILE):
        try:
            return int(open(PID_FILE).read().strip())
        except:
            return None
    return None

def is_running(pid):
    if not pid: return False
    try:
        os.kill(pid, 0) # 发送信号 0 检查进程是否存在
        return True
    except OSError:
        return False

def start(agent_id):
    pid = load_pid()
    if is_running(pid):
        print(f"⚠️ Agent is already running (PID: {pid}). Stop it first.")
        return

    if not agent_id:
        print("❌ Error: agent_id is required to start.")
        sys.exit(1)

    print(f"🚀 Starting Darwin Agent '{agent_id}'...")
    
    # 获取 Arena URL (支持环境变量配置)
    arena_url = os.environ.get("DARWIN_ARENA_URL", "ws://localhost:8888")
    print(f"🔗 Target Arena: {arena_url}")

    # === Auto-Auth Logic (Moltbook Style) ===
    api_key = None
    if "localhost" not in arena_url and "127.0.0.1" not in arena_url:
        # 这是一个远程连接，尝试自动注册/获取 Key
        try:
            import urllib.request
            import json
            
            # 1. 检查本地是否已保存 Key
            keys_file = os.path.join(SKILL_DIR, "keys.json")
            keys = {}
            if os.path.exists(keys_file):
                try:
                    keys = json.load(open(keys_file))
                except: pass
            
            if agent_id in keys:
                api_key = keys[agent_id]
                print(f"🔑 Found cached API Key: {api_key[:5]}...")
            else:
                # 2. 自动注册
                print(f"☁️ Detecting remote arena... Auto-registering '{agent_id}'...")
                http_url = arena_url.replace("ws://", "http://").replace("wss://", "https://")
                reg_url = f"{http_url}/auth/register?agent_id={agent_id}"
                
                with urllib.request.urlopen(reg_url, timeout=5) as response:
                    if response.getcode() == 200:
                        data = json.loads(response.read())
                        api_key = data["api_key"]
                        print(f"✅ Registration successful! Key: {api_key[:5]}...")
                        
                        # 保存 Key
                        keys[agent_id] = api_key
                        with open(keys_file, "w") as f:
                            json.dump(keys, f)
                    else:
                        print(f"⚠️ Auto-registration failed: {response.getcode()}")
        except Exception as e:
            print(f"⚠️ Auto-auth skipped (Connection error): {e}")

    # 启动后台进程
    with open(LOG_FILE, "a") as f:
        # 使用 nohup 类似的效果
        cmd = [sys.executable, "-u", AGENT_SCRIPT, "--id", agent_id, "--arena", arena_url]
        if api_key:
            cmd.extend(["--key", api_key])
        
        proc = subprocess.Popen(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            cwd=SKILL_DIR,
            start_new_session=True # 确保作为独立进程组运行
        )
    
    # 保存 PID
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    
    print(f"✅ Agent started successfully! (PID: {proc.pid})")
    print(f"📄 Logs: {LOG_FILE}")

def stop():
    pid = load_pid()
    if not is_running(pid):
        print("⚠️ No running agent found.")
        return

    print(f"🛑 Stopping agent (PID: {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(1)
        if is_running(pid):
            os.kill(pid, signal.SIGKILL)
        print("✅ Agent stopped.")
    except Exception as e:
        print(f"❌ Error stopping agent: {e}")
    
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

def status():
    pid = load_pid()
    running = is_running(pid)
    
    status_emoji = "🟢" if running else "🔴"
    status_text = "Running" if running else "Stopped"
    
    print(f"Status: {status_emoji} {status_text}")
    if running:
        print(f"PID: {pid}")
        # 读取最后几行日志
        if os.path.exists(LOG_FILE):
            print("\n--- Recent Logs ---")
            os.system(f"tail -n 5 {LOG_FILE}")
            print("-------------------")
    else:
        print("No active agent process.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument("--agent_id", help="Agent ID for start action")
    parser.add_argument("--background", action="store_true") # OpenClaw compatibility
    args, unknown = parser.parse_known_args()

    if args.action == "start":
        start(args.agent_id)
    elif args.action == "stop":
        stop()
    elif args.action == "status":
        status()

if __name__ == "__main__":
    main()
