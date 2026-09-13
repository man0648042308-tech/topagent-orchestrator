#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${TOPAGENT_PROJECT_DIR:-$HOME/AI-Project-TopAgent}"

echo "TopAgent v3 setup"
if [ ! -f "$PROJECT_DIR/CLAUDE.md" ]; then
  git clone https://github.com/man0648042308-tech/AI-Project-TopAgent.git "$PROJECT_DIR"
fi
cd "$PROJECT_DIR"

command -v python >/dev/null || { echo "Python 3 is required"; exit 1; }
command -v claude >/dev/null || npm install -g @anthropic-ai/claude-code

python -m topagent init

echo "No API key is embedded in this installer."
echo "Set keys as environment variables or, on Windows, run:"
echo "  python -m topagent secrets set DASHSCOPE_API_KEY"
echo "Start dashboard: python -m topagent serve"
