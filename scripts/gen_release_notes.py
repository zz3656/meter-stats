#!/usr/bin/env python3
"""生成结构化 release notes。"""
from __future__ import annotations

import os
import re
import subprocess
import sys


def main() -> int:
    version = os.environ["VERSION"]
    sha = os.environ["SHA"]
    sha_short = sha[:7]

    # 解析上次发布点(从哪个 commit 起算新增):
    # 优先用最新 tag;无 tag 时用 HEAD~1(最近一个 commit),避免把整个历史算进去
    prev_tag = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0", "HEAD~1"],
        capture_output=True, text=True).stdout.strip()

    if prev_tag:
        rng = f"{prev_tag}..HEAD"
    else:
        prev_sha = subprocess.run(
            ["git", "rev-parse", "HEAD~1"],
            capture_output=True, text=True).stdout.strip()
        if prev_sha:
            rng = f"{prev_sha}..HEAD"
        else:
            rng = "HEAD"  # 单 commit 仓库

    # 用 %B 拿完整 body,commits 之间用 NUL 分隔
    log_raw = subprocess.run(
        ["git", "log", "--pretty=format:%H%x00%s%x00%b%x00%x00", rng],
        capture_output=True, text=True).stdout.strip("\x00")

    commits_raw = [c for c in log_raw.split("\x00\x00") if c.strip()]
    commits: list[dict] = []
    for raw in commits_raw:
        parts = raw.split("\x00")
        if len(parts) >= 3:
            commits.append({"sha": parts[0], "subject": parts[1], "body": parts[2].strip()})
        elif len(parts) == 2:
            commits.append({"sha": parts[0], "subject": parts[1], "body": ""})

    TYPE_ICON = {
        "feat": "✨", "fix": "🐛", "refactor": "♻️", "perf": "⚡",
        "docs": "📖", "chore": "🔧", "ci": "🚀", "build": "📦", "test": "✅",
    }
    TYPE_ORDER = ["feat", "fix", "perf", "refactor", "docs", "ci", "build", "test", "chore"]

    SCOPE_NORM = {
        "mac": "macos", "macos": "macos", "mac-app": "macos",
        "docker": "docker", "container": "docker",
        "web": "web", "frontend": "web",
        "deploy": "deploy", "release": "release",
        "ci": "ci", "workflow": "ci",
    }
    SCOPE_DISPLAY = {
        "web": "🌐 Web/Docker 前端",
        "macos": "🍎 macOS 原生 App",
        "docker": "🐳 Docker 部署",
        "deploy": "🚀 部署/CDN",
        "ci": "🚀 CI/CD",
        "release": "📦 Release",
    }

    buckets: dict[str, dict[str, list]] = {}
    uncategorized: list[dict] = []

    for c in commits:
        m = re.match(r"^(\w+)(\([^)]+\))?:\s*(.+)$", c["subject"])
        if m:
            t, scope, subj = m.groups()
            scope_key = scope.strip("()") if scope else ""
            scope_norm = SCOPE_NORM.get(scope_key.lower(), scope_key.lower()) if scope_key else ""
            buckets.setdefault(t, {}).setdefault(scope_norm, []).append({
                "subject": subj.strip(),
                "body": c["body"],
                "sha": c["sha"][:7],
            })
        else:
            uncategorized.append(c)

    def fmt_item(item: dict) -> str:
        lines = [f"- {item['subject']} ({item['sha']})"]
        if item["body"]:
            body_lines = item["body"].split("\n")
            impact_lines: list[str] = []
            other_lines: list[str] = []
            in_impact = False
            for bl in body_lines:
                bl_stripped = bl.strip()
                if re.match(r"^-\s*(web|macos?|docker|三端|all):", bl_stripped, re.IGNORECASE):
                    impact_lines.append(bl_stripped)
                    in_impact = True
                elif bl_stripped.startswith("-") and in_impact:
                    impact_lines.append(bl_stripped)
                elif bl_stripped:
                    other_lines.append(bl_stripped)
                    in_impact = False
            if other_lines:
                for ol in other_lines[:5]:
                    if ol.startswith("#"):
                        lines.append(f"  {ol}")
                    else:
                        lines.append(f"  > {ol}")
            if impact_lines:
                lines.append("  **影响范围**:")
                for il in impact_lines:
                    lines.append(f"  {il}")
        return "\n".join(lines)

    def section_for_type(t: str) -> str:
        icon = TYPE_ICON.get(t, "•")
        t_buckets = buckets.get(t, {})
        if not t_buckets:
            return ""
        out = [f"### {icon} {t}", ""]
        scoped = [(s, items) for s, items in t_buckets.items() if s]
        unscoped = t_buckets.get("", [])
        if scoped:
            for scope, items in sorted(scoped):
                scope_display = SCOPE_DISPLAY.get(scope, f"📦 {scope}")
                out.append(f"#### {scope_display}")
                out.append("")
                for item in items:
                    out.append(fmt_item(item))
                    out.append("")
        if unscoped:
            for item in unscoped:
                out.append(fmt_item(item))
                out.append("")
        return "\n".join(out)

    if uncategorized:
        out_uncat = ["### 📝 其他改动", ""]
        for c in uncategorized:
            out_uncat.append(f"- {c['subject']} ({c['sha'][:7]})")
            if c.get("body"):
                out_uncat.append(f"  > {c['body']}")
        uncategorized_section = "\n".join(out_uncat) + "\n"
    else:
        uncategorized_section = ""

    body_sections = ""
    for t in TYPE_ORDER:
        body_sections += section_for_type(t)
    body_sections += uncategorized_section

    upgrade_hints: list[str] = []
    if buckets.get("fix"):
        upgrade_hints.append("⚠️ **强烈建议升级**:本次包含问题修复。")
    all_scopes = {s for t in buckets.values() for s in t}
    has_web = "web" in all_scopes
    has_macos = "macos" in all_scopes
    has_docker = "docker" in all_scopes
    if has_web or has_docker:
        upgrade_hints.append("- 🌐 **Web/Docker 用户**:重启 docker 容器 `docker compose pull && docker compose up -d`,浏览器强制刷新 (`Ctrl/Cmd+Shift+R`)。")
    if has_macos:
        upgrade_hints.append("- 🍎 **macOS 用户**:下载下方 DMG 覆盖安装。")
    if not upgrade_hints:
        upgrade_hints.append("- ✅ 内部优化,无需任何操作。")

    upgrade_section = "### ⬆️ 升级指引\n\n" + "\n".join(upgrade_hints) + "\n"

    header = "\n".join([
        f"## 📦 MeterStats v{version}",
        "",
        f"> macOS + Docker + Web 三端统一部署 · 提交 `{sha_short}` · 完整改动见下方",
        "",
        "**下载**:",
        f"- 🍎 macOS: `MeterStats-{version}-macos.dmg` (下方 Assets)",
        "- 🐳 Docker: `docker pull zz3656/meter-stats:latest`",
        "",
    ])

    footer_parts = ["", "---", ""]
    if prev_tag and prev_tag != "HEAD":
        footer_parts.append(
            f"💡 完整代码改动请看 [commits 页面]"
            f"(https://github.com/zz3656/meter-stats/compare/{prev_tag}...{sha_short})"
        )
    footer = "\n".join(footer_parts)

    body = header + body_sections + upgrade_section + footer
    print(body.rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())