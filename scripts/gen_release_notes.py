#!/usr/bin/env python3
"""生成简洁的 release notes。"""
from __future__ import annotations

import os
import re
import subprocess
import sys


# 噪音 commit 过滤:这些类型的提交不出现在 release notes 中
NOISE_SUBJECTS = [
    re.compile(r"\[skip ci\]", re.IGNORECASE),
    re.compile(r"自动同步.*changelog.*README\.Docker\.md", re.IGNORECASE),
    re.compile(r"bump\s+version", re.IGNORECASE),
]


def main() -> int:
    version = os.environ["VERSION"]
    sha = os.environ["SHA"]
    sha_short = sha[:7]

    # 解析上次发布点(只看 v* 版本标签,过滤 latest 等其它标签)
    prev_tag = subprocess.run(
        ["git", "tag", "--sort=-creatordate", "--list", "v*"],
        capture_output=True, text=True).stdout.strip().split("\n")
    prev_tag = next((t for t in prev_tag if t), "")

    if prev_tag:
        rng = f"{prev_tag}..HEAD"
    else:
        prev_sha = subprocess.run(
            ["git", "rev-parse", "HEAD~1"],
            capture_output=True, text=True).stdout.strip()
        if prev_sha:
            rng = f"{prev_sha}..HEAD"
        else:
            rng = "HEAD"

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

    # 过滤噪音 commit
    def is_noise(commit: dict) -> bool:
        subject = commit["subject"]
        # 只取 subject 第一行(避免 feat: xxx\n... 把后续行当作 subject)
        first_line = subject.split("\n")[0].strip()
        for pat in NOISE_SUBJECTS:
            if pat.search(first_line):
                return True
        return False

    commits = [c for c in commits if not is_noise(c)]

    TYPE_ICON = {
        "feat": "✨", "fix": "🐛", "refactor": "♻️", "perf": "⚡",
        "docs": "📖", "chore": "🔧", "ci": "🚀", "build": "📦", "test": "✅",
    }
    TYPE_ORDER = ["feat", "fix", "perf", "refactor", "ci", "build", "test", "docs", "chore"]
    TYPE_LABEL = {
        "feat": "新功能", "fix": "问题修复", "perf": "性能优化",
        "refactor": "重构", "ci": "CI/CD", "build": "构建",
        "test": "测试", "docs": "文档", "chore": "杂项",
    }

    # 从 body 提取简短描述(首个以 - 或汉字开头的行,不超 80 字)
    def short_desc(body: str, subject: str) -> str:
        if not body:
            return ""
        lines: list[str] = []
        for line in body.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            lines.append(stripped)
            if len(lines) >= 3:  # 只取前 3 行
                break
        text = " / ".join(lines)
        # 只保留第一句(中英文句号分号)
        m = re.match(r"^(.+?[\.\u3002;\uff1b])", text)
        if m:
            text = m.group(1)
        return text.strip()[:80]

    # 把所有 commits 按类型归类(每类内部去重:同 subject 只保留最新一条)
    buckets: dict[str, dict[str, str]] = {}  # {type: {subject: short_desc}}
    uncategorized: list[str] = []  # 不符合 type: 格式的 subject

    for c in commits:
        # subject 取首行(去掉 \n 后面的内容)
        subject = c["subject"].split("\n")[0].strip()
        m = re.match(r"^(\w+)(\([^)]+\))?:\s*(.+)$", subject)
        if m:
            t = m.group(1)
            subj = m.group(3).strip()
            desc = short_desc(c["body"], subject)
            if t not in buckets:
                buckets[t] = {}
            # 去重:同 subject 只保留第一个(最新)
            if subj not in buckets[t]:
                buckets[t][subj] = desc
        else:
            uncategorized.append(subject)

    sections: list[str] = []
    for t in TYPE_ORDER:
        if t not in buckets:
            continue
        icon = TYPE_ICON.get(t, "•")
        label = TYPE_LABEL.get(t, t)
        sections.append(f"### {icon} {label}")
        sections.append("")
        for subj, desc in buckets[t].items():
            if desc and desc != subj:
                sections.append(f"- {subj} — {desc}")
            else:
                sections.append(f"- {subj}")
        sections.append("")

    # 过滤掉只含空格的有效 subject
    uncategorized = [s for s in uncategorized if s.strip()]
    if uncategorized:
        sections.append("### 📝 其他")
        sections.append("")
        for s in uncategorized[:10]:
            sections.append(f"- {s}")
        sections.append("")

    body_sections = "\n".join(sections).rstrip()

    # 升级提示
    upgrade_hints: list[str] = []
    if "fix" in buckets:
        upgrade_hints.append("⚠️ **建议升级**:本次包含问题修复")
    upgrade_hints.append("- 🍎 macOS:下载下方 DMG 覆盖安装")
    upgrade_hints.append("- 🐳 Docker:`docker compose pull && docker compose up -d`")
    upgrade_hints.append("- 🌐 Web:浏览器强制刷新 (`Ctrl/Cmd+Shift+R`)")

    upgrade_section = "### ⬆️ 升级\n\n" + "\n".join(upgrade_hints) + "\n"

    header = "\n".join([
        f"## 📦 MeterStats v{version}",
        "",
        f"提交 `{sha_short}`",
        "",
        "**下载**:",
        f"- 🍎 macOS: `MeterStats-{version}-macos.dmg` (下方 Assets)",
        "- 🐳 Docker: `docker pull zz3656/meter-stats:latest`",
        "",
    ])

    footer_parts = ["", "---", ""]
    if prev_tag and prev_tag != "HEAD":
        footer_parts.append(
            f"💡 [完整代码改动](https://github.com/zz3656/meter-stats/compare/{prev_tag}...{sha_short})"
        )
    footer = "\n".join(footer_parts)

    body = header + body_sections + "\n\n" + upgrade_section + footer
    print(body.rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
