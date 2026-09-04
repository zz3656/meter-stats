# ============================================================
# 电表统计 — Docker 部署
# ============================================================
# 构建:  docker build -f docker/Dockerfile -t zz3656/meter-stats .
# 运行:  docker run -d --name meter-stats \
#           -p 8765:8765 \
#           -v meter-data:/data \
#           -e METER_INITIAL_PASS=your-secure-password \
#           zz3656/meter-stats
# ============================================================

FROM python:3.11-slim

LABEL maintainer="meter-team"
LABEL description="场所工程部电表用量统计工具 — Web 服务"

# 创建非 root 用户运行应用
RUN groupadd -r app && useradd -r -g app -d /data -s /sbin/nologin app

# 设置工作目录
WORKDIR /app

# 复制所有应用文件（从 MeterStats/）
COPY MeterStats/*.py ./
COPY MeterStats/*.html ./
COPY MeterStats/*.css ./
COPY MeterStats/*.js ./
COPY MeterStats/*.svg ./
COPY MeterStats/*.png ./
# VERSION 文件无后缀,glob 不匹配,单独复制(server.py 启动时需要)
COPY MeterStats/VERSION ./
COPY MeterStats/handlers/ handlers/
COPY MeterStats/utils/ utils/

# 复制 entrypoint 脚本
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 设置所有权
RUN chown -R app:app /app

# 创建数据目录
RUN mkdir -p /data && chown -R app:app /data

# 暴露端口
EXPOSE 8765

# 健康检查（每 30 秒检查一次，5 秒超时）
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/api/health', timeout=3).close()" || exit 1

# 以 root 身份启动 entrypoint，由它处理权限切换后运行服务
ENTRYPOINT ["/entrypoint.sh"]
