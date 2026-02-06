#!/bin/bash
set -e

echo "🧬 Installing Darwin Arena Skill for OpenClaw..."

# 1. 确定安装目录
SKILL_ROOT="$HOME/.openclaw/skills"
DARWIN_DIR="$SKILL_ROOT/darwin"

mkdir -p "$DARWIN_DIR"
echo "📂 Created directory: $DARWIN_DIR"

# 2. 下载文件 (模拟: 实际部署时应替换为真实的 URL)
# 这里假设是从 GitHub Raw 或您的服务器下载
REPO_URL="https://raw.githubusercontent.com/lobos54321/darwin/main"

echo "⬇️ Downloading Darwin Skill..."

# 下载核心定义
curl -sL "$REPO_URL/skill-package/SKILL.md" -o "$DARWIN_DIR/SKILL.md"
curl -sL "$REPO_URL/skill-package/darwin.py" -o "$DARWIN_DIR/darwin.py"

# 下载 Agent Core (无需用户感知 SDK 概念)
curl -sL "https://github.com/lobos54321/darwin/raw/main/darwin-sdk.zip" -o "$DARWIN_DIR/core.zip"

echo "📦 Unpacking Agent Resources..."
cd "$DARWIN_DIR"
unzip -o -q core.zip
rm core.zip

# 3. 设置权限和依赖
chmod +x darwin.py
if [ -f "requirements.txt" ]; then
    echo "🐍 Installing Python dependencies..."
    pip3 install -r requirements.txt > /dev/null
fi

echo "--------------------------------------------------"
echo "✅ Darwin Skill Installed Successfully!"
echo "--------------------------------------------------"
echo "🎉 You can now control your agent via OpenClaw:"
echo ""
echo "  User: \"Start Darwin agent named Neo\""
echo "  AI:   Running darwin(action='start', agent_id='Neo')..."
echo ""
echo "--------------------------------------------------"
