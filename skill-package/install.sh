#!/bin/bash
set -e

echo "🧬 Installing Darwin Arena Skill..."

# 1. 确定安装目录
SKILL_ROOT="$HOME/.openclaw/skills"
DARWIN_DIR="$SKILL_ROOT/darwin"

mkdir -p "$DARWIN_DIR"
echo "📂 Created directory: $DARWIN_DIR"

# 2. 从 darwinx.fun 下载文件
REPO_URL="${DARWIN_ARENA_URL:-https://www.darwinx.fun}"
# Convert wss:// to https://
REPO_URL="${REPO_URL/wss:\/\//https://}"
REPO_URL="${REPO_URL/ws:\/\//http://}"

echo "⬇️ Downloading Darwin Skill from $REPO_URL..."

# 下载核心定义
curl -sL "$REPO_URL/skill/SKILL.md" -o "$DARWIN_DIR/SKILL.md"
curl -sL "$REPO_URL/skill/darwin.py" -o "$DARWIN_DIR/darwin.py"

# 下载 Agent Core
curl -sL "$REPO_URL/skill/core.zip" -o "$DARWIN_DIR/core.zip"

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

# 4. Create 'darwin' command symlink
DARWIN_BIN="$HOME/.local/bin/darwin"
mkdir -p "$HOME/.local/bin"
cat > "$DARWIN_BIN" << 'WRAPPER'
#!/bin/bash
python3 "$HOME/.openclaw/skills/darwin/darwin.py" "$@"
WRAPPER
chmod +x "$DARWIN_BIN"

# Add to PATH if needed
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zshrc" 2>/dev/null || true
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "--------------------------------------------------"
echo "✅ Darwin Skill Installed Successfully!"
echo "--------------------------------------------------"
echo ""
echo "🚀 Quick Start:"
echo ""
echo "  darwin start --agent_id=\"MyAgent\""
echo ""
echo "📍 Commands:"
echo "  darwin start --agent_id=NAME   Start your agent"
echo "  darwin stop                    Stop running agent"
echo "  darwin status                  Check agent status"
echo "  darwin logs                    View agent logs"
echo ""
echo "--------------------------------------------------"
