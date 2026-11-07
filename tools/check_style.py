#!/usr/bin/env python3
"""Style checks for the any-translate documentation.

Conventions (see docs/STYLE.md):
  * service naming: "<Name>（<deployment>）", e.g. "Ollama（本机）", "DeepSeek（云端）"
  * "本机" = runs on this machine; "本地" = locally stored data/files
  * Chinese prose uses full-width parentheses （）; code/commands use ASCII ( )
  * one ASCII space between Chinese and Latin/digits, outside code
  * one term set: API Key / 配置串（spec）/ 预设（preset）/ 请求地址（endpoint）

Files are discovered (README, CHANGELOG, docs/**/*.md, plugin/*.as) so adding a
new document does not require editing this script. STYLE.md quotes the banned
examples on purpose, so it is exempt from the banned-phrase rules.

Exit code 0 = clean, 1 = violations found.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
BANNED_EXEMPT = {"STYLE.md"}

# (pattern, hint) — keep in sync with docs/STYLE.md.
BANNED = (
    (r"本机 Ollama", "改用“Ollama（本机）”（表格）或“本机部署的 Ollama”（正文）"),
    (r"本地 Ollama", "改用“Ollama（本机）”或“本机部署的 Ollama”"),
    (r"本地服务", "改用“本机服务”（指运行在本机的服务）"),
    (r"本地 mock", "改用“本机 mock”"),
    (r"完整 endpoint", "改用“完整请求地址”"),
    (r"服务端默认）", "表格模型列统一写“服务端默认模型”"),
    (r"(?<!用户)自填", "统一写“用户自填”"),
    (r"LM Studio\(本机\)", "中文括号统一用全角：“LM Studio（本机）”"),
)

CJK = r"\u4e00-\u9fff"
SPACING = (
    (rf"({CJK})([A-Za-z0-9])", "中英文/数字之间缺空格"),
    (rf"([A-Za-z0-9])({CJK})", "中英文/数字之间缺空格"),
)


def discover_files(root: Path) -> list[Path]:
    files = [root / "README.md", root / "CHANGELOG.md"]
    if (root / "docs").is_dir():
        files.extend(sorted((root / "docs").rglob("*.md")))
    if (root / "plugin").is_dir():
        files.extend(sorted((root / "plugin").glob("*.as")))
    return [path for path in files if path.is_file()]


def mask_code(text: str) -> str:
    """Blank out fenced code blocks and inline code, keep line numbers."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        if in_fence:
            out.append("")
            continue
        out.append(re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line))
    return "\n".join(out)


def check_file(path: Path, root: Path) -> list[str]:
    issues: list[str] = []
    text = path.read_text(encoding="utf-8")
    masked = mask_code(text)
    raw_lines = text.splitlines()
    label = path.relative_to(root).as_posix()

    if path.name not in BANNED_EXEMPT:
        for pattern, hint in BANNED:
            for match in re.finditer(pattern, masked):
                line_no = masked[: match.start()].count("\n") + 1
                issues.append(f"{label}:{line_no}: 命中“{match.group(0)}” → {hint}")

    for pattern, hint in SPACING:
        for match in re.finditer(pattern, masked):
            line_no = masked[: match.start()].count("\n") + 1
            snippet = raw_lines[line_no - 1].strip()
            issues.append(f"{label}:{line_no}: {hint}（…{match.group(0)}…）: {snippet[:90]}")

    for line_no, line in enumerate(raw_lines, 1):
        if line != line.rstrip():
            issues.append(f"{label}:{line_no}: 行尾多余空格")

    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check AnyTranslate documentation style")
    parser.add_argument("--root", type=Path, default=PROJECT, help="repository root (default: project root)")
    parser.add_argument("--list", action="store_true", help="print the files that would be checked")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    files = discover_files(root)
    if args.list:
        for path in files:
            print(path.relative_to(root).as_posix())
        return 0

    issues: list[str] = []
    for path in files:
        issues.extend(check_file(path, root))

    if issues:
        print(f"FAIL: {len(issues)} 处样式问题\n")
        for issue in issues:
            print("  - " + issue)
        return 1

    print(f"OK: 文档样式检查通过（{len(files)} 个文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
