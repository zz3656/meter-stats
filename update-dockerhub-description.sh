#!/bin/bash
# ============================================================
# 林卡电表统计 — 更新 Docker Hub 仓库描述（Overview / About）
# 用法:  ./update-dockerhub-description.sh [ACCESS_TOKEN]
# 要求:  Docker Hub Personal Access Token (dckr_pat_xxxxxxxx)
# ============================================================

set -e

TOKEN="${1:-$DOCKERHUB_TOKEN}"
USERNAME="zz3656"
REPO="linclub-electricity-stats"

if [ -z "$TOKEN" ]; then
  echo "❌ 未提供 Docker Hub Access Token"
  echo "   用法: $0 dckr_pat_xxxxxxxx"
  echo "   或设置环境变量: DOCKERHUB_TOKEN=dckr_pat_xxxxxxxx"
  exit 1
fi

echo "=================================================="
echo " 更新 Docker Hub 仓库描述"
echo "=================================================="
echo ""
echo "仓库: ${USERNAME}/${REPO}"
echo ""

python3 - "$TOKEN" << 'PYEOF'
import json, sys, os, urllib.request, urllib.error

TOKEN = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DOCKERHUB_TOKEN", "")
USERNAME = "zz3656"
REPO = "linclub-electricity-stats"

# Docker Hub API limits:
# - description field: max 100 bytes
# - full_description: no strict limit
SHORT_DESC = "林卡酒吧工程部电表统计工具 · Web服务"
FULL_DESC = """# 林卡电表统计 — Linclub Electricity Stats

> 酒吧/场所工程部电表用量统计工具。支持 macOS 桌面应用和 Docker Web 服务两种部署方式。

## ✨ 功能特性

| 功能 | 说明 |
|---|---|
| ⚡ 电表管理 | 4 块电表独立抄表读数 |
| 💰 充值记录 | 按表充值，支持备注 |
| 🧾 月度报告 | 逐日逐表用电计算 |
| 📊 年度汇总 | 12 个月数据汇总 |
| 🔧 物品管理 | 库存 CRUD |
| 📋 申购管理 | 申购 → 入库流转 |
| 🔐 用户权限 | 三级权限管理 |
| 💾 自动备份 | 每日自动备份 |

## 🚀 快速开始

```bash
docker run -d \\
  --name linclub \\
  -p 8765:8765 \\
  -v ./data:/data \\
  -e LINCLUB_INITIAL_PASS=your-password \\
  -e TZ=Asia/Shanghai \\
  zz3656/linclub-electricity-stats:latest
```

## 默认账户

| 用户名 | 密码 | 角色 |
|---|---|---|
| admin | admin123 | 管理员 |

**⚠️ 请首次登录后立即修改密码！**
"""

# Step 1: Login to Docker Hub to get JWT for hub operations
login_url = "https://hub.docker.com/v2/users/login/"
payload = json.dumps({"username": USERNAME, "password": TOKEN}).encode()

req = urllib.request.Request(login_url, data=payload,
    headers={"Content-Type": "application/json"}, method="POST")

try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        jwt = data.get("token", data.get("jwt", ""))
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"❌ Docker Hub 登录失败 (HTTP {e.code}): {body[:200]}")
    sys.exit(1)

if not jwt:
    print("❌ 未获取到 JWT token")
    sys.exit(1)

# Step 2: PATCH repository description
desc_data = {
    "description": SHORT_DESC,
    "full_description": FULL_DESC
}

desc_payload = json.dumps(desc_data, ensure_ascii=False).encode()
api_url = f"https://hub.docker.com/v2/repositories/{USERNAME}/{REPO}/"

req2 = urllib.request.Request(api_url, data=desc_payload,
    headers={"Authorization": "JWT " + jwt, "Content-Type": "application/json"},
    method="PATCH")

try:
    with urllib.request.urlopen(req2, timeout=30) as resp2:
        code = resp2.getcode()
        result = json.loads(resp2.read())
        if code == 200:
            print("✅ Docker Hub 仓库描述已更新！")
            print(f"   简介: {result.get('description', '')}")
            print(f"   详细介绍: {result.get('full_description', '')[:80]}...")
            print(f"   访问: https://hub.docker.com/r/{USERNAME}/{result.get('name', REPO)}")
        else:
            print(f"⚠️ 意外状态码: {code}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"❌ 更新失败 (HTTP {e.code}): {body[:300]}")
    sys.exit(1)
PYEOF

echo ""
