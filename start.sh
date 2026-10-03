#!/usr/bin/env bash
#
# 一键启动：后端 (FastAPI :8011) + 前端 (Vite :5173)。
#
#   ./start.sh
#
# 固化几处踩过的坑：
#  · 必须用项目自己的 .venv（不是 anaconda —— 系统 anaconda 缺 langgraph.checkpoint.sqlite）
#  · 后端固定 :8011（本机 :8000 被另一个应用占用）
#  · CORS 已在 web/api/main.py 放行 :5173，无需额外配置
#  · Ctrl-C 一次同时关掉前后端（trap 清理后台的后端进程）
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYBIN="$ROOT/.venv/bin/python"
BACKEND_PORT=8011
FRONTEND_PORT=5173

# 1) Python venv：首次运行自动建 .venv 并装依赖（隔离于 anaconda）
if [ ! -x "$PYBIN" ]; then
  echo "▸ 首次运行：创建 .venv 并安装 Python 依赖…"
  python3 -m venv "$ROOT/.venv"
  "$PYBIN" -m pip install --upgrade pip >/dev/null
  "$PYBIN" -m pip install -r "$ROOT/requirements.txt"
fi

# 2) API key：缺 proto/.env 就从模板复制并提示填 key 后重跑
if [ ! -f "$ROOT/proto/.env" ]; then
  cp "$ROOT/proto/.env.example" "$ROOT/proto/.env"
  echo "⚠ 已生成 proto/.env —— 请填入 ANTHROPIC_API_KEY（Finnhub 可选）后重新运行 ./start.sh"
  exit 1
fi

# 3) 前端依赖：缺 node_modules 就 npm install
if [ ! -d "$ROOT/web/frontend/node_modules" ]; then
  echo "▸ 安装前端依赖…"
  ( cd "$ROOT/web/frontend" && npm install )
fi

# 4) 起后端（后台），Ctrl-C 时一并清理
echo "▸ 后端启动中：http://127.0.0.1:${BACKEND_PORT}"
"$PYBIN" -m uvicorn web.api.main:app --port "$BACKEND_PORT" &
BACKEND_PID=$!
trap 'echo; echo "▸ 关闭后端 (pid $BACKEND_PID)…"; kill "$BACKEND_PID" 2>/dev/null || true' EXIT INT TERM

# 5) 起前端（前台）。退出前台即触发 trap 关后端。
echo "▸ 前端启动中：http://localhost:${FRONTEND_PORT}"
echo "  （Ctrl-C 同时停止前后端）"
cd "$ROOT/web/frontend"
npm run dev
