#!/usr/bin/env python3
"""Static sanity checks for the AnyTranslate AngelScript plugin.

Not an AngelScript parser: it checks the mechanical things that would make the
plugin fail to load or misbehave silently:

  * brace / parenthesis balance outside strings and comments
  * required plugin entry points are present
  * every ``L_*`` language table has the same length and no duplicates
  * every ``P_*`` preset table has the same length
  * every ``Host*`` API call exists in a PotPlayer API signature list
  * no duplicate top-level function definitions

The API list defaults to the checked-in ``docs/api-signatures.txt`` so the
check works on any machine (including CI). On a Windows box with PotPlayer
installed, ``--api-doc`` can point at ``<PotPlayer>\\Extension\\api.txt``, or
the script will try to detect that file automatically.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_SCRIPT = PROJECT / "plugin" / "SubtitleTranslate - AnyTranslate.as"
DEFAULT_API_DOC = PROJECT / "docs" / "api-signatures.txt"

# PotPlayer plugin contract; see docs/DESIGN.md §4.
REQUIRED_ENTRY = (
    "GetTitle",
    "GetVersion",
    "GetDesc",
    "GetLoginTitle",
    "GetLoginDesc",
    "GetUserText",
    "GetPasswordText",
    "ServerLogin",
    "ServerLogout",
    "GetSrcLangs",
    "GetDstLangs",
    "Translate",
    "OnInitialize",
    "OnFinalize",
)

ARRAY_RE = re.compile(r"array<string>\s+([A-Za-z_]\w*)\s*=\s*\{")
HOST_RE = re.compile(r"\b(Host\w+)\s*\(")
FUNC_RE = re.compile(r"(?m)^(?:string|void|bool|int|uint|array<string>)\s+(\w+)\s*\(")


def strip_code(text: str) -> str:
    """Remove // and /* */ comments and string literals, preserving structure."""
    out: list[str] = []
    i, n = 0, len(text)
    in_line = in_block = in_str = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line:
            if ch == "\n":
                in_line = False
                out.append("\n")
            else:
                out.append(" ")
            i += 1
            continue
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                out.append("  ")
                i += 2
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue
        if in_str:
            if ch == "\\":
                out.append("  ")
                i += 2
                continue
            if ch == '"':
                in_str = False
                out.append(" ")
                i += 1
                continue
            out.append(" ")
            i += 1
            continue
        if ch == "/" and nxt == "/":
            in_line = True
            out.append("  ")
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            out.append("  ")
            i += 2
            continue
        if ch == '"':
            in_str = True
            out.append(" ")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def extract_array(text: str, name: str) -> list[str]:
    m = re.search(r"array<string>\s+" + re.escape(name) + r"\s*=\s*\{(.*?)\n\};", text, re.S)
    if not m:
        raise SystemExit(f"array {name} not found")
    return re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))


def array_names(text: str) -> list[str]:
    return ARRAY_RE.findall(text)


def api_names(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return set(HOST_RE.findall(text))


def detect_api_doc() -> Path | None:
    """Best-effort detection of a local PotPlayer Extension/api.txt."""
    env = os.environ.get("POTPLAYER_HOME") or os.environ.get("POTPLAYER_DIR")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env) / "Extension" / "api.txt")

    if os.name == "nt":
        try:
            import winreg

            keys = (
                r"SOFTWARE\DAUM\PotPlayer",
                r"SOFTWARE\WOW6432Node\DAUM\PotPlayer",
            )
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for key in keys:
                    try:
                        with winreg.OpenKey(hive, key) as handle:
                            for value in ("ProgramPath", "InstallPath", "Path"):
                                try:
                                    raw, _ = winreg.QueryValueEx(handle, value)
                                except OSError:
                                    continue
                                p = Path(str(raw))
                                candidates.append(p.parent if p.is_file() else p)
                    except OSError:
                        continue
        except Exception:
            pass

    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            candidates.append(Path(base) / "DAUM" / "PotPlayer")

    for directory in candidates:
        api = directory / "Extension" / "api.txt"
        if api.is_file():
            return api
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Static checks for the AnyTranslate plugin")
    parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT, help="AngelScript file to check")
    parser.add_argument(
        "--api-doc",
        type=Path,
        default=None,
        help="Host API signature list (default: docs/api-signatures.txt, else auto-detect PotPlayer)",
    )
    parser.add_argument("--strict", action="store_true", help="fail when no API signature list is found")
    args = parser.parse_args(argv)

    script = args.script if args.script.is_absolute() else PROJECT / args.script
    if not script.exists():
        raise SystemExit(f"script not found: {script}")
    text = script.read_text(encoding="utf-8")
    code = strip_code(text)
    problems: list[str] = []

    if code.count("{") != code.count("}"):
        problems.append(f"brace mismatch: {code.count('{')} '{{' vs {code.count('}')} '}}'")
    if code.count("(") != code.count(")"):
        problems.append(f"paren mismatch: {code.count('(')} '(' vs {code.count(')')} ')'")

    for entry in REQUIRED_ENTRY:
        if not re.search(r"\b" + entry + r"\s*\(", code):
            problems.append(f"missing entry point: {entry}")

    names = array_names(text)
    language_arrays = [n for n in names if n.startswith("L_")]
    for required in ("L_CODE", "L_LABEL", "L_PROMPT"):
        if required not in language_arrays:
            problems.append(f"missing language table: {required}")
    if language_arrays:
        lengths = {}
        for name in language_arrays:
            try:
                lengths[name] = len(extract_array(text, name))
            except SystemExit:
                problems.append(f"missing language table: {name}")
        print("language tables: " + ", ".join(f"{k}={v}" for k, v in lengths.items()))
        if len(set(lengths.values())) > 1:
            problems.append(f"language table length mismatch: {lengths}")
        for name in ("L_CODE", "L_LABEL"):
            if name in lengths:
                values = extract_array(text, name)
                dupes = sorted({v for v in values if values.count(v) > 1})
                if dupes:
                    problems.append(f"duplicate {name} value(s): {dupes}")

    preset_arrays = [n for n in names if n.startswith("P_")]
    if "P_ID" not in preset_arrays:
        problems.append("missing preset table: P_ID")
    if preset_arrays:
        lengths = {}
        for name in preset_arrays:
            try:
                lengths[name] = len(extract_array(text, name))
            except SystemExit:
                problems.append(f"missing preset table: {name}")
        print("preset tables: " + ", ".join(f"{k}={v}" for k, v in lengths.items()))
        if len(set(lengths.values())) > 1:
            problems.append(f"preset table length mismatch: {lengths}")

    if args.api_doc:
        api_doc = args.api_doc if args.api_doc.is_absolute() else PROJECT / args.api_doc
    else:
        api_doc = DEFAULT_API_DOC if DEFAULT_API_DOC.is_file() else detect_api_doc()
    if api_doc and api_doc.is_file():
        known = api_names(api_doc)
        used = sorted(set(HOST_RE.findall(code)))
        unknown = [name for name in used if name not in known]
        print(f"Host API used: {len(used)}; documented in {api_doc.relative_to(PROJECT) if api_doc.is_relative_to(PROJECT) else api_doc}: {len(known)}")
        if unknown:
            problems.append(f"Host API not documented: {unknown}")
    else:
        message = "no API signature list found; skipping Host API check"
        if args.strict:
            problems.append(message)
        else:
            print(f"WARN: {message}")

    defs = FUNC_RE.findall(code)
    dup_funcs = sorted({d for d in defs if defs.count(d) > 1})
    if dup_funcs:
        problems.append(f"duplicate function definitions: {dup_funcs}")
    print(f"functions defined: {len(defs)}")

    if problems:
        print("\nFAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nOK: static checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
