#!/bin/bash
# 一键启动：后端 (8900) + 前端 (5173)
set -e
cd "$(dirname "$0")"

if [ ! -d backend/.venv ]; then
  echo "==> 创建后端虚拟环境并安装依赖（首次约 2-5 分钟）"
  cd backend
  python3 -m venv .venv
  .venv/bin/pip install -q -U pip
  .venv/bin/pip install -q -r requirements.txt
  cd ..
fi

if [ ! -d frontend/node_modules ]; then
  echo "==> 安装前端依赖"
  (cd frontend && pnpm install)
fi

echo "==> 启动后端 http://127.0.0.1:8900"
(cd backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8900) &
BE_PID=$!

echo "==> 启动前端 http://localhost:5173"
(cd frontend && pnpm run dev) &
FE_PID=$!

trap "kill $BE_PID $FE_PID 2>/dev/null" EXIT
echo "✅ 打开 http://localhost:5173 开始使用（Ctrl+C 退出）"
wait
