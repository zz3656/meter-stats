# 📊 电表统计 — Meter Stats

> 面向酒吧工程部的电表数据管理工具。4 表抄表、充值、月度/年度报表、物品借还、申购、值班工作记录,三级权限。Docker 一键部署,浏览器直接访问。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![Image Size](https://img.shields.io/docker/image-size/zz3656/meter-stats/latest?label=image%20size)](https://hub.docker.com/r/zz3656/meter-stats)
[![Platforms](https://img.shields.io/badge/platforms-linux%2Famd64%20%7C%20linux%2Farm64-brightgreen.svg)](https://hub.docker.com/r/zz3656/meter-stats)

---

## 🚀 快速开始

### Docker Compose(推荐)

```yaml
services:
  meter-stats:
    image: zz3656/meter-stats:latest
    container_name: meter-stats
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      - ./data:/data
    environment:
      - TZ=Asia/Shanghai
      - METER_PORT=8765
      - METER_DATA_DIR=/data
      - METER_BIND=0.0.0.0
      - METER_INITIAL_PASS=admin123
```

```bash
docker compose up -d
```

访问 **http://localhost:8765**,默认账号 `admin` / `admin123`。

### Docker Run

```bash
docker run -d --name meter-stats -p 8765:8765 \
  -v $(pwd)/data:/data \
  -e TZ=Asia/Shanghai -e METER_INITIAL_PASS=your-password \
  --restart unless-stopped \
  zz3656/meter-stats:latest
```

---

## ✨ 核心功能

- ⚡ **抄表管理** — 4 块电表独立抄表,月底水电录入(总表/分表/水表)
- 💰 **充值记录** — 4 表分别充值,实时余量预警 + 建议充值金额
- 🧮 **充值计算器** — 按预充天数自动计算需充值表读数 + 金额
- 📊 **报表分析** — 每日趋势 / 月度报告 / 水电月报 / 年度汇总
- 📦 **物品借还** — 借出/归还流水,支持部分归还
- 🛒 **申购管理** — 申购 → 确认购买 → 自动入库
- 🔧 **值班工作记录** — 报修 + 处理各一条记录,支持图片上传与预览
- 🔐 **三级权限** — 员工 / 主管 / 管理员
- 💾 **自动备份** — 启动时每日备份,可配置保留天数

---

## 📋 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TZ` | `Asia/Shanghai` | 时区 |
| `METER_PORT` | `8765` | 服务端口 |
| `METER_BIND` | `0.0.0.0` | 监听地址 |
| `METER_DATA_DIR` | `/data` | 数据持久化目录 |
| `METER_INITIAL_ADMIN` | `admin` | 初始管理员用户名 |
| `METER_INITIAL_PASS` | `admin123` | 初始管理员密码(**首次生效**) |
| `METER_BACKUP_DIR` | `backup` | 备份目录(相对 `METER_DATA_DIR`) |
| `METER_IMAGE_DIR` | `images` | 图片目录(相对 `METER_DATA_DIR`) |

---

## 🔄 升级

```bash
docker compose down && docker compose up -d
```

---

## 📄 许可证

[MIT License](https://opensource.org/licenses/MIT)

## 更新历史

## 📦 MeterStats v0.1.0

提交 `9747dfb`

**升级 Docker 容器**:
```bash
docker compose pull
docker compose up -d
```


- 添加 CSV 模板下载功能 — - 后端新增 GET /api/import/template?model=<name>，返回对应模型的表头 + 示例行 / - 前端导入区增加'下载模板'按钮
- 恢复流程直接弹文件选择器 + 支持 zip 备份上传 — - pickBackupDir 在浏览器/Docker 环境下,原本需要先弹一个确认模态框 / (showBrowserBackupPicker) → 用户点「
- 录入集成+侧栏重构+UI统一+移动端适配 — - 每个记录页面在 header 加 ➕ 新增按钮(弹窗与侧栏录入共用 submitXxxAdd(source) 函数) / - 抄表/水电弹窗合并为带 Tab
- 值班录入新增故障区域字段 — - 值班录入表单新增「故障区域」输入框(选填,如:1#大厅、2#消防) / - 工作记录表格新增「故障区域」列展示 / - 后端 duty.
- 完善借出归还 — 新增历史记录表与归还弹窗 — - 物品记录页面新增「借出 / 归还 记录」表格,展示每次借出和后续归还情况 / - 归还流程从简单的二次确认弹窗改为完整弹窗:不要求借出人,可填归还数量(默认
- 物品记录新增借出和归还功能 — - handlers/items.
- 新增值班录入和工作记录功能 — - 新增 handlers/duty.

### 🐛 问题修复

- ensure DATA_PATHS includes readings_water and add Docker data diagnostics — - Add 'readings_water' to DATA_PATHS in app_handler.
- url.lastPath → url.lastPathComponent — Swift URL 类型的属性名是 lastPathComponent,不是 lastPath。
- 修复 macOS app 点击恢复数据不弹文件选择器 — 根因:macOS WKWebView 默认不实现 WKUIDelegate,任何 <input type="file"> / 的 .
- 注入 ?v=<token> 绕过 Cloudflare CDN 缓存旧版 app.js — 根因:Cloudflare CDN 默认缓存 .
- 修复 fetchSnapshot/admin 恢复后页面不刷新导致用户看不到数据 — 两个相关 bug: / - fetchSnapshot 成功路径只写 localStorage 缓存,未赋值全局 / CURRENT_READINGS / CU
- build-dmg shell 步骤改用 $version 取版本号($VERSION 为空) — 之前 $GITHUB_ENV 写入的是 'version=0.
- 修正 build-dmg release artifact 文件名缺失版本号 — ${{ env.
- 手动备份恢复数据到 docker 不生效 — 根因: / 1.
- 修复 Build DMG 失败 + push 自动构建发布 — - 修复手动触发 Build DMG 失败:无 Apple secrets 时证书步骤无条件执行 / 导致 security import 失败。
- 修复 build-dmg.yml 工作流 — - 移除已弃用的 altool 引用 / - 使用新的 notarytool 替代 altool --notarize 公证
- 完善 build-dmg.yml 版本判断逻辑

### ♻️ 重构

- 精简 release notes 生成脚本,输出更简洁 — - 过滤噪音 commit([skip ci]、自动同步 changelog、bump version) / - 按 type 分组(subject 去重,只保
- 拆分 handlers/ + utils/, 引入认证/会话/CORS/PBKDF2 — 把原 server.

### 📖 文档

- README 添加 data/ 目录使用警告,说明不应手动修改
- 重写 README + DockerHub 描述;清理冗余文件 — - .

### ⬆️ 升级

⚠️ **建议升级**:本次包含问题修复
- 🍎 macOS:下载下方 DMG 覆盖安装
- 🐳 Docker:`docker compose pull && docker compose up -d`
- 🌐 Web:浏览器强制刷新 (`Ctrl/Cmd+Shift+R`)

---

💡 [完整代码改动](https://github.com/zz3656/meter-stats/compare/v0.1.0...9747dfb)

