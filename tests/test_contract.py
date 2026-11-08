# -*- coding: utf-8 -*-
"""AnyTranslate 插件契约测试（原生 unittest，仅标准库，不依赖第三方包）。

**契约唯一事实来源**：`plugin/SubtitleTranslate - AnyTranslate.as` + `docs/design.md`。
本文件把“login User 配置语法 -> HTTP 请求 -> 响应解析 -> 登录自检”的契约钉死，
供人工把 `tests/support/reference_impl.py` 的断言逐条映射回 `.as`（清单见 docs/testing/contract.md §7）。

运行
----
::

    python -m unittest discover -s tests -v
    python tests/test_contract.py            # 直接运行也可以
    pwsh -File tests/run_tests.ps1           # 一键运行 + 摘要

覆盖范围：
(a) 18 个 provider 预设的 URL / 请求头 / 请求体断言（含默认模型、厂商扩展字段）；
(b) 全部成功/异常响应样例解析（提取路径、数组 \\n 拼接、思考块跳过、围栏清洗）；
(c) spec 解析边界（默认值、preset 默认模型、任意 spec 的 |opts、非法 spec、
    style/context/deadline 选项与默认值）；
(d) HTTP 状态码 -> 稳定错误码映射，以及超时/连接失败；
(e) 登录自检（/models、404/405 放行、模型名匹配、custom 不探测）与 Key 脱敏；
(f) 提示词结构/目标语言规则/非对白过滤，以及译文质量门（回显、文字脚本、超长）。
"""

import dataclasses
import json
import os
import re
import socket
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from support import mock_server  # noqa: E402
from support import reference_impl as ref_impl  # noqa: E402

KIND_OPENAI = ref_impl.KIND_OPENAI
KIND_ANTHROPIC = ref_impl.KIND_ANTHROPIC
KIND_GEMINI = ref_impl.KIND_GEMINI
KIND_OLLAMA = ref_impl.KIND_OLLAMA

CUSTOM_PLACEHOLDER_URL = "http://placeholder.invalid/v1/translate"
CONTROL_DROP = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


# ---------------------------------------------------------------------------
# 契约常量（刻意与 ref_impl.PRESETS 分开写，形成“双份独立断言”）
# ---------------------------------------------------------------------------

#: preset -> (kind, base, auth, 默认模型, 默认 keyname)
PRESET_EXPECTED = {
    "openai": (KIND_OPENAI, "https://api.openai.com/v1", "bearer", "gpt-5.6-terra", ""),
    "deepseek": (KIND_OPENAI, "https://api.deepseek.com/v1", "bearer", "deepseek-v4-flash", ""),
    "moonshot": (KIND_OPENAI, "https://api.moonshot.cn/v1", "bearer", "kimi-k3.1-pro", ""),
    "zhipu": (KIND_OPENAI, "https://open.bigmodel.cn/api/paas/v4", "bearer", "glm-5.3", ""),
    "qwen": (KIND_OPENAI, "https://dashscope.aliyuncs.com/compatible-mode/v1", "bearer",
             "qwen-flash", ""),
    "siliconflow": (KIND_OPENAI, "https://api.siliconflow.cn/v1", "bearer",
                    "deepseek-ai/DeepSeek-V4-Flash", ""),
    "openrouter": (KIND_OPENAI, "https://openrouter.ai/api/v1", "bearer",
                   "openai/gpt-5.6-terra", ""),
    "groq": (KIND_OPENAI, "https://api.groq.com/openai/v1", "bearer",
             "openai/gpt-oss-120b", ""),
    "xai": (KIND_OPENAI, "https://api.x.ai/v1", "bearer", "grok-4.7", ""),
    "mistral": (KIND_OPENAI, "https://api.mistral.ai/v1", "bearer",
                "mistral-small-latest", ""),
    "together": (KIND_OPENAI, "https://api.together.ai/v1", "bearer",
                 "meta-llama/Llama-3.3-70B-Instruct-Turbo", ""),
    "lmstudio": (KIND_OPENAI, "http://127.0.0.1:1234/v1", "none", "", ""),
    "vllm": (KIND_OPENAI, "http://127.0.0.1:8000/v1", "none", "", ""),
    "sglang": (KIND_OPENAI, "http://127.0.0.1:30000/v1", "none", "", ""),
    "ollama": (KIND_OLLAMA, "http://127.0.0.1:11434", "none", "", ""),
    "anthropic": (KIND_ANTHROPIC, "https://api.anthropic.com", "x-api-key",
                  "claude-sonnet-4-6", "x-api-key"),
    "gemini": (KIND_GEMINI, "https://generativelanguage.googleapis.com", "x-api-key",
               "gemini-3.5-flash", "x-goog-api-key"),
    "custom": (KIND_OPENAI, "", "bearer", "", ""),
}

#: preset -> 用 model=test-model / key=sk-test 时应拼出的最终 URL（Gemini Key 不进 URL）
EXPECTED_CHAT_URLS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
    "moonshot": "https://api.moonshot.cn/v1/chat/completions",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    "siliconflow": "https://api.siliconflow.cn/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "xai": "https://api.x.ai/v1/chat/completions",
    "mistral": "https://api.mistral.ai/v1/chat/completions",
    "together": "https://api.together.ai/v1/chat/completions",
    "lmstudio": "http://127.0.0.1:1234/v1/chat/completions",
    "vllm": "http://127.0.0.1:8000/v1/chat/completions",
    "sglang": "http://127.0.0.1:30000/v1/chat/completions",
    "ollama": "http://127.0.0.1:11434/api/chat",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "gemini": (
        "https://generativelanguage.googleapis.com"
        "/v1beta/models/test-model:generateContent"
    ),
}

#: preset -> 预设追加的厂商字段（.as P_EXTRA）
PRESET_EXTRA_BODY = {
    "deepseek": {"thinking": {"type": "disabled"}},
    "qwen": {"enable_thinking": False},
    "siliconflow": {"enable_thinking": False},
}


# ---------------------------------------------------------------------------
# 测试小工具
# ---------------------------------------------------------------------------


def spec_of(line, **overrides):
    """解析 spec；失败直接抛 AssertionError（测试内使用）。"""
    ok, spec = ref_impl.parse_spec(line)
    if not ok:
        raise AssertionError(f"spec 解析失败：{line!r} -> {spec}")
    if overrides:
        spec = dataclasses.replace(spec, **overrides)
    return spec


def request_of(line, key="sk-test", prompt="你好", text="", src="", dst=""):
    ok, req = ref_impl.build_request(
        spec_of(line), key, prompt, text=text, src=src, dst=dst
    )
    if not ok:
        raise AssertionError(f"构造请求失败：{line!r} -> {req}")
    return req


def body_of(req):
    return json.loads(req.body)


def parse_ok(testcase, line, status, payload):
    ok, result = ref_impl.parse_response(spec_of(line), status, payload)
    testcase.assertTrue(ok, msg=f"期望解析成功，实际：{result}")
    return result


def parse_err(testcase, line, status, payload):
    ok, result = ref_impl.parse_response(spec_of(line), status, payload)
    testcase.assertFalse(ok, msg=f"期望解析失败，实际成功：{result!r}")
    testcase.assertIsInstance(result, ref_impl.Err)
    return result


def json_text(obj):
    return json.dumps(obj, ensure_ascii=False)


def stripped_controls(text):
    return CONTROL_DROP.sub("", text)


def openai_body(model, prompt, extra=None, temperature=0.2):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": temperature,
    }
    body.update(extra or {})
    return body


def ollama_body(model, prompt, temperature=0.2, options_extra=None):
    options = {"temperature": temperature}
    options.update(options_extra or {})
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": options,
    }


def anthropic_body(model, prompt, max_tokens=1024):
    return {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }


def gemini_body(prompt, generation_extra=None, minimal=False):
    generation = {"temperature": 0.2}
    generation.update(generation_extra or {})
    if not minimal:
        generation["thinkingConfig"] = {"thinkingBudget": 0}
    return {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation,
    }


def openai_payload(content, **extra):
    message = {"role": "assistant", "content": content}
    message.update(extra)
    return {"choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}


# ---------------------------------------------------------------------------
# (c) spec / provider 解析
# ---------------------------------------------------------------------------


class TestSpecParsing(unittest.TestCase):
    """配置语法：preset[:model][|opts] 或 custom|<url>|<model>[|opts]。"""

    def test_empty_spec_uses_default_ollama(self):
        for empty in ("", "   ", "\t\n", None):
            with self.subTest(empty=repr(empty)):
                ok, spec = ref_impl.parse_spec(empty)
                self.assertTrue(ok, msg=spec)
                self.assertEqual(spec.preset, "ollama")
                self.assertEqual(spec.kind, KIND_OLLAMA)
                self.assertEqual(spec.model, "qwen3:4b")
                self.assertEqual(spec.base, "http://127.0.0.1:11434")
                self.assertEqual(spec.probe, "models")

    def test_empty_spec_custom_default_override(self):
        ok, spec = ref_impl.parse_spec("", default="deepseek:deepseek-chat")
        self.assertTrue(ok, msg=spec)
        self.assertEqual((spec.preset, spec.model), ("deepseek", "deepseek-chat"))

    def test_preset_only_uses_preset_default_model(self):
        for name, (_, _, _, default_model, _) in PRESET_EXPECTED.items():
            if name == "custom":
                continue
            with self.subTest(preset=name):
                ok, spec = ref_impl.parse_spec(name)
                self.assertTrue(ok, msg=spec)
                self.assertEqual(spec.model, default_model)
                self.assertEqual(spec.preset, name)

    def test_preset_with_trailing_colon_uses_default_model(self):
        ok, spec = ref_impl.parse_spec("openai:")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.model, "gpt-5.6-terra")
        ok, spec = ref_impl.parse_spec("ollama:")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.model, "")

    def test_preset_model_splits_on_first_colon_only(self):
        ok, spec = ref_impl.parse_spec("ollama:qwen3:4b")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.preset, "ollama")
        self.assertEqual(spec.model, "qwen3:4b")

    def test_preset_model_can_contain_slash(self):
        ok, spec = ref_impl.parse_spec("openrouter:meta-llama/llama-3.1-70b-instruct")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.model, "meta-llama/llama-3.1-70b-instruct")

    def test_preset_name_case_insensitive(self):
        ok, spec = ref_impl.parse_spec("  DeepSeek:deepseek-chat  ")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.preset, "deepseek")
        self.assertEqual(spec.model, "deepseek-chat")
        self.assertEqual(spec.kind, KIND_OPENAI)

    def test_unknown_preset_reports_bad_preset(self):
        ok, err = ref_impl.parse_spec("no-such-provider:model-x")
        self.assertFalse(ok)
        self.assertEqual(err.code, "bad_preset")
        self.assertIn("未知服务商", err.message)
        self.assertIn("no-such-provider", err.message)
        self.assertIn("openai", err.message)
        self.assertIn("anthropic", err.message)
        self.assertIn("vllm/sglang/lmstudio/ollama", err.message)

    def test_all_presets_resolve_to_expected_defaults(self):
        for name, (kind, base, auth, default_model, keyname) in PRESET_EXPECTED.items():
            with self.subTest(preset=name):
                ok, provider = ref_impl.resolve_provider(name)
                self.assertTrue(ok, msg=provider)
                self.assertEqual(provider.kind, kind)
                self.assertEqual(provider.base, base)
                self.assertEqual(provider.auth, auth)
                self.assertEqual(provider.default_model, default_model)
                self.assertEqual(provider.keyname, keyname)
                self.assertEqual(provider.name, name)

    def test_resolve_provider_unknown(self):
        ok, err = ref_impl.resolve_provider("")
        self.assertFalse(ok)
        self.assertEqual(err.code, "bad_preset")
        ok, err = ref_impl.resolve_provider("whatever")
        self.assertFalse(ok)
        self.assertEqual(err.code, "bad_preset")

    def test_default_probe_by_preset(self):
        ok, spec = ref_impl.parse_spec("deepseek:deepseek-chat")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.probe, "models")
        ok, spec = ref_impl.parse_spec(f"custom|{CUSTOM_PLACEHOLDER_URL}|m")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.probe, "none")

    def test_default_path_by_protocol(self):
        cases = {
            "openai:gpt-4o-mini": "choices[0].message.content",
            "deepseek:deepseek-chat": "choices[0].message.content",
            "ollama:qwen3:4b": "message.content",
            "anthropic:claude-x": "content",
            "gemini:gemini-x": "candidates[0].content.parts",
            f"custom|{CUSTOM_PLACEHOLDER_URL}|m": "choices[0].message.content",
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                ok, spec = ref_impl.parse_spec(line)
                self.assertTrue(ok, msg=spec)
                self.assertEqual(spec.path, expected)

    def test_path_override_allowed_on_any_spec(self):
        ok, spec = ref_impl.parse_spec("deepseek:deepseek-chat|path=result.translation")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.path, "result.translation")
        self.assertEqual(spec.preset, "deepseek")

    def test_dst_override_option(self):
        ok, spec = ref_impl.parse_spec(
            f"custom|{CUSTOM_PLACEHOLDER_URL}|m|dst=ko"
        )
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.dst_override, "ko")

        ok, spec = ref_impl.parse_spec("deepseek:deepseek-chat")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.dst_override, "")

    def test_pipeline_context_options(self):
        ok, spec = ref_impl.parse_spec(
            "deepseek:deepseek-chat|contextmode=split;contextchars=500;glossary=Alice=爱丽丝,Bob=鲍勃"
        )
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.context_mode, "split")
        self.assertEqual(spec.context_chars, 500)
        self.assertEqual(spec.glossary, (("Alice", "爱丽丝"), ("Bob", "鲍勃")))

        ok, spec = ref_impl.parse_spec("deepseek:deepseek-chat")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.context_mode, "split")
        self.assertEqual(spec.context_chars, 1600)
        self.assertEqual(spec.glossary, ())

        ok, err = ref_impl.parse_spec("deepseek:deepseek-chat|contextmode=bad")
        self.assertFalse(ok)
        self.assertEqual(err.code, "bad_opts")

    def test_glossary_line_formats(self):
        cases = {
            "Alice=爱丽丝": ("Alice", "爱丽丝"),
            "Alice => 爱丽丝": ("Alice", "爱丽丝"),
            "Alice -> 爱丽丝": ("Alice", "爱丽丝"),
            "Alice→爱丽丝": ("Alice", "爱丽丝"),
            "Alice | 爱丽丝": ("Alice", "爱丽丝"),
            "Alice\t爱丽丝": ("Alice", "爱丽丝"),
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                self.assertEqual(ref_impl.parse_glossary_line(line), expected)
        self.assertIsNone(ref_impl.parse_glossary_line("# comment"))
        self.assertIsNone(ref_impl.parse_glossary_line("malformed"))
        self.assertIsNone(ref_impl.parse_glossary_line("=missing-source"))

    def test_custom_basic_url_with_port(self):
        line = "custom|http://127.0.0.1:8080/v1/translate|my-model"
        ok, spec = ref_impl.parse_spec(line)
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.preset, "custom")
        self.assertEqual(spec.kind, KIND_OPENAI)
        self.assertEqual(spec.url, "http://127.0.0.1:8080/v1/translate")
        self.assertEqual(spec.model, "my-model")
        self.assertEqual(spec.path, "choices[0].message.content")
        self.assertEqual(spec.auth, "bearer")
        self.assertEqual(spec.temperature, 0.2)
        self.assertFalse(spec.debug)
        self.assertFalse(spec.minimal)
        self.assertEqual(spec.probe, "none")

    def test_custom_model_may_be_omitted(self):
        ok, spec = ref_impl.parse_spec("custom|http://h/x")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.model, "")
        ok, spec = ref_impl.parse_spec("custom|http://h/x|")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.model, "")

    def test_custom_url_keeps_query_string(self):
        ok, spec = ref_impl.parse_spec("custom|http://h:9000/api?x=1&y=2|m")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.url, "http://h:9000/api?x=1&y=2")

    def test_custom_all_opts_parsed(self):
        line = (
            "custom|https://api.example.com/translate|gpt-4o-mini|"
            'path=result.translation;auth=x-api-key;keyname=api-key;temp=0.3;'
            'max_tokens=256;debug=1;minimal=1;version=2024-01-01;probe=models;'
            'body={"q":"{{prompt}}"}'
        )
        ok, spec = ref_impl.parse_spec(line)
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.path, "result.translation")
        self.assertEqual(spec.auth, "x-api-key")
        self.assertEqual(spec.keyname, "api-key")
        self.assertEqual(spec.temperature, 0.3)
        self.assertEqual(spec.max_tokens, 256)
        self.assertTrue(spec.debug)
        self.assertTrue(spec.minimal)
        self.assertEqual(spec.version, "2024-01-01")
        self.assertEqual(spec.probe, "models")
        self.assertEqual(spec.body_template, '{"q":"{{prompt}}"}')

    def test_opts_work_on_preset_spec(self):
        line = "deepseek:deepseek-chat|debug=1;temp=0.7;max_tokens=512;minimal=1"
        ok, spec = ref_impl.parse_spec(line)
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.preset, "deepseek")
        self.assertEqual(spec.model, "deepseek-chat")
        self.assertTrue(spec.debug)
        self.assertEqual(spec.temperature, 0.7)
        self.assertEqual(spec.max_tokens, 512)
        self.assertTrue(spec.minimal)
        # preset-only + opts 也合法
        ok, spec = ref_impl.parse_spec("openai|debug=1")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.model, "gpt-5.6-terra")
        self.assertTrue(spec.debug)

    def test_custom_opts_may_contain_pipe(self):
        line = (
            "custom|http://h/x|m|"
            'body={"q":"{{prompt}}","sep":"a|b"}'
        )
        ok, spec = ref_impl.parse_spec(line)
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.body_template, '{"q":"{{prompt}}","sep":"a|b"}')

    def test_custom_invalid_forms(self):
        cases = {
            "custom": "bad_spec",  # 没有 |，按 preset 解析后 base 为空
            "custom|": "bad_spec",  # 缺少 url
        }
        for line, code in cases.items():
            with self.subTest(line=line):
                ok, err = ref_impl.parse_spec(line)
                self.assertFalse(ok)
                self.assertEqual(err.code, code, msg=str(err))
                self.assertIn("custom", err.message)

    def test_custom_missing_url_message(self):
        ok, err = ref_impl.parse_spec("custom|")
        self.assertFalse(ok)
        self.assertIn("custom 缺少 url", err.message)
        ok, err = ref_impl.parse_spec("custom")
        self.assertFalse(ok)
        self.assertIn("custom 需要完整 URL", err.message)

    def test_custom_accepts_arbitrary_scheme_and_extra_fields(self):
        # .as 不校验 URL scheme；opts 里出现 '|' 时作为 opts 内容保留
        ok, spec = ref_impl.parse_spec("custom|ftp://h/x|m")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.url, "ftp://h/x")
        ok, spec = ref_impl.parse_spec("custom|http://h/x|m|a=1|b=2")
        self.assertTrue(ok, msg=spec)

    def test_uppercase_custom_prefix_is_treated_as_preset(self):
        # .as StartsWith("custom|") 大小写敏感；"Custom|..." 会走 preset 分支
        ok, err = ref_impl.parse_spec("Custom|http://h/x|m")
        self.assertFalse(ok)
        self.assertEqual(err.code, "bad_spec")

    def test_invalid_auth_value(self):
        for line in (
            f"custom|{CUSTOM_PLACEHOLDER_URL}|m|auth=basic",
            "deepseek:deepseek-chat|auth=token",
        ):
            with self.subTest(line=line):
                ok, err = ref_impl.parse_spec(line)
                self.assertFalse(ok)
                self.assertEqual(err.code, "bad_opts")
                self.assertEqual(err.message, "auth 只能是 bearer / x-api-key / query / none")

    def test_temperature_sanitized_and_default(self):
        cases = {
            "temp=abc": 0.2,
            "temp=": 0.2,
            "temp=0.35": 0.35,
            "temp=0.55x": 0.55,  # 非数字字符被删除
        }
        for opt, expected in cases.items():
            with self.subTest(opt=opt):
                ok, spec = ref_impl.parse_spec(f"deepseek:deepseek-chat|{opt}")
                self.assertTrue(ok, msg=spec)
                self.assertAlmostEqual(spec.temperature, expected)

    def test_max_tokens_sanitized(self):
        ok, spec = ref_impl.parse_spec("deepseek:deepseek-chat|max_tokens=512x")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.max_tokens, 512)
        ok, spec = ref_impl.parse_spec("deepseek:deepseek-chat|max_tokens=abc")
        self.assertTrue(ok, msg=spec)
        self.assertIsNone(spec.max_tokens)

    def test_flags_only_accept_1_or_true(self):
        cases = {
            "debug=1": ("debug", True),
            "debug=true": ("debug", True),
            "debug=TRUE": ("debug", True),
            "debug=yes": ("debug", False),
            "debug=0": ("debug", False),
            "minimal=1": ("minimal", True),
            "minimal=TRUE": ("minimal", True),
            "minimal=yes": ("minimal", False),
        }
        for opt, (field, expected) in cases.items():
            with self.subTest(opt=opt):
                ok, spec = ref_impl.parse_spec(f"deepseek:deepseek-chat|{opt}")
                self.assertTrue(ok, msg=spec)
                self.assertIs(getattr(spec, field), expected)

    def test_version_default_and_override(self):
        ok, spec = ref_impl.parse_spec("anthropic:claude-x")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.version, "2023-06-01")
        ok, spec = ref_impl.parse_spec("anthropic:claude-x|version=2024-06-01")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.version, "2024-06-01")

    def test_opts_unknown_and_malformed_ignored(self):
        ok, spec = ref_impl.parse_spec(
            "deepseek:deepseek-chat|future=1;broken;=x;;temp=0.6"
        )
        self.assertTrue(ok, msg=spec)
        self.assertAlmostEqual(spec.temperature, 0.6)

    def test_opts_duplicate_last_wins(self):
        ok, spec = ref_impl.parse_spec("deepseek:deepseek-chat|temp=0.1;temp=0.9")
        self.assertTrue(ok, msg=spec)
        self.assertAlmostEqual(spec.temperature, 0.9)

    def test_opts_whitespace_tolerated(self):
        ok, spec = ref_impl.parse_spec(
            "deepseek:deepseek-chat| path = data[0].text ; temp = 0.25 ; auth = none "
        )
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.path, "data[0].text")
        self.assertAlmostEqual(spec.temperature, 0.25)
        self.assertEqual(spec.auth, "none")

    def test_parse_opts_returns_tuple_never_raises(self):
        for raw in (None, "", "  ", ";;;", "a", "=x", "auth=", "temp=NaN"):
            with self.subTest(raw=repr(raw)):
                ok, result = ref_impl.parse_opts(raw)
                self.assertIsInstance(ok, bool)
                if not ok:
                    self.assertIsInstance(result, ref_impl.Err)

    def test_parse_spec_never_raises_on_garbage(self):
        garbage = [
            ":", "::", "|", "|||", "custom|", "custom||", "custom|||",
            "\x00", "openai:\x01", "ollama:qwen3:4b|extra",
            "custom|http://x|m|path=a[b]", "custom|http://x|m|path=.a",
            "custom|http://x|m|auth=Bearer", "CUSTOM|http://x|m",
            "a" * 500, "openai|", "deepseek|;",
        ]
        for line in garbage:
            with self.subTest(line=line[:40]):
                ok, result = ref_impl.parse_spec(line)
                self.assertIsInstance(ok, bool)
                if not ok:
                    self.assertIsInstance(result, ref_impl.Err)
                    self.assertTrue(result.code)
                    self.assertTrue(result.message)


# ---------------------------------------------------------------------------
# (a) 请求构造：URL / 请求头 / 请求体
# ---------------------------------------------------------------------------


class TestRequestBuilding(unittest.TestCase):
    def test_all_preset_chat_urls(self):
        for name, expected_url in EXPECTED_CHAT_URLS.items():
            with self.subTest(preset=name):
                req = request_of(f"{name}:test-model")
                self.assertEqual(req.url, expected_url)
                self.assertEqual(req.method, "POST")

    def test_gemini_key_never_in_url(self):
        req = request_of("gemini:gemini-2.5-flash", key="gm-secret")
        self.assertNotIn("gm-secret", req.url)
        self.assertNotIn("?", req.url)
        self.assertEqual(req.headers["x-goog-api-key"], "gm-secret")

    def test_all_preset_headers(self):
        for name, (_, _, auth, _, keyname) in PRESET_EXPECTED.items():
            if name == "custom":
                continue
            with self.subTest(preset=name):
                req = request_of(f"{name}:test-model", key="sk-test")
                expected = {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
                if auth == "bearer":
                    expected["Authorization"] = "Bearer sk-test"
                elif auth == "x-api-key":
                    expected[keyname or "x-api-key"] = "sk-test"
                    if name == "anthropic":
                        expected["anthropic-version"] = "2023-06-01"
                self.assertEqual(req.headers, expected)

    def test_openai_deepseek_headers_and_body(self):
        req = request_of("deepseek:deepseek-chat", prompt="你好")
        self.assertEqual(req.url, "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(req.headers, {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer sk-test",
        })
        self.assertEqual(
            body_of(req),
            openai_body("deepseek-chat", "你好", {"thinking": {"type": "disabled"}}),
        )

    def test_openai_preset_default_body_has_no_extra_fields(self):
        req = request_of("openai", prompt="hi")
        body = body_of(req)
        self.assertEqual(body, openai_body("gpt-5.6-terra", "hi"))
        self.assertNotIn("thinking", body)

    def test_think_option_adds_openai_template_flag(self):
        ok, spec = ref_impl.parse_spec(f"custom|{CUSTOM_PLACEHOLDER_URL}|m|think=0")
        self.assertTrue(ok, msg=spec)
        ok, req = ref_impl.build_request(spec, "sk-test", "hi", dst="zh-CN")
        self.assertTrue(ok, msg=req)
        self.assertEqual(body_of(req)["chat_template_kwargs"], {"enable_thinking": False})

        ok, spec = ref_impl.parse_spec(f"custom|{CUSTOM_PLACEHOLDER_URL}|m|think=1")
        self.assertTrue(ok, msg=spec)
        ok, req = ref_impl.build_request(spec, "sk-test", "hi", dst="zh-CN")
        self.assertTrue(ok, msg=req)
        self.assertEqual(body_of(req)["chat_template_kwargs"], {"enable_thinking": True})

    def test_think_option_provider_fields(self):
        self.assertEqual(body_of(request_of("deepseek:deepseek-chat|think=0"))["thinking"], {"type": "disabled"})
        self.assertEqual(body_of(request_of("deepseek:deepseek-chat|think=1"))["thinking"], {"type": "enabled"})
        self.assertIs(body_of(request_of("qwen:qwen-flash|think=1"))["enable_thinking"], True)
        self.assertIs(body_of(request_of("openrouter:openai/gpt-x|think=0"))["reasoning"]["enabled"], False)
        self.assertEqual(
            body_of(request_of("gemini:gemini-3.5-flash|think=0"))["generationConfig"]["thinkingConfig"],
            {"thinkingBudget": 0},
        )
        self.assertNotIn(
            "thinkingConfig",
            body_of(request_of("gemini:gemini-3.5-flash|think=1"))["generationConfig"],
        )
        self.assertIs(body_of(request_of("ollama:qwen3:4b|think=1"))["think"], True)

    def test_qwen_and_siliconflow_disable_thinking(self):
        for name in ("qwen", "siliconflow"):
            with self.subTest(preset=name):
                spec = spec_of(name)
                req = request_of(f"{name}:x", prompt="hi")
                self.assertEqual(
                    body_of(req),
                    openai_body("x", "hi", {"enable_thinking": False}),
                )
                self.assertEqual(spec.extra_body, {"enable_thinking": False})

    def test_preset_default_model_flows_into_body(self):
        cases = {
            "openai": "gpt-5.6-terra",
            "deepseek": "deepseek-v4-flash",
            "groq": "openai/gpt-oss-120b",
            "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "anthropic": "claude-sonnet-4-6",
            "gemini": "gemini-3.5-flash",
        }
        for preset, model in cases.items():
            with self.subTest(preset=preset):
                req = request_of(preset)
                if preset == "anthropic":
                    self.assertEqual(body_of(req)["model"], model)
                elif preset == "gemini":
                    self.assertIn("models/" + model, req.url)
                else:
                    self.assertEqual(body_of(req)["model"], model)
        # 本机服务默认不猜模型
        self.assertNotIn("model", body_of(request_of("ollama")))
        self.assertNotIn("model", body_of(request_of("lmstudio")))
        self.assertNotIn("model", body_of(request_of("vllm")))
        self.assertNotIn("model", body_of(request_of("sglang")))

    def test_local_presets_no_auth_no_model(self):
        for preset, url in (
            ("vllm", "http://127.0.0.1:8000/v1/chat/completions"),
            ("sglang", "http://127.0.0.1:30000/v1/chat/completions"),
            ("lmstudio", "http://127.0.0.1:1234/v1/chat/completions"),
        ):
            with self.subTest(preset=preset):
                req = request_of(preset, key="")
                self.assertEqual(req.url, url)
                self.assertEqual(req.headers, {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                })
                self.assertNotIn("model", body_of(req))

    def test_ollama_native_request(self):
        req = request_of("ollama:qwen3:4b", key="ignored", prompt="hi")
        self.assertEqual(req.url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(req.headers, {
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        self.assertEqual(body_of(req), ollama_body("qwen3:4b", "hi"))

    def test_anthropic_request(self):
        req = request_of("anthropic:claude-sonnet-4-5", key="sk-ant-test", prompt="hi")
        self.assertEqual(req.url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(req.headers, {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-api-key": "sk-ant-test",
            "anthropic-version": "2023-06-01",
        })
        self.assertEqual(body_of(req), anthropic_body("claude-sonnet-4-5", "hi"))

    def test_anthropic_version_override(self):
        line = "anthropic:claude-x|version=2024-06-01"
        req = request_of(line, key="k")
        self.assertEqual(req.headers["anthropic-version"], "2024-06-01")

    def test_anthropic_max_tokens_override(self):
        req = request_of("anthropic:claude-x|max_tokens=256", key="k")
        self.assertEqual(body_of(req)["max_tokens"], 256)

    def test_gemini_request(self):
        req = request_of("gemini:gemini-2.5-flash", key="gm-key", prompt="hi")
        self.assertEqual(
            req.url,
            "https://generativelanguage.googleapis.com"
            "/v1beta/models/gemini-2.5-flash:generateContent",
        )
        self.assertEqual(req.headers, {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-goog-api-key": "gm-key",
        })
        self.assertEqual(body_of(req), gemini_body("hi"))

    def test_gemini_empty_key_has_no_auth_header(self):
        req = request_of("gemini:gemini-2.5-flash", key="")
        self.assertEqual(req.headers, {
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def test_custom_default_request(self):
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|my-model"
        req = request_of(line, prompt="hi")
        self.assertEqual(req.url, CUSTOM_PLACEHOLDER_URL)
        self.assertEqual(req.headers, {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer sk-test",
        })
        self.assertEqual(body_of(req), openai_body("my-model", "hi"))

    def test_custom_empty_model_body_omits_model(self):
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|"
        req = request_of(line, prompt="hi")
        self.assertNotIn("model", body_of(req))

    def test_custom_auth_bearer(self):
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|m|auth=bearer"
        req = request_of(line, key="k1")
        self.assertEqual(req.headers["Authorization"], "Bearer k1")

    def test_custom_auth_x_api_key_header_name(self):
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|m|auth=x-api-key;keyname=api-key"
        req = request_of(line, key="k2")
        self.assertEqual(req.headers["api-key"], "k2")
        self.assertNotIn("Authorization", req.headers)
        self.assertNotIn("anthropic-version", req.headers)

    def test_custom_auth_x_api_key_default_header(self):
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|m|auth=x-api-key"
        req = request_of(line, key="k3")
        self.assertEqual(req.headers["x-api-key"], "k3")

    def test_custom_auth_query_with_existing_query(self):
        line = "custom|http://h:9000/api?x=1|m|auth=query;keyname=k"
        req = request_of(line, key="a b&c")
        parsed = urllib.parse.urlparse(req.url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(query["x"], ["1"])
        self.assertEqual(query["k"], ["a b&c"])

    def test_custom_auth_query_without_existing_query(self):
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|m|auth=query"
        req = request_of(line, key="tok")
        self.assertTrue(req.url.endswith("?key=tok"), msg=req.url)

    def test_auth_query_keyname_normalized_to_key(self):
        # .as ParseSpec：auth=query 且未显式 keyname= 时，keyname 归一化为 "key"
        cases = [
            "gemini:gemini-2.5-flash|auth=query",
            "openai|auth=query",
            "anthropic:claude-x|auth=query",
            "ollama:qwen3:4b|auth=query",
            f"custom|{CUSTOM_PLACEHOLDER_URL}|m|auth=query",
        ]
        for line in cases:
            with self.subTest(line=line):
                ok, spec = ref_impl.parse_spec(line)
                self.assertTrue(ok, msg=spec)
                self.assertEqual(spec.keyname, "key")

    def test_auth_query_explicit_keyname_preserved(self):
        ok, spec = ref_impl.parse_spec("gemini:gemini-2.5-flash|auth=query;keyname=gmkey")
        self.assertTrue(ok, msg=spec)
        self.assertEqual(spec.keyname, "gmkey")

    def test_auth_query_gemini_url_uses_key_param(self):
        req = request_of("gemini:gemini-3.5-flash|auth=query", key="qk")
        self.assertTrue(req.url.endswith(":generateContent?key=qk"), msg=req.url)
        self.assertNotIn("x-goog-api-key", req.headers)
        self.assertEqual(req.headers, {
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def test_auth_query_openai_url_uses_key_param(self):
        req = request_of("openai|auth=query", key="qk")
        self.assertTrue(req.url.endswith("/chat/completions?key=qk"), msg=req.url)
        self.assertNotIn("Authorization", req.headers)

    def test_auth_query_anthropic_has_no_auth_headers(self):
        req = request_of("anthropic:claude-x|auth=query", key="qk")
        self.assertTrue(req.url.endswith("/v1/messages?key=qk"), msg=req.url)
        self.assertNotIn("x-api-key", req.headers)
        self.assertNotIn("anthropic-version", req.headers)

    def test_custom_auth_none(self):
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|m|auth=none"
        req = request_of(line, key="k4")
        self.assertEqual(req.headers, {
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def test_custom_body_template_all_placeholders(self):
        template = (
            '{"p":"{{prompt}}","t":"{{text}}","m":"{{model}}",'
            '"s":"{{src}}","d":"{{dst}}"}'
        )
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|tmpl-model|body={template}"
        prompt = 'He said "你好"\n第二行\t\\ 结束'
        ok, req = ref_impl.build_request(
            spec_of(line), "secret", prompt, text="原文", src="English", dst="Chinese"
        )
        self.assertTrue(ok, msg=req)
        body = json.loads(req.body)
        self.assertEqual(body["p"], prompt)
        self.assertEqual(body["t"], "原文")
        self.assertEqual(body["m"], "tmpl-model")
        self.assertEqual(body["s"], "English")
        self.assertEqual(body["d"], "Chinese")

    def test_custom_body_template_invalid_json(self):
        line = f'custom|{CUSTOM_PLACEHOLDER_URL}|m|body={{"input":"{{{{prompt}}}}'
        ok, req = ref_impl.build_request(spec_of(line), "k", "hi")
        self.assertFalse(ok)
        self.assertEqual(req.code, "bad_body_template")

    def test_minimal_bodies(self):
        req = request_of("deepseek:deepseek-chat|minimal=1", prompt="hi")
        self.assertEqual(body_of(req), {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        })
        req = request_of("ollama:qwen3:4b|minimal=1", prompt="hi")
        self.assertEqual(body_of(req), {
            "model": "qwen3:4b",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        })
        req = request_of("gemini:gemini-x|minimal=1", prompt="hi")
        self.assertEqual(body_of(req), gemini_body("hi", minimal=True))
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|m|minimal=1"
        req = request_of(line, prompt="hi")
        self.assertEqual(body_of(req), {
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        })

    def test_max_tokens_maps_per_protocol(self):
        req = request_of("deepseek:deepseek-chat|max_tokens=512", prompt="hi")
        self.assertEqual(body_of(req)["max_completion_tokens"], 512)
        req = request_of("ollama:qwen3:4b|max_tokens=256", prompt="hi")
        self.assertEqual(body_of(req)["options"]["num_predict"], 256)
        req = request_of("gemini:gemini-x|max_tokens=128", prompt="hi")
        self.assertEqual(body_of(req)["generationConfig"]["maxOutputTokens"], 128)
        req = request_of("anthropic:claude-x|max_tokens=64", key="k", prompt="hi")
        self.assertEqual(body_of(req)["max_tokens"], 64)
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|m|max_tokens=99"
        req = request_of(line, prompt="hi")
        self.assertEqual(body_of(req)["max_completion_tokens"], 99)

    def test_max_tokens_absent_by_default(self):
        self.assertNotIn("max_completion_tokens", body_of(request_of("deepseek:deepseek-chat")))
        self.assertNotIn("num_predict", body_of(request_of("ollama:qwen3:4b"))["options"])
        self.assertNotIn("maxOutputTokens", body_of(request_of("gemini:gemini-x"))["generationConfig"])

    def test_temperature_override(self):
        req = request_of("deepseek:deepseek-chat|temp=0.7", prompt="hi")
        self.assertEqual(body_of(req)["temperature"], 0.7)
        req = request_of("openai|temp=abc", prompt="hi")
        self.assertEqual(body_of(req)["temperature"], 0.2)

    def test_temperature_normalization(self):
        cases = {
            "temp=1.": 1.0,
            "temp=.5": 0.5,
            "temp=01": 1.0,
            "temp=00.5": 0.5,
            "temp=1.2.3": 0.2,
            "temp=.": 0.2,
        }
        for opt, expected in cases.items():
            with self.subTest(opt=opt):
                req = request_of("deepseek:deepseek-chat|" + opt, prompt="hi")
                self.assertEqual(body_of(req)["temperature"], expected)

    def test_style_and_context_options(self):
        ok, spec = ref_impl.parse_spec("deepseek:deepseek-chat|style=anime;context=6")
        self.assertTrue(ok)
        self.assertEqual(spec.style, "anime")
        self.assertEqual(spec.context, 6)
        self.assertEqual(spec.deadline, ref_impl.DEFAULT_DEADLINE)

        ok, spec = ref_impl.parse_spec("deepseek:deepseek-chat")
        self.assertTrue(ok)
        self.assertEqual(spec.style, "movie")
        self.assertEqual(spec.context, 4)

        for value, expected in (("0", 0), ("99", 8), ("abc", 4)):
            with self.subTest(value=value):
                ok, spec = ref_impl.parse_spec(f"deepseek:deepseek-chat|context={value}")
                self.assertTrue(ok)
                self.assertEqual(spec.context, expected)

        for value, expected in (("5000", 5000), ("1000", 2000), ("99999", 20000), ("abc", 6000)):
            with self.subTest(value=value):
                ok, spec = ref_impl.parse_spec(f"deepseek:deepseek-chat|deadline={value}")
                self.assertTrue(ok)
                self.assertEqual(spec.deadline, expected)

        ok, err = ref_impl.parse_spec("deepseek:deepseek-chat|style=unknown")
        self.assertFalse(ok)
        self.assertEqual(err.code, "bad_opts")

    def test_content_type_and_accept_on_every_provider(self):
        lines = [
            "openai:gpt-4o-mini",
            "deepseek:deepseek-chat",
            "ollama:qwen3:4b",
            "anthropic:claude-x",
            "gemini:gemini-2.5-flash",
            f"custom|{CUSTOM_PLACEHOLDER_URL}|m",
        ]
        for line in lines:
            with self.subTest(line=line):
                req = request_of(line)
                self.assertEqual(req.headers["Content-Type"], "application/json")
                self.assertEqual(req.headers["Accept"], "application/json")

    def test_body_is_single_line_valid_json_and_controls_removed(self):
        prompt = 'He said "你好"\n第二行\t\\ 结束\x01\x1f😀'
        expected = stripped_controls(prompt)
        for line in (
            "deepseek:deepseek-chat",
            "ollama:qwen3:4b",
            "anthropic:claude-x",
            "gemini:gemini-2.5-flash",
            f"custom|{CUSTOM_PLACEHOLDER_URL}|m",
        ):
            with self.subTest(line=line):
                req = request_of(line, prompt=prompt)
                self.assertNotIn("\n", req.body)
                self.assertNotIn("\r", req.body)
                body = json.loads(req.body)
                if "messages" in body:
                    content = body["messages"][0]["content"]
                else:
                    content = body["contents"][0]["parts"][0]["text"]
                self.assertEqual(content, expected)

    def test_tricky_prompt_roundtrip_all_kinds_and_placeholders(self):
        prompt = 'quote:" back:\\ newline:\n tab:\t cr:\r ctrl:\x02 unicode:你好😀 <br/>'
        expected = stripped_controls(prompt)
        lines = [
            "deepseek:deepseek-chat",
            "ollama:qwen3:4b",
            "anthropic:claude-x",
            "gemini:gemini-2.5-flash",
        ]
        for line in lines:
            with self.subTest(line=line):
                req = request_of(line, prompt=prompt)
                body = json.loads(req.body)
                if line.startswith("anthropic"):
                    content = body["messages"][0]["content"]
                elif line.startswith("gemini"):
                    content = body["contents"][0]["parts"][0]["text"]
                else:
                    content = body["messages"][0]["content"]
                self.assertEqual(content, expected)

    def test_build_request_accepts_err_passthrough(self):
        err = ref_impl.Err("bad_spec", "x")
        ok, result = ref_impl.build_request(err)
        self.assertFalse(ok)
        self.assertIs(result, err)

    def test_build_request_never_raises_on_garbage(self):
        spec = spec_of("openai:gpt-4o-mini")
        for key in (None, 123, "  ", "k"):
            for prompt in (None, 123, "", "x"):
                with self.subTest(key=key, prompt=prompt):
                    ok, result = ref_impl.build_request(spec, key, prompt)  # type: ignore[arg-type]
                    self.assertIsInstance(ok, bool)
                    if ok:
                        json.loads(result.body)
                    else:
                        self.assertIsInstance(result, ref_impl.Err)


# ---------------------------------------------------------------------------
# JSON 转义（镜像 .as JsonEscape）
# ---------------------------------------------------------------------------


class TestJsonEscaping(unittest.TestCase):
    CORPUS = [
        "",
        "hello world",
        'double " quote',
        "back \\ slash",
        "line\nbreak",
        "tab\there",
        "carriage\rreturn",
        "control\x00\x01\x08\x0b\x0c\x1fend",
        "中文与英文 mixed",
        "emoji 😀🎬",
        "<br/>tag",
        "<script>alert('x')</script>",
        "quote' single",
        "slash / path",
        "\u2028\u2029",
        "\x7f delete",
    ]

    def test_removes_c0_controls_except_tab_nl_cr(self):
        self.assertEqual(ref_impl.json_escape("\x00\x01\x08\x0b\x0c\x1f"), "")
        self.assertEqual(ref_impl.json_escape("a\tb\nc\rd"), "a\\tb\\nc\\rd")
        self.assertEqual(ref_impl.json_escape("\x7f"), "\x7f")  # DEL 不属于 C0
        self.assertEqual(ref_impl.json_escape("\u2028"), "\u2028")

    def test_backspace_and_formfeed_removed_not_escaped(self):
        # .as StripChars 剔除 \b(0x08)/\f(0x0C)，不做短转义
        self.assertEqual(ref_impl.json_escape("\b\f"), "")
        self.assertEqual(ref_impl.json_escape("a\bb\fc"), "abc")
        self.assertNotIn("\\b", ref_impl.json_escape("\b"))
        self.assertNotIn("\\f", ref_impl.json_escape("\f"))

    def test_short_escapes_and_quotes(self):
        self.assertEqual(ref_impl.json_escape('a"b\\c'), 'a\\"b\\\\c')
        self.assertEqual(ref_impl.json_escape("a\nb"), "a\\nb")
        self.assertEqual(ref_impl.json_escape("a\rb"), "a\\rb")
        self.assertEqual(ref_impl.json_escape("a\tb"), "a\\tb")

    def test_roundtrip_after_control_removal(self):
        for text in self.CORPUS:
            with self.subTest(text=repr(text)):
                expected = stripped_controls(text)
                literal = '"' + ref_impl.json_escape(text) + '"'
                self.assertEqual(json.loads(literal), expected)

    def test_json_quote_roundtrip(self):
        for text in self.CORPUS:
            with self.subTest(text=repr(text)):
                self.assertEqual(
                    json.loads(ref_impl.json_quote(text)), stripped_controls(text)
                )

    def test_json_escape_does_not_urlencode(self):
        # 官方 LM Studio 插件用 HostUrlEncode 拼 JSON，这是 bug；契约要求 JSON 转义
        self.assertEqual(ref_impl.json_escape("a b"), "a b")
        self.assertNotIn("%20", ref_impl.json_escape("a b"))

    def test_json_escape_non_string_inputs(self):
        self.assertEqual(ref_impl.json_escape(None), "")
        self.assertEqual(ref_impl.json_escape(123), "123")
        self.assertEqual(ref_impl.json_quote(True), '"True"')

    def test_manual_concat_body_matches_as_semantics(self):
        text = 'a "b"\n\nc\\d\t\x02'
        manual = (
            '{"model":"m","messages":[{"role":"user","content":'
            + ref_impl.json_quote(text)
            + '}],"stream":false,"temperature":0}'
        )
        body = json.loads(manual)
        self.assertEqual(body["messages"][0]["content"], stripped_controls(text))

    def test_safe_url_masks_encoded_and_raw_key(self):
        # .as SafeUrl：先替换 HostUrlEncode(key)，再替换原始 key
        key = "a+b/c=d"
        encoded = ref_impl.host_url_encode(key)
        self.assertEqual(encoded, "a%2Bb%2Fc%3Dd")
        url = f"http://h/v1/models?key={encoded}&raw={key}"
        masked = ref_impl.safe_url(url, key)
        self.assertNotIn(encoded, masked)
        self.assertNotIn(key, masked)
        self.assertEqual(masked.count("****"), 2)
        self.assertEqual(masked, "http://h/v1/models?key=****&raw=****")

    def test_safe_url_encoding_of_special_chars(self):
        key = "sk/with+special=chars"
        encoded = ref_impl.host_url_encode(key)
        self.assertIn("%2F", encoded)
        self.assertIn("%2B", encoded)
        self.assertIn("%3D", encoded)
        self.assertNotIn("/", encoded)

    def test_safe_url_no_key_or_absent_key(self):
        url = "http://h/v1/models?key=abc"
        self.assertEqual(ref_impl.safe_url(url, ""), url)
        self.assertEqual(ref_impl.safe_url(url, "not-present"), url)

    def test_mask_key(self):
        self.assertEqual(ref_impl.mask_key(""), "(未设置)")
        # .as MaskKey：长度 < 16 一律 ****
        for length in (1, 8, 9, 15):
            with self.subTest(length=length):
                self.assertEqual(ref_impl.mask_key("k" * length), "****")
        self.assertEqual(ref_impl.mask_key("k" * 16), "kkkk****kkkk")
        self.assertEqual(ref_impl.mask_key("sk-1234567890abcdef"), "sk-1****cdef")


# ---------------------------------------------------------------------------
# (b) 响应解析
# ---------------------------------------------------------------------------


class TestResponseParsing(unittest.TestCase):
    def test_openai_success(self):
        text = parse_ok(self, "deepseek:deepseek-chat", 200, openai_payload("你好，世界。"))
        self.assertEqual(text, "你好，世界。")

    def test_openai_bytes_response(self):
        raw = json_text(openai_payload("你好")).encode("utf-8")
        self.assertEqual(parse_ok(self, "deepseek:deepseek-chat", 200, raw), "你好")

    def test_openai_content_array_joined_with_newline(self):
        payload = openai_payload([
            {"type": "text", "text": "前半"},
            {"type": "text", "text": "后半"},
        ])
        self.assertEqual(
            parse_ok(self, "deepseek:deepseek-chat", 200, payload), "前半\n后半"
        )

    def test_openai_content_array_skips_thinking_and_empty(self):
        payload = openai_payload([
            {"type": "text", "text": "正文"},
            {"type": "thinking", "text": "不应出现"},
            {"type": "text", "text": ""},
            {"type": "text", "text": "结尾"},
        ])
        self.assertEqual(
            parse_ok(self, "deepseek:deepseek-chat", 200, payload), "正文\n结尾"
        )

    def test_openai_content_array_of_plain_strings(self):
        payload = openai_payload(["a", "b"])
        self.assertEqual(parse_ok(self, "deepseek:deepseek-chat", 200, payload), "a\nb")

    def test_openai_reasoning_only_is_error(self):
        payload = openai_payload("", reasoning_content="思考中……")
        err = parse_err(self, "deepseek:deepseek-chat", 200, payload)
        self.assertEqual(err.code, "reasoning_only")
        self.assertIn("reasoning_content", err.message)

    def test_openai_whitespace_content_with_reasoning_is_error(self):
        payload = openai_payload("   \n ", reasoning_content="思考中……")
        err = parse_err(self, "deepseek:deepseek-chat", 200, payload)
        self.assertEqual(err.code, "reasoning_only")

    def test_openai_content_wins_over_reasoning(self):
        payload = openai_payload("最终译文。", reasoning_content="思考中……")
        self.assertEqual(
            parse_ok(self, "deepseek:deepseek-chat", 200, payload), "最终译文。"
        )

    def test_openai_empty_choices_is_no_content(self):
        err = parse_err(self, "deepseek:deepseek-chat", 200, {"choices": []})
        self.assertEqual(err.code, "no_content")

    def test_openai_missing_choices_is_no_content(self):
        err = parse_err(self, "deepseek:deepseek-chat", 200, {})
        self.assertEqual(err.code, "no_content")

    def test_openai_error_object_with_200_is_provider_error(self):
        payload = {"error": {"message": "model not found", "type": "x", "code": "y"}}
        err = parse_err(self, "deepseek:deepseek-chat", 200, payload)
        self.assertEqual(err.code, "provider_error")
        self.assertEqual(err.detail, "model not found")

    def test_openai_clean_text_applied(self):
        cases = {
            "```json\n你好\n```": "你好",
            "翻译：你好": "你好",
            "Translation: 你好": "你好",
            "「你好」": "你好",
            "第一行<br/>第二行": "第一行\n第二行",
            "第一行<BR>第二行": "第一行<BR>第二行",
        }
        for content, expected in cases.items():
            with self.subTest(content=content):
                text = parse_ok(
                    self, "deepseek:deepseek-chat", 200, openai_payload(content)
                )
                self.assertEqual(text, expected)

    def test_anthropic_multiple_text_parts_joined_with_newline(self):
        payload = {
            "id": "msg_x",
            "type": "message",
            "content": [
                {"type": "text", "text": "甲"},
                {"type": "thinking", "thinking": "思考"},
                {"type": "text", "text": "乙"},
            ],
        }
        self.assertEqual(parse_ok(self, "anthropic:claude-x", 200, payload), "甲\n乙")

    def test_anthropic_empty_content_is_no_content(self):
        err = parse_err(self, "anthropic:claude-x", 200, {"content": []})
        self.assertEqual(err.code, "no_content")

    def test_anthropic_thinking_only_is_reasoning_error(self):
        payload = {
            "content": [
                {"type": "thinking", "thinking": "只有思考"},
            ]
        }
        err = parse_err(self, "anthropic:claude-x", 200, payload)
        self.assertEqual(err.code, "reasoning_only")

    def test_anthropic_error_object_with_200_is_provider_error(self):
        payload = {"error": {"message": "overloaded", "type": "overloaded_error"}}
        err = parse_err(self, "anthropic:claude-x", 200, payload)
        self.assertEqual(err.code, "provider_error")
        self.assertEqual(err.detail, "overloaded")

    def test_gemini_parts_joined_with_newline_and_thought_skipped(self):
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "思考", "thought": True},
                            {"text": "Gemini "},
                            {"text": "译文。"},
                        ]
                    }
                }
            ]
        }
        self.assertEqual(
            parse_ok(self, "gemini:gemini-2.5-flash", 200, payload),
            "Gemini \n译文。",
        )

    def test_gemini_empty_candidates_is_no_content(self):
        err = parse_err(self, "gemini:gemini-2.5-flash", 200, {"candidates": []})
        self.assertEqual(err.code, "no_content")

    def test_gemini_error_object_with_200_is_provider_error(self):
        payload = {"error": {"message": "API key not valid", "code": 400}}
        err = parse_err(self, "gemini:gemini-2.5-flash", 200, payload)
        self.assertEqual(err.code, "provider_error")
        self.assertEqual(err.detail, "API key not valid")

    def test_ollama_success(self):
        payload = {"message": {"role": "assistant", "content": "Ollama 译文"}}
        self.assertEqual(parse_ok(self, "ollama:qwen3:4b", 200, payload), "Ollama 译文")

    def test_ollama_error_field_is_provider_error(self):
        payload = {"error": "model 'x' not found, try pulling it first"}
        err = parse_err(self, "ollama:qwen3:4b", 200, payload)
        self.assertEqual(err.code, "provider_error")
        self.assertIn("not found", err.detail)

    def test_ollama_thinking_only_is_error(self):
        payload = {"message": {"role": "assistant", "content": "", "thinking": "思考"}}
        err = parse_err(self, "ollama:qwen3:4b", 200, payload)
        self.assertEqual(err.code, "reasoning_only")

    def test_custom_response_paths(self):
        shared = {
            "choices": [{"message": {"content": "choices-译文"}}],
            "result": {"translation": "result-译文"},
            "data": [{"text": "data-译文"}],
        }
        cases = {
            "choices[0].message.content": "choices-译文",
            "result.translation": "result-译文",
            "data[0].text": "data-译文",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                line = f"custom|http://h/x|m|path={path}"
                ok, text = ref_impl.parse_response(spec_of(line), 200, shared)
                self.assertTrue(ok, msg=text)
                self.assertEqual(text, expected)

    def test_custom_default_path_is_choices_message_content(self):
        payload = {"choices": [{"message": {"content": "默认路径译文"}}]}
        self.assertEqual(parse_ok(self, "custom|http://h/x|m", 200, payload), "默认路径译文")

    def test_custom_missing_path_is_no_content(self):
        err = parse_err(
            self, "custom|http://h/x|m|path=result.translation", 200, {"result": {}}
        )
        self.assertEqual(err.code, "no_content")
        self.assertIn("result.translation", err.detail)

    def test_custom_non_text_value_is_no_content(self):
        err = parse_err(
            self, "custom|http://h/x|m", 200, {"choices": [{"message": {"content": 12345}}]}
        )
        self.assertEqual(err.code, "no_content")

    def test_custom_path_value_list_of_strings_joined(self):
        line = "custom|http://h/x|m|path=data[0].text"
        payload = {"data": [{"text": ["拼接", "结果"]}]}
        self.assertEqual(parse_ok(self, line, 200, payload), "拼接\n结果")

    def test_custom_root_array_path(self):
        line = "custom|http://h/x|m|path=[0].text"
        payload = [{"text": "根数组译文"}]
        self.assertEqual(parse_ok(self, line, 200, payload), "根数组译文")

    def test_multi_digit_index_not_supported_like_as(self):
        # DESIGN 6.2 / .as DigitToInt：只支持 0-9 单数字下标
        line = "custom|http://h/x|m|path=data[10].text"
        payload = {"data": [{"text": "x"}] * 11}
        err = parse_err(self, line, 200, payload)
        self.assertEqual(err.code, "no_content")

    def test_path_override_for_preset_spec(self):
        line = "deepseek:deepseek-chat|path=result.translation"
        payload = {"result": {"translation": "预设路径覆盖"}}
        self.assertEqual(parse_ok(self, line, 200, payload), "预设路径覆盖")

    def test_custom_provider_error_object_with_200(self):
        err = parse_err(
            self, "custom|http://h/x|m", 200, {"error": {"message": "quota exceeded"}}
        )
        self.assertEqual(err.code, "provider_error")
        self.assertEqual(err.detail, "quota exceeded")

    def test_non_json_200_is_bad_json(self):
        err = parse_err(self, "deepseek:deepseek-chat", 200, "<html>not json</html>")
        self.assertEqual(err.code, "bad_json")

    def test_empty_body_is_empty_response(self):
        err = parse_err(self, "deepseek:deepseek-chat", 200, "")
        self.assertEqual(err.code, "empty_response")

    def test_json_root_scalars_are_no_content(self):
        for payload in ("null", "123", '"str"', "true"):
            with self.subTest(payload=payload):
                err = parse_err(self, "deepseek:deepseek-chat", 200, payload)
                self.assertEqual(err.code, "no_content")

    def test_parse_response_status_string_accepted(self):
        text = parse_ok(self, "deepseek:deepseek-chat", "200", openai_payload("你好"))
        self.assertEqual(text, "你好")

    def test_parse_response_never_raises_on_garbage(self):
        bodies = [
            None, b"", b"\xff\xfe\x00", "null", "[]", "{}", '"str"', "123",
            "<html>", "{bad json", '{"choices":null}', '{"choices":[{}]}',
            '{"content":"x"}', '{"message":null}', '{"candidates":null}',
            '{"data":[]}', '{"error":"boom"}', "\ufeff{}", "😀",
        ]
        kinds = [
            "deepseek:deepseek-chat",
            "anthropic:claude-x",
            "gemini:gemini-2.5-flash",
            "ollama:qwen3:4b",
            "custom|http://h/x|m",
        ]
        statuses = [200, 401, 429, 500, None, "200", 204, 302, 0, -1, 999]
        for line in kinds:
            spec = spec_of(line)
            for status in statuses:
                for body in bodies:
                    with self.subTest(line=line, status=status, body=repr(body)[:30]):
                        ok, result = ref_impl.parse_response(spec, status, body)
                        self.assertIsInstance(ok, bool)
                        if ok:
                            self.assertIsInstance(result, str)
                            self.assertTrue(result)
                        else:
                            self.assertIsInstance(result, ref_impl.Err)
                            self.assertTrue(result.code)
                            self.assertTrue(result.message)


# ---------------------------------------------------------------------------
# (d) 错误码 / HTTP 状态码映射
# ---------------------------------------------------------------------------


class TestErrorMapping(unittest.TestCase):
    STATUS_CASES = (
        (400, "bad_request", "请求参数错误 (HTTP 400)"),
        (401, "auth_failed", "API Key 无效或已过期 (HTTP 401)"),
        (402, "insufficient_balance", "账户余额不足 (HTTP 402)"),
        (403, "forbidden", "没有访问权限 (HTTP 403)"),
        (404, "not_found", "接口地址或模型不存在 (HTTP 404)"),
        (408, "timeout", "请求超时 (HTTP 408)"),
        (413, "payload_too_large", "请求体过大 (HTTP 413)"),
        (422, "invalid_params", "参数非法 (HTTP 422)"),
        (429, "rate_limited", "请求过于频繁，请稍后重试 (HTTP 429)"),
        (500, "server_error", "服务端错误 (HTTP 500)，请稍后重试"),
        (502, "server_error", "服务端错误 (HTTP 502)，请稍后重试"),
        (503, "server_error", "服务端错误 (HTTP 503)，请稍后重试"),
    )

    def test_status_code_mapping_is_stable_chinese(self):
        spec = spec_of("deepseek:deepseek-chat")
        for status, expected_code, expected_message in self.STATUS_CASES:
            with self.subTest(status=status):
                raw = json_text({"error": {"message": f"provider-detail-{status}"}})
                ok, err = ref_impl.parse_response(spec, status, raw)
                self.assertFalse(ok, msg=err)
                self.assertEqual(err.code, expected_code)
                self.assertEqual(err.message, expected_message)
                self.assertEqual(err.status, status)
                self.assertIn(f"provider-detail-{status}", err.detail)

    def test_unlisted_4xx_maps_to_client_error(self):
        err = parse_err(
            self, "deepseek:deepseek-chat", 418, json_text({"error": {"message": "teapot"}})
        )
        self.assertEqual(err.code, "client_error")
        self.assertEqual(err.message, "请求被拒绝 (HTTP 418)")

    def test_unexpected_3xx_maps_to_http_error(self):
        err = parse_err(self, "deepseek:deepseek-chat", 302, "")
        self.assertEqual(err.code, "http_error")
        self.assertEqual(err.message, "非预期 HTTP 状态 (HTTP 302)")

    def test_status_none_maps_to_http_error(self):
        err = parse_err(self, "deepseek:deepseek-chat", None, '{"choices":[]}')
        self.assertEqual(err.code, "http_error")
        self.assertIn("非预期", err.message)

    def test_status_401_with_plain_text_body(self):
        err = parse_err(self, "deepseek:deepseek-chat", 401, "Unauthorized")
        self.assertEqual(err.code, "auth_failed")
        self.assertEqual(err.message, "API Key 无效或已过期 (HTTP 401)")
        self.assertEqual(err.detail, "")

    def test_status_priority_over_body_parsing(self):
        err = parse_err(self, "deepseek:deepseek-chat", 401, "<html>bad</html>")
        self.assertEqual(err.code, "auth_failed")

    def test_502_html_body(self):
        raw = "<html><body>502 Bad Gateway</body></html>"
        err = parse_err(self, "deepseek:deepseek-chat", 502, raw)
        self.assertEqual(err.code, "server_error")
        self.assertEqual(err.message, "服务端错误 (HTTP 502)，请稍后重试")

    def test_error_codes_are_unique_and_documented(self):
        known = set(ref_impl.STATUS_MESSAGES) | {
            "bad_spec", "bad_preset", "config_error", "bad_opts", "auth_needed",
            "unsupported", "bad_body_template", "empty_response", "bad_json",
            "no_content", "reasoning_only", "provider_error", "network",
            "parse_error", "internal_error", "model_not_found",
        }
        spec = spec_of("deepseek:deepseek-chat")
        probes = [
            ref_impl.parse_response(spec, 401, "{}"),
            ref_impl.parse_response(spec, 200, ""),
            ref_impl.parse_response(spec, 200, "not json"),
            ref_impl.parse_response(spec, 200, "{}"),
            ref_impl.parse_response(spec, 200, openai_payload("", reasoning_content="x")),
            ref_impl.parse_spec("nope:x"),
        ]
        for ok, result in probes:
            self.assertFalse(ok)
            self.assertIn(result.code, known, msg=str(result))
            self.assertTrue(result.message)

    def test_perform_raw_and_request_error_mapping(self):
        # 用未知 URL scheme 稳定触发 URLError -> network（不依赖系统是否回 RST）
        spec = spec_of("deepseek:deepseek-chat")
        req = ref_impl.Request(
            method="POST",
            url="nosuchscheme://127.0.0.1/x",
            headers={"Content-Type": "application/json"},
            body="{}",
            timeout=1.0,
            spec=spec,
            kind=KIND_OPENAI,
        )
        ok, res = ref_impl.perform_request(req)
        self.assertFalse(ok)
        self.assertEqual(res.code, "network")
        self.assertIn("网络连接失败", res.message)
        self.assertIsInstance(res.detail, str)


# ---------------------------------------------------------------------------
# clean_text（镜像 .as CleanTranslation）
# ---------------------------------------------------------------------------


class TestCleanText(unittest.TestCase):
    def test_clean_text_cases(self):
        cases = {
            "```\n你好\n```": "你好",
            "```json\n你好\n```": "你好",
            "``` 你好 ```": "``` 你好",  # .as 只按首个换行去开围栏
            "```\n你好": "你好",
            "你好```": "你好",
            "'''\n你好\n'''": "你好",
            "'''你好'''": "你好",
            '"""\n你好\n"""': "你好",
            "'''\n你好": "你好",
            "你好'''": "你好",
            "翻译：你好": "你好",
            "译文: 你好": "你好",
            "Translation: 你好": "你好",
            "Translated text: 你好": "你好",
            "输出：你好": "你好",
            "【译文】你好": "你好",
            "原文：abc\n你好": "你好",
            "Here is the translation: 你好": "Here is the translation: 你好",
            "第一行<br/>第二行": "第一行\n第二行",
            "第一行<br />第二行": "第一行\n第二行",
            "第一行<br>第二行": "第一行\n第二行",
            "第一行<BR>第二行": "第一行<BR>第二行",
            '"你好"': "你好",
            "“你好”": "你好",
            "「你好」": "你好",
            "『你好』": "你好",
            "  x  ": "x",
            "a\r\nb": "a\nb",
            "a\rb": "a\nb",
            "a\n\n\nb": "a\n\nb",
            "a\n\n\n\nb": "a\n\n\nb",
            "": "",
            None: "",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=repr(raw)):
                self.assertEqual(ref_impl.clean_text(raw), expected)

    def test_strip_known_prefixes_three_rounds(self):
        self.assertEqual(ref_impl.strip_known_prefixes("翻译：Translation: 你好"), "你好")
        self.assertEqual(
            ref_impl.strip_known_prefixes("翻译：翻译：翻译：翻译：你好"), "翻译：你好"
        )
        self.assertEqual(ref_impl.strip_known_prefixes("说明：这不是前缀"), "说明：这不是前缀")

    def test_clean_text_never_raises(self):
        for value in (None, 123, 4.5, ["a"], {"k": "v"}, "\x00", "```" * 10,
                      "Here is", "翻译", "\u202b"):
            with self.subTest(value=repr(value)):
                self.assertIsInstance(ref_impl.clean_text(value), str)

    def test_clean_text_rtl(self):
        self.assertEqual(ref_impl.clean_text("x", dst_lang="فارسی"), "\u202bx")
        self.assertEqual(ref_impl.clean_text("x", dst_lang="العربية"), "\u202bx")
        self.assertEqual(ref_impl.clean_text("x", dst_lang="简体中文"), "x")

    def test_is_rtl(self):
        for lang in ("العربية", "עברית", "فارسی", "اردو"):
            with self.subTest(lang=lang):
                self.assertTrue(ref_impl.is_rtl(lang))
        # .as IsRtlLabel 按 L_LABEL 精确匹配，不接受语言码/英文名
        for lang in ("", None, "fa", "ar", "Arabic", "Persian", "fa-IR", " AR ",
                     "en", "Chinese", "ja", "fr", "yi", "ps", "sd"):
            with self.subTest(lang=lang):
                self.assertFalse(ref_impl.is_rtl(lang))

    def test_known_prefix_count(self):
        self.assertEqual(len(ref_impl.KNOWN_PREFIXES), 14)
        self.assertEqual(len(set(ref_impl.KNOWN_PREFIXES)), 14)

    def test_validate_translation(self):
        self.assertEqual(ref_impl.validate_translation("Hello world", "你好，世界", "English", "Chinese"), "")
        self.assertEqual(ref_impl.validate_translation("Hello world", "Hello world", "English", "Chinese"), "echo")
        self.assertEqual(ref_impl.validate_translation("ok", "ok", "English", "Chinese"), "")
        self.assertEqual(ref_impl.validate_translation("Hello", "This is an English sentence", "English", "Chinese"), "wrong_script")
        self.assertEqual(ref_impl.validate_translation("Hello", "NASA", "English", "Chinese"), "")
        self.assertEqual(ref_impl.validate_translation("Hello", "Mr. Smith", "English", "Chinese"), "")
        self.assertEqual(ref_impl.validate_translation("Hello", "", "English", "Chinese"), "empty")
        self.assertEqual(
            ref_impl.validate_translation("Hello", "- 原文：Hello\n译文：你好", "English", "Chinese"),
            "history_leak",
        )
        self.assertEqual(
            ref_impl.validate_translation(
                "Hello", "你好。\n情况好点啦。", "English", "Chinese",
                history=[("Hello", "情况好点啦。")],
            ),
            "history_leak",
        )
        self.assertEqual(
            ref_impl.validate_translation(
                "A different source line", "上一句的完整译文。", "English", "Chinese",
                history=[("The previous source line", "上一句的完整译文。")],
            ),
            "history_leak",
        )
        self.assertEqual(
            ref_impl.validate_translation(
                "另一句没有标签的原文", "提要：夜里我又画了一张。", "Chinese", "Chinese",
                history=[("提要 夜里我又画了一张", "提要：夜里我又画了一张。")],
            ),
            "history_leak",
        )
        self.assertEqual(
            ref_impl.validate_translation(
                "まあ、とりあえずもう少ししたら", "嗯，总之过一会儿应该就能走了。",
                "Japanese", "Chinese",
                history=[("もう少し時間がたったら", "过一会儿应该就能走了")],
            ),
            "history_leak",
        )
        self.assertEqual(
            ref_impl.validate_translation(
                "さくらさん、この後って予定あります?", "樱花小姐，接下来有什么安排吗？",
                "Japanese", "Chinese",
                history=[("さくらさん", "樱花小姐")],
            ),
            "",
        )
        self.assertEqual(ref_impl.validation_reason_zh("history_leak"), "译文混入了上下文格式")
        self.assertEqual(ref_impl.validate_translation("Hi", "你好", "Chinese", "Chinese"), "")
        self.assertEqual(
            ref_impl.validate_translation("Hi", "你" * 100, "English", "Chinese"),
            "too_long",
        )
        self.assertEqual(
            ref_impl.validate_translation("夜里", "夜裡", "", "zh-CN"),
            "traditional",
        )
        self.assertEqual(
            ref_impl.validate_translation("夜裡", "这", "", "zh-TW"),
            "simplified",
        )
        self.assertEqual(ref_impl.validation_reason_zh("traditional"), "译文仍是繁体字，需要转为简体")
        self.assertEqual(ref_impl.validation_reason_zh("simplified"), "译文仍是简体字，需要转为繁体")
        self.assertEqual(ref_impl.validation_reason_zh("echo"), "回显原文")
        self.assertEqual(ref_impl.validation_reason_zh("wrong_script"), "目标语言文字脚本不对")
        self.assertEqual(ref_impl.validation_reason_zh("too_long"), "译文过长")
        self.assertEqual(ref_impl.validation_reason_zh("unknown"), "unknown")

    def test_non_dialogue_filter(self):
        for value in ("♪", "♪♪", "。。。", "12345", "...", "— —"):
            with self.subTest(value=value):
                self.assertTrue(ref_impl.is_non_dialogue_text(value))
        for value in ("Hello", "[door slams]", "你好", "2024 年"):
            with self.subTest(value=value):
                self.assertFalse(ref_impl.is_non_dialogue_text(value))

    def test_target_rules(self):
        self.assertIn("全角标点", ref_impl.target_rules("简体中文"))
        self.assertIn("逐字转为简体", ref_impl.target_rules("zh-CN"))
        self.assertIn("机械逐字替换", ref_impl.target_rules("zh-TW"))
        self.assertIn("發/髮", ref_impl.target_rules("zh-TW"))
        self.assertIn("復/複", ref_impl.target_rules("zh-TW"))
        self.assertNotIn("后", ref_impl.target_rules("zh-TW"))
        self.assertIn("日文标点", ref_impl.target_rules("日本語"))
        self.assertIn("英文标点", ref_impl.target_rules("English"))
        self.assertIn("从右到左", ref_impl.target_rules("العربية"))
        self.assertEqual(ref_impl.target_rules("Klingon"), "")

    def test_node_text_semantics(self):
        self.assertEqual(ref_impl.node_text("x"), "x")
        self.assertEqual(ref_impl.node_text(["a", "", "b"]), "a\nb")
        self.assertEqual(ref_impl.node_text([{"text": "a"}, {"text": "b"}]), "a\nb")
        self.assertEqual(ref_impl.node_text({"text": "a"}), "a")
        self.assertEqual(ref_impl.node_text({"content": "a"}), "a")
        self.assertEqual(ref_impl.node_text({"thought": True, "text": "a"}), "")
        self.assertEqual(ref_impl.node_text({"type": "thinking", "text": "a"}), "")
        self.assertEqual(ref_impl.node_text({"type": "text", "text": "a"}), "a")
        self.assertEqual(ref_impl.node_text(123), "")

    def test_parse_json_path_tokens(self):
        ok, tokens = ref_impl.parse_json_path("choices[0].message.content")
        self.assertTrue(ok, msg=tokens)
        self.assertEqual(tokens, ["choices", 0, "message", "content"])
        ok, tokens = ref_impl.parse_json_path("[0].text")
        self.assertTrue(ok, msg=tokens)
        self.assertEqual(tokens, [0, "text"])
        for bad in ("", ".a", "a..b", "a[0", "a[x]", "a[0]x", "data[10].text"):
            with self.subTest(path=bad):
                ok, err = ref_impl.parse_json_path(bad)
                self.assertFalse(ok)

    def test_resolve_json_path(self):
        obj = {"data": [{"text": "x"}]}
        ok, value = ref_impl.resolve_json_path(obj, "data[0].text")
        self.assertTrue(ok)
        self.assertEqual(value, "x")
        ok, value = ref_impl.resolve_json_path(obj, "data[9].text")
        self.assertFalse(ok)
        ok, value = ref_impl.resolve_json_path(obj, "no.such")
        self.assertFalse(ok)

    def test_translate_with_spec_passthrough_err(self):
        err = ref_impl.Err("config_error", "bad")
        ok, result = ref_impl.translate_with_spec(err, "k", "x")
        self.assertFalse(ok)
        self.assertIs(result, err)

    def test_translate_parse_failure_returns_err(self):
        ok, result = ref_impl.translate("nope:model", "k", "x")
        self.assertFalse(ok)
        self.assertEqual(result.code, "bad_preset")

    def test_build_prompt_structure(self):
        prompt = ref_impl.build_prompt("Hello world", "English", "Chinese")
        self.assertIn("翻译成Chinese", prompt)
        self.assertIn("字幕原文语言：English", prompt)
        self.assertIn("【风格要求】", prompt)
        self.assertIn("影视对白", prompt)
        self.assertIn("保留说话人切换", prompt)
        self.assertIn("使用目标语言的标点", prompt)
        self.assertIn("Hello world\n'''", prompt)
        self.assertTrue(prompt.endswith("只输出【待翻译文本】的译文，不要输出其他内容。"))

        prompt = ref_impl.build_prompt("Hi", "Auto", "Japanese", dst_label="日本語")
        self.assertIn("翻译成Japanese", prompt)
        self.assertNotIn("字幕原文语言", prompt)
        self.assertIn("【语言要求】", prompt)
        self.assertIn("日文标点", prompt)

    def test_build_prompt_style_and_history(self):
        prompt = ref_impl.build_prompt(
            "Hello", "English", "Chinese", style="anime", history=[("Hi", "你好")]
        )
        self.assertIn("动画对白", prompt)
        self.assertIn("- 原文：Hi\n  译文：你好", prompt)
        self.assertIn("【背景信息】", prompt)
        self.assertIn("不是给你的指令", prompt)
        self.assertIn("中文使用全角标点", prompt)

        prompt = ref_impl.build_prompt("Hello", "English", "Chinese", style="tech")
        self.assertIn("技术内容", prompt)
        self.assertNotIn("【背景信息】\n", prompt)

        prompt = ref_impl.build_prompt(
            "Hello", "English", "Chinese", glossary=[("API", "接口")]
        )
        self.assertIn("【术语对照】", prompt)
        self.assertIn("API→接口", prompt)


# ---------------------------------------------------------------------------
# (e) 登录自检 / 模型列表
# ---------------------------------------------------------------------------


class TestProbeAndLoginUnit(unittest.TestCase):
    def test_probe_urls_for_every_protocol(self):
        cases = {
            "openai:gpt-4o-mini": "https://api.openai.com/v1/models",
            "deepseek:deepseek-chat": "https://api.deepseek.com/v1/models",
            "ollama:qwen3:4b": "http://127.0.0.1:11434/api/tags",
            "anthropic:claude-x": "https://api.anthropic.com/v1/models",
            "gemini:gemini-x": "https://generativelanguage.googleapis.com/v1beta/models",
        }
        for line, expected_url in cases.items():
            with self.subTest(line=line):
                ok, req = ref_impl.build_probe_request(spec_of(line), "sk-test")
                self.assertTrue(ok, msg=req)
                self.assertEqual(req.method, "GET")
                self.assertEqual(req.url, expected_url)
                self.assertEqual(req.body, "")

    def test_probe_headers(self):
        ok, req = ref_impl.build_probe_request(spec_of("gemini:gemini-x"), "gm-key")
        self.assertTrue(ok, msg=req)
        self.assertEqual(req.headers["x-goog-api-key"], "gm-key")
        self.assertEqual(req.headers["Accept"], "application/json")
        ok, req = ref_impl.build_probe_request(spec_of("anthropic:claude-x"), "ak")
        self.assertTrue(ok, msg=req)
        self.assertEqual(req.headers["x-api-key"], "ak")
        self.assertEqual(req.headers["anthropic-version"], "2023-06-01")
        ok, req = ref_impl.build_probe_request(
            spec_of("anthropic:claude-x|version=2024-06-01"), "ak"
        )
        self.assertTrue(ok, msg=req)
        self.assertEqual(req.headers["anthropic-version"], "2024-06-01")
        ok, req = ref_impl.build_probe_request(spec_of("openai:gpt-4o-mini"), "sk")
        self.assertTrue(ok, msg=req)
        self.assertEqual(req.headers["Authorization"], "Bearer sk")

    def test_probe_query_auth_all_protocols(self):
        # .as AppendQueryAuth 同时用于翻译与登录自检：probe URL 也带 ?key=
        cases = {
            "openai:gpt-4o-mini|auth=query": "/v1/models?key=",
            "anthropic:claude-x|auth=query": "/v1/models?key=",
            "ollama:qwen3:4b|auth=query": "/api/tags?key=",
            "gemini:gemini-x|auth=query": "/v1beta/models?key=",
        }
        for line, suffix in cases.items():
            with self.subTest(line=line):
                ok, req = ref_impl.build_probe_request(spec_of(line), "my key")
                self.assertTrue(ok, msg=req)
                self.assertEqual(req.method, "GET")
                self.assertTrue(req.url.endswith(suffix + "my%20key"), msg=req.url)
                self.assertNotIn("Authorization", req.headers)
                self.assertNotIn("x-api-key", req.headers)
                self.assertNotIn("x-goog-api-key", req.headers)

    def test_probe_query_auth_explicit_keyname(self):
        ok, req = ref_impl.build_probe_request(
            spec_of("openai:gpt-4o-mini|auth=query;keyname=k"), "tok"
        )
        self.assertTrue(ok, msg=req)
        self.assertTrue(req.url.endswith("/v1/models?k=tok"), msg=req.url)

    def test_probe_unsupported_for_custom(self):
        ok, err = ref_impl.build_probe_request(spec_of("custom|http://h/x|m"), "k")
        self.assertFalse(ok)
        self.assertEqual(err.code, "unsupported")

    def test_parse_models_response_shapes(self):
        spec = spec_of("openai:mock-model")
        shapes = [
            ({"data": [{"id": "a"}, {"id": "b"}]}, ["a", "b"]),
            ({"models": [{"name": "qwen3:4b"}]}, ["qwen3:4b"]),
            ([{"id": "x"}, "y"], ["x", "y"]),
            ({"data": []}, []),
            ({}, []),
        ]
        for payload, expected in shapes:
            with self.subTest(payload=payload):
                ok, names = ref_impl.parse_models_response(spec, 200, payload)
                self.assertTrue(ok, msg=names)
                self.assertEqual(names, expected)

    def test_parse_models_strips_models_prefix_everywhere(self):
        spec = spec_of("gemini:gemini-x")
        payload = {"models": [{"name": "models/gemini-1"}, {"name": "models/models/x"}]}
        ok, names = ref_impl.parse_models_response(spec, 200, payload)
        self.assertTrue(ok, msg=names)
        self.assertEqual(names, ["gemini-1", "x"])

    def test_parse_models_bad_json_and_status(self):
        spec = spec_of("openai:mock-model")
        ok, err = ref_impl.parse_models_response(spec, 200, "not json")
        self.assertFalse(ok)
        self.assertEqual(err.code, "bad_json")
        ok, err = ref_impl.parse_models_response(spec, 401, '{"error":{"message":"no"}}')
        self.assertFalse(ok)
        self.assertEqual(err.code, "auth_failed")

    def test_model_matched_semantics(self):
        self.assertTrue(ref_impl.model_matched(["Qwen3:4B"], "qwen3:4b"))
        self.assertTrue(ref_impl.model_matched(["qwen3:4b"], "qwen3"))
        self.assertFalse(ref_impl.model_matched(["qwen3:4b"], "qwen"))
        self.assertFalse(ref_impl.model_matched([], "any"))
        self.assertTrue(ref_impl.model_matched(["gpt-4o-mini"], "GPT-4O-MINI"))

    def test_join_models(self):
        self.assertEqual(ref_impl.join_models(["a", "b"]), "a, b")
        self.assertEqual(ref_impl.join_models([str(i) for i in range(10)], 3), "0, 1, 2 ...")

    def test_login_preflight_checks(self):
        ok, err = ref_impl.login("openai:gpt-4o-mini", "")
        self.assertFalse(ok)
        self.assertEqual(err.code, "auth_needed")
        self.assertIn("API Key", err.message)

        # Ollama 的 /api/chat 必须带 model，登录前就拒绝空模型
        ok, err = ref_impl.login("ollama", "")
        self.assertFalse(ok)
        self.assertEqual(err.code, "config_error")
        self.assertIn("必须指定模型名", err.message)
        self.assertIn("ollama:<model>", err.message)

    def test_login_local_none_auth_allows_empty_key(self):
        # probe=none 避免真正发请求
        ok, msg = ref_impl.login("lmstudio|probe=none", "")
        self.assertTrue(ok, msg=msg)
        self.assertEqual(msg, "200 ok")

    def test_login_probe_none_skips_without_request(self):
        ok, msg = ref_impl.login("deepseek:deepseek-chat|probe=none", "k")
        self.assertTrue(ok, msg=msg)
        self.assertEqual(msg, "200 ok")

    def test_login_parse_error_passthrough(self):
        ok, err = ref_impl.login("nope:model", "k")
        self.assertFalse(ok)
        self.assertEqual(err.code, "bad_preset")


# ---------------------------------------------------------------------------
# mock 服务端到端（真实 HTTP 收发）
# ---------------------------------------------------------------------------


class TestMockServerE2E(unittest.TestCase):
    """真实 HTTP：ref_impl -> mock_server -> ref_impl，并断言服务端收到的请求。"""

    @classmethod
    def setUpClass(cls):
        cls.mock = mock_server.MockServer(scenario="ok", slow_seconds=2.0).start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def setUp(self):
        self.mock.reset()

    # -- 工具 -------------------------------------------------------------

    def _spec(self, line, scenario="ok"):
        ok, spec = ref_impl.parse_spec(line)
        self.assertTrue(ok, msg=f"spec 解析失败：{line!r} -> {spec}")
        if spec.preset == "custom":
            return dataclasses.replace(
                spec, url=f"{self.mock.url}/s/{scenario}/custom/translate"
            )
        return dataclasses.replace(spec, base=f"{self.mock.url}/s/{scenario}")

    def _translate(self, line, scenario="ok", key="sk-test", text="Hello",
                   src="English", dst="Chinese", timeout=5.0):
        spec = self._spec(line, scenario)
        return ref_impl.translate_with_spec(
            spec, key=key, text=text, src=src, dst=dst, timeout=timeout
        )

    def _login(self, line, scenario="ok", key="sk-test", timeout=5.0):
        spec = self._spec(line, scenario)
        return ref_impl.login(spec, key, timeout=timeout)

    def _last(self):
        record = self.mock.last_request()
        self.assertIsNotNone(record, msg="mock 没有记录到请求")
        return record

    def _assert_no_problems(self, record):
        self.assertEqual(record["problems"], [], msg=f"请求不符合契约：{record['problems']}")

    # -- OpenAI 兼容 ------------------------------------------------------

    def test_openai_success_and_recorded_request(self):
        ok, text = self._translate("deepseek:deepseek-chat")
        self.assertTrue(ok, msg=text)
        self.assertEqual(text, mock_server.OPENAI_TEXT)

        record = self._last()
        self.assertEqual(record["method"], "POST")
        self.assertEqual(record["route"], "openai")
        self.assertEqual(record["route_path"], "/chat/completions")
        self._assert_no_problems(record)
        self.assertEqual(record["headers"]["authorization"], "Bearer sk-test")
        self.assertEqual(record["headers"]["content-type"], "application/json")
        self.assertEqual(record["headers"]["accept"], "application/json")
        body = record["body_json"]
        self.assertEqual(body["model"], "deepseek-chat")
        self.assertIs(body["stream"], False)
        self.assertEqual(body["temperature"], 0.2)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(
            body["messages"][0]["content"],
            ref_impl.build_prompt("Hello", "English", "Chinese"),
        )

    def test_openai_preset_default_model_recorded(self):
        ok, text = self._translate("deepseek")
        self.assertTrue(ok, msg=text)
        self.assertEqual(self._last()["body_json"]["model"], "deepseek-v4-flash")

    def test_openai_content_array_scenario(self):
        ok, text = self._translate("deepseek:deepseek-chat", scenario="array")
        self.assertTrue(ok, msg=text)
        self.assertEqual(text, "\n".join(mock_server.OPENAI_ARRAY_PARTS))

    def test_openai_mixed_scenario_skips_thinking_part(self):
        ok, text = self._translate("deepseek:deepseek-chat", scenario="mixed")
        self.assertTrue(ok, msg=text)
        self.assertEqual(text, "\n".join(mock_server.OPENAI_ARRAY_PARTS))

    def test_openai_reasoning_scenario(self):
        ok, err = self._translate("deepseek:deepseek-chat", scenario="reasoning")
        self.assertFalse(ok)
        self.assertEqual(err.code, "reasoning_only")

    def test_openai_empty_scenario(self):
        ok, err = self._translate("deepseek:deepseek-chat", scenario="empty")
        self.assertFalse(ok)
        self.assertEqual(err.code, "no_content")

    def test_openai_minimal_body_recorded(self):
        ok, text = self._translate("deepseek:deepseek-chat|minimal=1")
        self.assertTrue(ok, msg=text)
        body = self._last()["body_json"]
        self.assertEqual(
            body,
            {
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": ref_impl.build_prompt(
                    "Hello", "English", "Chinese")}],
                "stream": False,
            },
        )

    def test_openai_max_tokens_recorded(self):
        ok, text = self._translate("deepseek:deepseek-chat|max_tokens=512")
        self.assertTrue(ok, msg=text)
        self.assertEqual(self._last()["body_json"]["max_completion_tokens"], 512)

    def test_openai_without_key_sends_no_authorization(self):
        ok, text = self._translate("lmstudio", key="")
        self.assertTrue(ok, msg=text)
        record = self._last()
        self.assertNotIn("authorization", record["headers"])

    # -- Anthropic --------------------------------------------------------

    def test_anthropic_success_and_recorded_request(self):
        ok, text = self._translate("anthropic:claude-sonnet-4-5", key="sk-ant-test")
        self.assertTrue(ok, msg=text)
        self.assertEqual(text, "\n".join(mock_server.ANTHROPIC_PARTS))

        record = self._last()
        self.assertEqual(record["route"], "anthropic")
        self.assertEqual(record["route_path"], "/v1/messages")
        self._assert_no_problems(record)
        self.assertEqual(record["headers"]["x-api-key"], "sk-ant-test")
        self.assertEqual(record["headers"]["anthropic-version"], "2023-06-01")
        body = record["body_json"]
        self.assertEqual(body["model"], "claude-sonnet-4-5")
        self.assertEqual(body["max_tokens"], 1024)
        self.assertNotIn("temperature", body)

    def test_anthropic_mixed_scenario_skips_thinking(self):
        ok, text = self._translate("anthropic:claude-x", scenario="mixed")
        self.assertTrue(ok, msg=text)
        self.assertEqual(text, "\n".join(mock_server.ANTHROPIC_PARTS))

    # -- Gemini -----------------------------------------------------------

    def test_gemini_success_and_recorded_request(self):
        ok, text = self._translate(
            "gemini:gemini-2.5-flash", key="gm-key", text="Hello"
        )
        self.assertTrue(ok, msg=text)
        self.assertEqual(text, "\n".join(mock_server.GEMINI_PARTS))

        record = self._last()
        self.assertEqual(record["route"], "gemini")
        self.assertNotIn("gm-key", record["path"])
        self.assertNotIn("key", record["query"])
        self.assertIn("/v1beta/models/gemini-2.5-flash:generateContent", record["route_path"])
        self._assert_no_problems(record)
        self.assertEqual(record["headers"]["x-goog-api-key"], "gm-key")
        body = record["body_json"]
        self.assertEqual(
            body["contents"][0]["parts"][0]["text"],
            ref_impl.build_prompt("Hello", "English", "Chinese"),
        )
        self.assertEqual(body["generationConfig"]["temperature"], 0.2)
        self.assertEqual(body["generationConfig"]["thinkingConfig"], {"thinkingBudget": 0})

    def test_gemini_mixed_scenario_skips_thought(self):
        ok, text = self._translate("gemini:gemini-2.5-flash", scenario="mixed")
        self.assertTrue(ok, msg=text)
        self.assertEqual(text, "\n".join(mock_server.GEMINI_PARTS))

    # -- Ollama -----------------------------------------------------------

    def test_ollama_success_and_recorded_request(self):
        ok, text = self._translate("ollama:qwen3:4b")
        self.assertTrue(ok, msg=text)
        self.assertEqual(text, mock_server.OLLAMA_TEXT)

        record = self._last()
        self.assertEqual(record["route"], "ollama")
        self.assertEqual(record["route_path"], "/api/chat")
        self._assert_no_problems(record)
        self.assertNotIn("authorization", record["headers"])
        body = record["body_json"]
        self.assertEqual(body["model"], "qwen3:4b")
        self.assertEqual(body["options"]["temperature"], 0.2)
        self.assertIs(body["think"], False)
        self.assertIs(body["stream"], False)

    def test_ollama_mixed_scenario_uses_content_not_thinking(self):
        ok, text = self._translate("ollama:qwen3:4b", scenario="mixed")
        self.assertTrue(ok, msg=text)
        self.assertEqual(text, mock_server.OLLAMA_TEXT)

    # -- 自定义 JSON API ---------------------------------------------------

    def test_custom_default_path_success(self):
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|mock-model"
        ok, text = self._translate(line)
        self.assertTrue(ok, msg=text)
        self.assertEqual(text, mock_server.CUSTOM_TEXTS[ref_impl.DEFAULT_CUSTOM_PATH])
        record = self._last()
        self.assertEqual(record["route"], "custom")
        self.assertEqual(record["headers"]["authorization"], "Bearer sk-test")
        self._assert_no_problems(record)

    def test_custom_path_result_translation(self):
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|mock-model|path=result.translation"
        ok, text = self._translate(line)
        self.assertTrue(ok, msg=text)
        self.assertEqual(text, mock_server.CUSTOM_TEXTS["result.translation"])

    def test_custom_path_data_text(self):
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|mock-model|path=data[0].text"
        ok, text = self._translate(line)
        self.assertTrue(ok, msg=text)
        self.assertEqual(text, mock_server.CUSTOM_TEXTS["data[0].text"])

    def test_custom_auth_x_api_key_recorded(self):
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|m|auth=x-api-key;keyname=api-key"
        ok, text = self._translate(line, key="sk-custom")
        self.assertTrue(ok, msg=text)
        record = self._last()
        self.assertEqual(record["headers"]["api-key"], "sk-custom")
        self.assertNotIn("authorization", record["headers"])

    def test_custom_auth_query_recorded(self):
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|m|auth=query;keyname=k"
        ok, text = self._translate(line, key="hello world")
        self.assertTrue(ok, msg=text)
        record = self._last()
        self.assertEqual(record["query"]["k"], "hello world")

    def test_auth_query_translate_recorded(self):
        # .as AppendQueryAuth：翻译 URL 带 ?key=，无认证头
        ok, text = self._translate(
            "openai:mock-model-a|auth=query", key="sk-query/with+chars"
        )
        self.assertTrue(ok, msg=text)
        record = self._last()
        self.assertEqual(record["query"]["key"], "sk-query/with+chars")
        self.assertNotIn("authorization", record["headers"])
        self._assert_no_problems(record)

    def test_gemini_auth_query_translate_recorded(self):
        ok, text = self._translate("gemini:gemini-mock-1|auth=query", key="gm-query")
        self.assertTrue(ok, msg=text)
        record = self._last()
        self.assertEqual(record["query"]["key"], "gm-query")
        self.assertNotIn("x-goog-api-key", record["headers"])
        self._assert_no_problems(record)

    def test_custom_body_template_recorded(self):
        template = (
            '{"p":"{{prompt}}","t":"{{text}}","m":"{{model}}",'
            '"s":"{{src}}","d":"{{dst}}"}'
        )
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|tmpl-model|body={template}"
        ok, text = self._translate(line, text="Hello")
        self.assertTrue(ok, msg=text)
        body = self._last()["body_json"]
        self.assertEqual(body["m"], "tmpl-model")
        self.assertEqual(body["t"], "Hello")
        self.assertEqual(body["s"], "English")
        self.assertEqual(body["d"], "Chinese")
        self.assertEqual(
            body["p"], ref_impl.build_prompt("Hello", "English", "Chinese")
        )

    def test_custom_temperature_and_max_tokens_recorded(self):
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|m|temp=0.7;max_tokens=99"
        ok, text = self._translate(line)
        self.assertTrue(ok, msg=text)
        body = self._last()["body_json"]
        self.assertEqual(body["temperature"], 0.7)
        self.assertEqual(body["max_completion_tokens"], 99)

    def test_rtl_destination_prefixes_u202b(self):
        # .as IsRtlLabel：本地化目标标签（فارسی 等）在译文前加 U+202B
        ok, text = self._translate("deepseek:deepseek-chat", dst="فارسی")
        self.assertTrue(ok, msg=text)
        self.assertTrue(text.startswith("\u202b"), msg=repr(text))
        self.assertEqual(text[1:], mock_server.OPENAI_TEXT)

    # -- 错误场景 ---------------------------------------------------------

    def test_e2e_401_auth_failed(self):
        ok, err = self._translate("deepseek:deepseek-chat", scenario="401")
        self.assertFalse(ok)
        self.assertEqual(err.code, "auth_failed")
        self.assertEqual(err.message, "API Key 无效或已过期 (HTTP 401)")
        self.assertIn("Incorrect API key", err.detail)
        self.assertEqual(self._last()["scenario"], "401")

    def test_e2e_429_rate_limited(self):
        ok, err = self._translate("deepseek:deepseek-chat", scenario="429")
        self.assertFalse(ok)
        self.assertEqual(err.code, "rate_limited")
        self.assertEqual(err.message, "请求过于频繁，请稍后重试 (HTTP 429)")
        self.assertIn("Rate limit reached", err.detail)

    def test_e2e_500_server_error(self):
        ok, err = self._translate("deepseek:deepseek-chat", scenario="500")
        self.assertFalse(ok)
        self.assertEqual(err.code, "server_error")
        self.assertEqual(err.message, "服务端错误 (HTTP 500)，请稍后重试")

    def test_e2e_502_html_server_error(self):
        ok, err = self._translate("deepseek:deepseek-chat", scenario="502")
        self.assertFalse(ok)
        self.assertEqual(err.code, "server_error")
        self.assertEqual(err.message, "服务端错误 (HTTP 502)，请稍后重试")

    def test_e2e_badjson(self):
        ok, err = self._translate("deepseek:deepseek-chat", scenario="badjson")
        self.assertFalse(ok)
        self.assertEqual(err.code, "bad_json")

    def test_e2e_timeout(self):
        with mock_server.MockServer(slow_seconds=2.0) as slow_mock:
            ok, spec = ref_impl.parse_spec("deepseek:deepseek-chat")
            self.assertTrue(ok, msg=spec)
            spec = dataclasses.replace(spec, base=slow_mock.url + "/s/slow")
            ok, err = ref_impl.translate_with_spec(
                spec, "k", "Hello", dst="Chinese", timeout=0.4
            )
        self.assertFalse(ok)
        self.assertEqual(err.code, "timeout")
        self.assertTrue(err.message.startswith("请求超时"), msg=err.message)

    def test_e2e_connection_failure(self):
        # 本机 Windows 安全策略会把“连接被拒绝”表现为超时（并非 RST），
        # 所以这里接受 network/timeout 两者之一；network 的稳定映射在
        # TestErrorMapping.test_perform_raw_and_request_error_mapping 单独覆盖。
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        ok, spec = ref_impl.parse_spec("deepseek:deepseek-chat")
        self.assertTrue(ok, msg=spec)
        spec = dataclasses.replace(spec, base=f"http://127.0.0.1:{port}/v1")
        ok, err = ref_impl.translate_with_spec(spec, "k", "Hello", timeout=0.6)
        self.assertFalse(ok)
        self.assertIn(err.code, ("network", "timeout"))
        self.assertTrue(err.message)

    # -- mock 元接口 -------------------------------------------------------

    def test_requests_endpoint_and_reset(self):
        ok, text = self._translate("deepseek:deepseek-chat")
        self.assertTrue(ok, msg=text)

        with urllib.request.urlopen(self.mock.url + "/__requests", timeout=5) as resp:
            records = json.loads(resp.read().decode("utf-8"))
        self.assertIsInstance(records, list)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["route"], "openai")
        self.assertEqual(records[0]["method"], "POST")

        with urllib.request.urlopen(self.mock.url + "/__last", timeout=5) as resp:
            last = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(last["id"], records[0]["id"])

        request = urllib.request.Request(self.mock.url + "/__reset", method="DELETE")
        with urllib.request.urlopen(request, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["cleared"], 1)
        self.assertEqual(self.mock.requests(), [])

    def test_health_endpoint(self):
        with urllib.request.urlopen(self.mock.url + "/__health", timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["scenario"], "ok")
        self.assertIsInstance(payload["routes"], list)

    def test_scenario_via_query_param(self):
        body = json_text({
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
            "temperature": 0,
        }).encode("utf-8")
        request = urllib.request.Request(
            self.mock.url + "/chat/completions?__scenario=badjson",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            raw = resp.read().decode("utf-8")
        self.assertFalse(raw.lstrip().startswith("{"))
        self.assertEqual(self._last()["scenario"], "badjson")

    def test_mock_validation_flags_bad_request(self):
        request = urllib.request.Request(
            self.mock.url + "/s/ok/chat/completions",
            data=b'{"messages":[{"role":"user","content":"hi"}]}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5).read()
        except urllib.error.HTTPError:  # mock 仍返回成功，这里只是兜底
            pass
        record = self._last()
        problems = " | ".join(record["problems"])
        self.assertIn("Authorization", problems)
        self.assertIn("model", problems)
        self.assertIn("stream", problems)
        self.assertIn("temperature", problems)

    # -- 模型探测 / 登录自检 ------------------------------------------------

    def test_models_probe_all_providers(self):
        cases = {
            "openai:mock-model-a": (["mock-model-a", "mock-model-b"], "models"),
            "anthropic:mock-model-a": (["mock-model-a", "mock-model-b"], "models"),
            "gemini:gemini-mock-1": (["gemini-mock-1", "gemini-mock-2"], "models_gemini"),
            "ollama:qwen3:4b": (["qwen3:4b", "llama3.2:3b"], "models_ollama"),
        }
        for line, (expected, route) in cases.items():
            with self.subTest(line=line):
                spec = self._spec(line)
                ok, names = ref_impl.fetch_models(spec, "sk-test", timeout=5.0)
                self.assertTrue(ok, msg=names)
                self.assertEqual(names, expected)
                record = self._last()
                self.assertEqual(record["route"], route)
                self.assertEqual(record["method"], "GET")
                self._assert_no_auth_leak(record, "sk-test")

    def _assert_no_auth_leak(self, record, key):
        self.assertNotIn(key, record["path"])
        if record["route"] != "gemini":
            self.assertNotIn(key, json.dumps(record["query"], ensure_ascii=False))

    def test_models_probe_gemini_key_in_header(self):
        spec = self._spec("gemini:gemini-mock-1")
        ok, names = ref_impl.fetch_models(spec, "gm-secret", timeout=5.0)
        self.assertTrue(ok, msg=names)
        record = self._last()
        self.assertEqual(record["headers"]["x-goog-api-key"], "gm-secret")
        self.assertNotIn("gm-secret", record["path"])

    def test_login_success_openai(self):
        ok, msg = self._login("openai:mock-model-a")
        self.assertTrue(ok, msg=msg)
        self.assertEqual(msg, "200 ok")
        record = self._last()
        self.assertEqual(record["route"], "models")
        self.assertEqual(record["method"], "GET")
        self.assertEqual(record["headers"]["authorization"], "Bearer sk-test")
        self.assertEqual(record["headers"]["accept"], "application/json")

    def test_login_success_anthropic_headers(self):
        ok, msg = self._login("anthropic:mock-model-a", key="sk-ant")
        self.assertTrue(ok, msg=msg)
        record = self._last()
        self.assertEqual(record["route"], "models")
        self.assertEqual(record["headers"]["x-api-key"], "sk-ant")
        self.assertEqual(record["headers"]["anthropic-version"], "2023-06-01")

    def test_login_success_gemini_headers(self):
        ok, msg = self._login("gemini:gemini-mock-1", key="gm-key")
        self.assertTrue(ok, msg=msg)
        record = self._last()
        self.assertEqual(record["route"], "models_gemini")
        self.assertEqual(record["headers"]["x-goog-api-key"], "gm-key")

    def test_login_success_ollama_tag_prefix_match(self):
        ok, msg = self._login("ollama:qwen3", key="")
        self.assertTrue(ok, msg=msg)
        self.assertEqual(self._last()["route"], "models_ollama")

    def test_login_model_match_is_case_insensitive(self):
        ok, msg = self._login("openai:MOCK-MODEL-A")
        self.assertTrue(ok, msg=msg)

    def test_login_model_not_found_lists_models(self):
        ok, err = self._login("openai:not-a-real-model")
        self.assertFalse(ok)
        self.assertEqual(err.code, "model_not_found")
        self.assertIn("not-a-real-model", err.message)
        self.assertIn("mock-model-a", err.message)

    def test_login_probe_404_passes(self):
        ok, msg = self._login("openai:whatever|probe=models", scenario="404")
        self.assertTrue(ok, msg=msg)
        self.assertEqual(msg, "200 ok")

    def test_login_probe_405_passes(self):
        ok, msg = self._login("openai:whatever|probe=models", scenario="405")
        self.assertTrue(ok, msg=msg)
        self.assertEqual(msg, "200 ok")

    def test_login_probe_401_fails_with_as_message(self):
        ok, err = self._login("openai:whatever", scenario="401")
        self.assertFalse(ok)
        self.assertEqual(err.code, "auth_failed")
        self.assertEqual(err.message, "API Key 无效或无权限（HTTP 401）")

    def test_login_probe_429_fails_with_as_message(self):
        ok, err = self._login("openai:whatever", scenario="429")
        self.assertFalse(ok)
        self.assertEqual(err.code, "rate_limited")
        self.assertEqual(err.message, "请求过于频繁（HTTP 429），请稍后重试")

    def test_login_probe_500_fails_with_as_message(self):
        ok, err = self._login("openai:whatever", scenario="500")
        self.assertFalse(ok)
        self.assertEqual(err.code, "server_error")
        self.assertEqual(err.message, "服务端错误（HTTP 500），请稍后重试")

    def test_login_probe_none_sends_no_request(self):
        ok, msg = self._login("openai:whatever|probe=none")
        self.assertTrue(ok, msg=msg)
        self.assertEqual(self.mock.requests(), [])

    def test_login_custom_never_probes(self):
        line = f"custom|{CUSTOM_PLACEHOLDER_URL}|mock-model"
        ok, msg = self._login(line)
        self.assertTrue(ok, msg=msg)
        self.assertEqual(self.mock.requests(), [])

    def test_login_query_auth_probe_uses_query(self):
        # .as AppendQueryAuth 同时用于 Probe：登录自检 URL 带 ?key=，无认证头
        ok, msg = self._login("openai:mock-model-a|auth=query", key="sk-query")
        self.assertTrue(ok, msg=msg)
        record = self._last()
        self.assertEqual(record["route"], "models")
        self.assertEqual(record["query"]["key"], "sk-query")
        self.assertNotIn("authorization", record["headers"])

    def test_login_gemini_query_auth_probe_uses_query(self):
        ok, msg = self._login("gemini:gemini-mock-1|auth=query", key="gm-query")
        self.assertTrue(ok, msg=msg)
        record = self._last()
        self.assertEqual(record["route"], "models_gemini")
        self.assertEqual(record["query"]["key"], "gm-query")
        self.assertNotIn("x-goog-api-key", record["headers"])
        self.assertNotIn("authorization", record["headers"])

    def test_login_missing_key_returns_as_message(self):
        ok, err = self._login("openai:mock-model-a", key="")
        self.assertFalse(ok)
        self.assertEqual(err.code, "auth_needed")
        self.assertEqual(err.message, "请在密码框填写 API Key（本机服务可把 auth 设为 none）")

    def test_login_network_error_message(self):
        # 端口关闭（本机会超时）→ 登录返回可读错误，而不是抛异常
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        ok, spec = ref_impl.parse_spec("openai:mock-model-a")
        self.assertTrue(ok, msg=spec)
        spec = dataclasses.replace(spec, base=f"http://127.0.0.1:{port}/v1")
        ok2, err = ref_impl.login(spec, "k", timeout=0.6)
        self.assertFalse(ok2)
        self.assertIn(err.code, ("network", "timeout"))
        self.assertTrue(err.message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
