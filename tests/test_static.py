#!/usr/bin/env python3
"""Static contract checks for the AnyTranslate AngelScript plugin.

Run as part of the normal test suite:

    python -m unittest discover -s tests -v
    python -m unittest tests.test_static -v

Not an AngelScript parser. It checks the mechanical things that would make the
plugin fail to load or misbehave silently:

  * brace / parenthesis balance outside strings and comments
  * required plugin entry points are present
  * every ``L_*`` language table has the same length and no duplicates
  * every ``P_*`` preset table has the same length
  * the two ``STYLE_*`` tables have the same length and no duplicates
  * every ``Host*`` API call exists in a PotPlayer API signature list
  * the PowerShell installer keeps its UTF-8 BOM for Windows PowerShell 5.1
  * the AngelScript reserved word ``out`` is not used as an identifier
  * no duplicate top-level function definitions

The API list defaults to the checked-in ``docs/api-signatures.txt`` so the
check works on any machine (including CI). On a Windows box with PotPlayer
installed, the script also tries to detect ``<PotPlayer>\\Extension\\api.txt``.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from support import reference_impl  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_SCRIPT = PROJECT / "plugin" / "SubtitleTranslate - AnyTranslate.as"
DEFAULT_API_DOC = PROJECT / "docs" / "api-signatures.txt"

# PotPlayer plugin contract; see docs/design.md §4.
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
    match = re.search(r"array<string>\s+" + re.escape(name) + r"\s*=\s*\{(.*?)\n\};", text, re.S)
    if not match:
        raise ValueError(name)
    return re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1))


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
                                path = Path(str(raw))
                                candidates.append(path.parent if path.is_file() else path)
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


def collect_problems() -> list[str]:
    script = DEFAULT_SCRIPT
    if not script.exists():
        return [f"script not found: {script}"]

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

    title_tags = ("CP936", "CP950", "CP949", "CP932", "CP0")
    title_positions = []
    for tag in title_tags:
        marker = "{$" + tag + "="
        if marker not in text:
            problems.append(f"GetTitle missing {tag} branch")
        else:
            title_positions.append(text.find(marker))
    if len(title_positions) == len(title_tags) and title_positions != sorted(title_positions):
        problems.append(
            "GetTitle language order must be CP936, CP950, CP949, CP932, CP0"
        )

    names = ARRAY_RE.findall(text)
    language_arrays = [name for name in names if name.startswith("L_")]
    for required in ("L_CODE", "L_LABEL", "L_PROMPT"):
        if required not in language_arrays:
            problems.append(f"missing language table: {required}")
    if language_arrays:
        lengths: dict[str, int] = {}
        for name in language_arrays:
            try:
                lengths[name] = len(extract_array(text, name))
            except ValueError:
                problems.append(f"missing language table: {name}")
        if len(set(lengths.values())) > 1:
            problems.append(f"language table length mismatch: {lengths}")
        for name in ("L_CODE", "L_LABEL"):
            if name in lengths:
                try:
                    values = extract_array(text, name)
                except ValueError:
                    continue
                dupes = sorted({value for value in values if values.count(value) > 1})
                if dupes:
                    problems.append(f"duplicate {name} value(s): {dupes}")

    preset_arrays = [name for name in names if name.startswith("P_")]
    if "P_ID" not in preset_arrays:
        problems.append("missing preset table: P_ID")
    if preset_arrays:
        lengths = {}
        for name in preset_arrays:
            try:
                lengths[name] = len(extract_array(text, name))
            except ValueError:
                problems.append(f"missing preset table: {name}")
        if len(set(lengths.values())) > 1:
            problems.append(f"preset table length mismatch: {lengths}")
        try:
            preset_ids = extract_array(text, "P_ID")
            preset_models = extract_array(text, "P_MODEL")
        except ValueError:
            preset_ids = []
            preset_models = []
        local_prefix = ["vllm", "sglang", "lmstudio", "ollama"]
        if preset_ids[:4] != local_prefix:
            problems.append(f"P_ID local prefix mismatch: {preset_ids[:4]}")
        for index, preset in enumerate(local_prefix):
            if index < len(preset_models) and preset_models[index] != "":
                problems.append(f"P_MODEL must stay empty for {preset}")

    style_arrays = [name for name in names if name.startswith("STYLE_")]
    for required in ("STYLE_IDS", "STYLE_RULES"):
        if required not in style_arrays:
            problems.append(f"missing style table: {required}")
    if style_arrays:
        lengths = {}
        for name in style_arrays:
            try:
                lengths[name] = len(extract_array(text, name))
            except ValueError:
                problems.append(f"missing style table: {name}")
        if len(set(lengths.values())) > 1:
            problems.append(f"style table length mismatch: {lengths}")
        for name in ("STYLE_IDS", "STYLE_RULES"):
            if name in lengths:
                try:
                    values = extract_array(text, name)
                except ValueError:
                    continue
                dupes = sorted({value for value in values if values.count(value) > 1})
                if dupes:
                    problems.append(f"duplicate {name} value(s): {dupes}")
        try:
            style_ids = extract_array(text, "STYLE_IDS")
            style_rules = extract_array(text, "STYLE_RULES")
            if style_ids != list(reference_impl.STYLE_ORDER):
                problems.append("STYLE_IDS 与 reference_impl.STYLE_ORDER 不一致")
            expected_rules = [reference_impl.STYLE_RULES[name] for name in style_ids if name in reference_impl.STYLE_RULES]
            if style_rules != expected_rules:
                problems.append("STYLE_RULES 与 reference_impl.STYLE_RULES 不一致")
        except (ValueError, KeyError):
            pass

    api_doc = DEFAULT_API_DOC if DEFAULT_API_DOC.is_file() else detect_api_doc()
    if api_doc:
        used = sorted(set(HOST_RE.findall(code)))
        unknown = [name for name in used if name not in api_names(api_doc)]
        if unknown:
            problems.append(f"Host API not documented: {unknown}")

    definitions = FUNC_RE.findall(code)
    duplicate_functions = sorted({name for name in definitions if definitions.count(name) > 1})
    if duplicate_functions:
        problems.append(f"duplicate function definitions: {duplicate_functions}")

    # PotPlayer's AngelScript compiler treats out as a reserved keyword; only
    # the &out parameter / literal phrase may use it.
    for line_number, line in enumerate(code.splitlines(), 1):
        if "&out" in line or "logged out" in line:
            continue
        if re.search(r"\bout\b", line):
            problems.append(f"reserved word out at line {line_number}")

    return problems


class PluginStaticTest(unittest.TestCase):
    def test_plugin_contract(self) -> None:
        problems = collect_problems()
        installer = PROJECT / "scripts" / "install.ps1"
        if installer.exists():
            raw = installer.read_bytes()
            if not raw.startswith(b"\xef\xbb\xbf"):
                problems.append("scripts/install.ps1 must keep a UTF-8 BOM for Windows PowerShell 5.1")

        self.assertEqual(problems, [], "静态检查失败:\n" + "\n".join(f"  - {p}" for p in problems))

    def test_zh_t2s_mapping_integrity(self) -> None:
        text = DEFAULT_SCRIPT.read_text(encoding="utf-8")
        match = re.search(r'string ZH_T2S_PAIRS = "(.*?)";', text)
        self.assertIsNotNone(match, "ZH_T2S_PAIRS missing")
        raw = match.group(1).encode("utf-8")
        self.assertEqual(len(raw) % 6, 0, "ZH_T2S_PAIRS must be 3-byte char + 3-byte char pairs")
        pairs = {
            raw[i:i + 3].decode("utf-8"): raw[i + 3:i + 6].decode("utf-8")
            for i in range(0, len(raw), 6)
        }
        self.assertEqual(pairs.get("裡"), "里")
        self.assertEqual(pairs.get("這"), "这")
        self.assertEqual(pairs.get("們"), "们")

    def test_cache_key_ignores_context(self) -> None:
        """Cache identity must stay config + raw text, not selected history."""
        text = DEFAULT_SCRIPT.read_text(encoding="utf-8")
        start = text.index("string CacheKey(")
        end = text.index("int CacheFindKey", start)
        body = text[start:end]
        self.assertNotIn("g_ctx_src_sel", body)
        self.assertNotIn("g_ctx_dst_sel", body)
        self.assertIn("g_cache_scope", body)

    def test_language_tables_defined(self) -> None:
        """Guard against a referenced language table being deleted while its use remains."""
        text = DEFAULT_SCRIPT.read_text(encoding="utf-8")
        for name in ("L_CODE", "L_LABEL", "L_PROMPT", "LATIN_LANG_CODES"):
            self.assertRegex(
                text,
                rf"array<string>\s+{name}\s*=",
                f"{name} must be defined in the plugin",
            )

    def test_host_lang_writeback_in_translate(self) -> None:
        """AngelScript &in object args are copied; write-back must stay in host-called Translate."""
        text = DEFAULT_SCRIPT.read_text(encoding="utf-8")
        start = text.index("string Translate(")
        end = text.index("// 登录 / 初始化 / 语言列表", start)
        body = text[start:end]
        self.assertIn('SrcLang = "UTF8";', body)
        self.assertIn('DstLang = "UTF8";', body)

    def test_pipeline_contract(self) -> None:
        text = DEFAULT_SCRIPT.read_text(encoding="utf-8")
        for needle in (
            'contextmode',
            'contextchars',
            'glossary',
            'BuildSystemPrompt',
            'BuildContextBlock',
            'BuildBodyPipeline',
            'BuildMessagesJson',
            'EffectiveContextMode',
            'bodySystem',
            '【硬性要求】',
            '【背景信息',
            '【术语对照】',
            '只翻译最后一条 user 消息里的【待翻译文本】',
            'ReadGlossaryFile',
            'ParseGlossaryLine',
            'HostFileOpen',
        ):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
