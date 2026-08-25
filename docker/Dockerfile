# ============================================================
# 林卡电表统计 — Docker 部署
# ============================================================
# 构建:  docker build -t zz3656/linclub-electricity-stats .
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

# 复制所有应用文件
COPY *.py ./
COPY *.html ./
COPY *.css ./
COPY *.js ./
COPY handlers/ handlers/
COPY utils/ utils/

# 设置所有权
RUN chown -R linclub:linclub /app

# 创建数据目录
RUN mkdir -p /data && chown linclub:linclub /data

# 切换到非 root 用户
USER linclub

# 暴露端口
EXPOSE 8765

# 健康检查（每 30 秒检查一次）
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/api/health')" || exit 1

# 启动命令
CMD ["python3", "server.py"]
