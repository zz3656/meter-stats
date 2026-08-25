# ============================================================
# 林卡电表统计 — Docker 部署
# ============================================================
# 构建:  docker build -t linca/electricity-stats .
# 运行:  docker run -d --name linca \
#           -p 8765:8765 \
#           -v linca-data:/data \
#           -e LINCA_INITIAL_PASS=your-secure-password \
#           linca/electricity-stats
# ============================================================

# ---- 构建阶段（无） ----
# Python 标准库，无需编译步骤

FROM python:3.11-slim

LABEL maintainer="linca-team"
LABEL description="林卡酒吧工程部电表用量统计工具 — Web 服务"

# 创建非 root 用户运行应用
RUN groupadd -r linca && useradd -r -g linca -d /data -s /sbin/nologin linca

# 设置工作目录
WORKDIR /app

# 复制所有应用文件
COPY --chown=linca:linca *.py .
COPY --chown=linca:linca *.html .
COPY --chown=linca:linca *.css .
COPY --chown=linca:linca *.js  .
COPY --chown=linca:linca handlers/ handlers/
COPY --chown=linca:linca utils/  utils/

# 创建数据目录
RUN mkdir -p /data && chown linca:linca /data

# 切换到非 root 用户
USER linca

# 暴露端口
EXPOSE 8765

# 健康检查（每 30 秒检查一次）
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/api/health')" || exit 1

# 启动命令
CMD ["python3", "server.py"]
