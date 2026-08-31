#!/usr/bin/env python3
"""把 release notes 追加到 README.Docker.md,触发 sync-readme-to-dockerhub.yml。

用法:
  python3 scripts/sync_docker_readme.py <release-notes-file> <version>

读取 <release-notes-file>(GitHub Release notes markdown),提取最新一个 release block,
追加到 README.Docker.md 末尾的"## 更新历史"区块,替换掉旧的 changelog。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


def main(notes_path: str, version: str) -> int:
    notes = Path(notes_path).read_text(encoding="utf-8")
    readme_path = Path("README.Docker.md")
    if readme_path.exists():
        original = readme_path.read_text(encoding="utf-8")
    else:
        original = ""

    split_marker = "## 更新历史"
    if split_marker in original:
        original = original.split(split_marker)[0].rstrip()

    # 提取最新 release block(从"## 📦 MeterStats v"开头的整段,直到下一个 ## 📦 或文件末尾)
    version_blocks = re.findall(
        r"## 📦 MeterStats v[^\n]+\n(?:(?!## 📦 MeterStats v).)*",
        notes, re.DOTALL
    )
    new_block = version_blocks[-1] if version_blocks else notes

    # 简化下载指引(从 docker 视角)
    new_block = re.sub(
        r"\*\*下载\*\*:.*?(?=\n\n|\Z)",
        "**升级 Docker 容器**:\n```bash\n"
        "docker compose pull\n"
        "docker compose up -d\n"
        "```\n",
        new_block, count=1, flags=re.DOTALL,
    )

    new_readme = original.rstrip() + "\n\n" + split_marker + "\n\n" + new_block + "\n"
    readme_path.write_text(new_readme, encoding="utf-8")
    print(f"✅ README.Docker.md 已更新(共 {len(new_readme)} 字符)")

    # 自动 commit 触发 sync-readme-to-dockerhub.yml
    github_actor = os.environ.get("GITHUB_ACTOR", "github-actions[bot]")
    subprocess.run(["git", "config", "user.email", f"{github_actor}@users.noreply.github.com"], check=True)
    subprocess.run(["git", "config", "user.name", github_actor], check=True)
    subprocess.run(["git", "add", "README.Docker.md"], check=True)
    commit_msg = f"docs: 自动同步 v{version} changelog 到 README.Docker.md [skip ci]"
    result = subprocess.run(["git", "commit", "-m", commit_msg], check=False)
    if result.returncode == 0:
        subprocess.run(["git", "push", "origin", "main"], check=False)
        print(f"✅ README.Docker.md 已 commit 并 push,触发 sync-readme-to-dockerhub.yml")
    else:
        print("ℹ️ README.Docker.md 无变更,无需 commit")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"用法: {sys.argv[0]} <release-notes-file> <version>", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2]))