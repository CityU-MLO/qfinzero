#!/bin/bash
echo "🚀 启动 QFinZero Dashboard..."
cd "$(dirname "$0")/infra/dashboard-web"
pnpm dev
