#!/bin/bash
# 启动脚本：修复 /data 目录权限后启动服务
set -e

# 如果 /data 被挂载（容器内变为非空或存在），确保 linclub 用户可写
if [ -d /data ]; then
    chown -R linclub:linclub /data 2>/dev/null || true
fi

exec python3 server.py
