# ============================================================
# 林卡电表统计 — Docker 部署
# ============================================================
# 构建:  docker build -f docker/Dockerfile -t zz3656/linclub-electricity-stats .
# 运行:  docker run -d --name linclub \
#           -p 8765:8765 \
#           -v linclub-data:/data \
#           -e LINCLUB_INITIAL_PASS=your-secure-password \
#           zz3656/linclub-electricity-stats
# ============================================================

FROM python:3.11-slim

LABEL maintainer="linclub-team"
LABEL description="林卡酒吧工程部电表用量统计工具 — Web 服务"

# 创建非 root 用户运行应用
RUN groupadd -r linclub && useradd -r -g linclub -d /data -s /sbin/nologin linclub

# 设置工作目录
WORKDIR /app

# 复制所有应用文件（从 Sources/Linclub/Resources/）
COPY Sources/Linclub/Resources/*.py ./
COPY Sources/Linclub/Resources/*.html ./
COPY Sources/Linclub/Resources/*.css ./
COPY Sources/Linclub/Resources/*.js ./
COPY Sources/Linclub/Resources/*.svg ./
COPY Sources/Linclub/Resources/*.png ./
COPY Sources/Linclub/Resources/handlers/ handlers/
COPY Sources/Linclub/Resources/utils/ utils/

# 复制 entrypoint 脚本
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 设置所有权
RUN chown -R linclub:linclub /app

# 创建数据目录
RUN mkdir -p /data && chown -R linclub:linclub /data

# 暴露端口
EXPOSE 8765

# 健康检查（每 30 秒检查一次，5 秒超时）
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/api/health', timeout=3).close()" || exit 1

# 以 root 身份启动 entrypoint，由它处理权限切换
ENTRYPOINT ["/entrypoint.sh"]
