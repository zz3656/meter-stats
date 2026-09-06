#!/bin/bash
# 启动脚本：确保 /data 目录权限正确后启动服务
set -e

# 设置时区（POSIX 标准 TZ 环境变量，默认 Asia/Shanghai）
export TZ="${TZ:-Asia/Shanghai}"

# 标记 Docker 环境(handlers/admin.py 据此禁用 backup_dir UI 编辑)。
# 优先用显式环境变量,否则用 /.dockerenv 检测(更稳,无需用户正确设 env)。
if [ -z "$METER_DOCKER" ]; then
    if [ -f /.dockerenv ]; then
        export METER_DOCKER=1
    fi
fi

# Docker 环境下备份目录和环境变量 METER_BACKUP_DIR
# 默认值: /data/backup(相对于 /data)
if [ -z "$METER_BACKUP_DIR" ]; then
    export METER_BACKUP_DIR=backup
fi

# Docker 环境下图片目录环境变量 METER_IMAGE_DIR
# 默认值: /data/images
if [ -z "$METER_IMAGE_DIR" ]; then
    export METER_IMAGE_DIR=/data/images
fi

# 修复 /data 目录权限
if [ -d /data ]; then
    chown -R app:app /data 2>/dev/null || true
    chmod -R 755 /data 2>/dev/null || true
fi

# 验证 app 用户可写入 /data
touch /data/.write_test 2>/dev/null || {
    echo "FATAL: /data directory is not writable by app user!" >&2
    echo "Directory permissions: $(ls -ld /data 2>/dev/null || echo 'not found')" >&2
    echo "Current user: $(whoami) $(id)" >&2
    exit 1
}
rm -f /data/.write_test

# 切换到 app 用户运行服务
# python:3.11-slim includes runuser (shadow) and su-exec (busybox)
if command -v su-exec &>/dev/null; then
    exec su-exec app python3 server.py
elif command -v runuser &>/dev/null; then
    exec runuser -u app -- python3 server.py
elif command -v gosu &>/dev/null; then
    exec gosu app python3 server.py
else
    # 兜底：直接用当前用户运行（如果就是 app）
    exec python3 server.py
fi
