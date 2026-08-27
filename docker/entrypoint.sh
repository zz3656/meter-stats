#!/bin/bash
# 启动脚本：确保 /data 目录权限正确后启动服务
set -e

# 修复 /data 目录权限（以 root 身份运行 entrypoint）
if [ -d /data ]; then
    chown -R app:app /data 2>/dev/null || true
fi

# 验证 app 用户可写入 /data
touch /data/.write_test 2>/dev/null || {
    echo "FATAL: /data directory is not writable by app user!" >&2
    echo "Directory permissions: $(ls -ld /data 2>/dev/null || echo 'not found')" >&2
    exit 1
}
rm -f /data/.write_test

# 设置时区（POSIX 标准 TZ 环境变量，默认 Asia/Shanghai）
export TZ="${TZ:-Asia/Shanghai}"

# 切换到 app 用户运行（python 镜像通常包含 /usr/bin/runuser 或 /usr/bin/su-exec）
# 尝试多种切换方式
if command -v runuser &>/dev/null; then
    exec runuser -u app -- python3 server.py
elif command -v su-exec &>/dev/null; then
    exec su-exec app python3 server.py
elif command -v gosu &>/dev/null; then
    exec gosu app python3 server.py
else
    # 兜底：直接用当前用户运行（如果就是 app）
    exec python3 server.py
fi
