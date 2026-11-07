"""AnyTranslate 契约测试的 Python 参考实现（仅标准库，不依赖第三方包）。

**契约唯一事实来源**：`plugin/SubtitleTranslate - AnyTranslate.as` + `docs/DESIGN.md`。
本文件按当前 `.as` 实现逐函数镜像（函数名对应关系见 `docs/testing/CONTRACT.md`），
供 `tests/test_contract.py` 断言、供人工把断言映射回 `.as`。

硬性约定
--------
1. 所有公开函数“永不抛异常”，统一返回 ``(ok, payload)``：
   - 成功：``(True, payload)``；
   - 失败：``(False, Err(code, message, status=None, detail=""))``。
2. 请求体按 UTF-8 编码的合法 JSON，转义规则镜像 `.as` 的 ``JsonEscape``：
   删除 ``\\x00-\\x08 \\x0B \\x0C \\x0E-\\x1F`` 控制字符（JSON 不允许裸控制符），
   ``\\t \\n \\r`` 用短转义，其余 ``\\`` / ``"`` 转义，非 ASCII 原样保留。
3. 错误原因按 HTTP 状态码映射为**稳定中文文案**（:data:`STATUS_MESSAGES`）；
   **登录自检**（:func:`login`）的文案则与 `.as` 的 ``Probe()`` 逐字一致。

与 `.as` 的镜像关系（详见 CONTRACT.md §7 交叉核对清单）
------------------------------------------------------------
====================  ==================================
ref_impl              .as
====================  ==================================
PRESETS               ``P_ID/P_BASE/P_MODEL/P_PROTO/P_AUTH/P_KEYNAME/P_EXTRA``
parse_spec            ``ParseSpec``
build_request         ``BuildUrl`` + ``BuildHeaders`` + ``BuildBody``
build_probe_request   ``ProbeUrl`` + ``BuildHeaders``
parse_models_response ``ParseModels``
model_matched         ``ModelMatched``
login                 ``ServerLogin`` + ``Probe``
parse_response        ``SendOnce`` + ``ExtractByPath`` + ``NodeText`` + ``CleanTranslation``
clean_text            ``CleanTranslation`` + ``StripKnownPrefixes``
json_escape           ``JsonEscape``
safe_url / mask_key   ``SafeUrl`` / ``MaskKey``
====================  ==================================
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 常量（与 .as 顶部常量表逐项对应）
# ---------------------------------------------------------------------------

DEFAULT_SPEC = "ollama:qwen3:4b"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_ANTHROPIC_MAX_TOKENS = 1024
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT = 30.0

PROBE_TIMEOUT = 15.0  # .as Probe(): HostIncTimeOut(15000)
SEND_TIMEOUT = 20.0  # .as SendOnce(): HostIncTimeOut(20000)

KIND_OPENAI = "openai"
KIND_ANTHROPIC = "anthropic"
KIND_GEMINI = "gemini"
KIND_OLLAMA = "ollama"
KIND_CUSTOM = "custom"

AUTH_MODES = ("bearer", "x-api-key", "query", "none")
PROBE_MODES = ("models", "none")
OPTS_KEYS = (
    "path",
    "auth",
    "keyname",
    "body",
    "temp",
    "max_tokens",
    "probe",
    "debug",
    "version",
    "minimal",
)

#: 错误码 -> 稳定中文原因（HTTP 状态码映射；测试逐条断言）
STATUS_MESSAGES: Dict[str, str] = {
    "bad_request": "请求参数错误 (HTTP 400)",
    "auth_failed": "API Key 无效或已过期 (HTTP 401)",
    "insufficient_balance": "账户余额不足 (HTTP 402)",
    "forbidden": "没有访问权限 (HTTP 403)",
    "not_found": "接口地址或模型不存在 (HTTP 404)",
    "timeout": "请求超时 (HTTP 408)",
    "payload_too_large": "请求体过大 (HTTP 413)",
    "invalid_params": "参数非法 (HTTP 422)",
    "rate_limited": "请求过于频繁，请稍后重试 (HTTP 429)",
    "client_error": "请求被拒绝 (HTTP {status})",
    "server_error": "服务端错误 (HTTP {status})，请稍后重试",
    "http_error": "非预期 HTTP 状态 (HTTP {status})",
}

DEFAULT_PATHS: Dict[str, str] = {
    KIND_OPENAI: "choices[0].message.content",
    KIND_ANTHROPIC: "content",
    KIND_GEMINI: "candidates[0].content.parts",
    KIND_OLLAMA: "message.content",
}
DEFAULT_CUSTOM_PATH = DEFAULT_PATHS[KIND_OPENAI]

#: 目标语言 RTL 集合（镜像 .as IsRtlLabel：L_CODE 中只有 ar/he/fa/ur）
_RTL_LANGS = {
    "ar", "arabic",
    "he", "hebrew",
    "fa", "persian",
    "ur", "urdu",
}


@dataclass(frozen=True)
class Err:
    """解析/请求失败结果（区别于异常：插件侧不得崩溃）。"""

    code: str
    message: str
    status: Optional[int] = None
    detail: str = ""

    def __str__(self) -> str:
        extra = f" | detail={self.detail}" if self.detail else ""
        status = f" | HTTP {self.status}" if self.status is not None else ""
        return f"[{self.code}] {self.message}{status}{extra}"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class Preset:
    """对应 .as 的 P_ID/P_BASE/P_MODEL/P_PROTO/P_AUTH/P_KEYNAME/P_EXTRA 一行。"""

    name: str
    base: str
    kind: str
    auth: str
    keyname: str = ""
    default_model: str = ""
    extra_body: Dict[str, Any] = field(default_factory=dict)


#: 全部 provider 预设（顺序与 .as P_ID 一致；改这里必须同步 .as 与 DESIGN §5.1）
PRESETS: Dict[str, Preset] = {
    "openai": Preset("openai", "https://api.openai.com/v1", KIND_OPENAI, "bearer",
                     default_model="gpt-5.6-terra"),
    "deepseek": Preset("deepseek", "https://api.deepseek.com/v1", KIND_OPENAI, "bearer",
                       default_model="deepseek-v4-flash",
                       extra_body={"thinking": {"type": "disabled"}}),
    "moonshot": Preset("moonshot", "https://api.moonshot.cn/v1", KIND_OPENAI, "bearer",
                       default_model="kimi-k3.1-pro"),
    "zhipu": Preset("zhipu", "https://open.bigmodel.cn/api/paas/v4", KIND_OPENAI, "bearer",
                    default_model="glm-5.3"),
    "qwen": Preset("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1",
                   KIND_OPENAI, "bearer", default_model="qwen-flash",
                   extra_body={"enable_thinking": False}),
    "siliconflow": Preset("siliconflow", "https://api.siliconflow.cn/v1", KIND_OPENAI,
                          "bearer", default_model="deepseek-ai/DeepSeek-V4-Flash",
                          extra_body={"enable_thinking": False}),
    "openrouter": Preset("openrouter", "https://openrouter.ai/api/v1", KIND_OPENAI,
                         "bearer", default_model="openai/gpt-5.6-terra"),
    "groq": Preset("groq", "https://api.groq.com/openai/v1", KIND_OPENAI, "bearer",
                   default_model="openai/gpt-oss-120b"),
    "xai": Preset("xai", "https://api.x.ai/v1", KIND_OPENAI, "bearer",
                  default_model="grok-4.20"),
    "mistral": Preset("mistral", "https://api.mistral.ai/v1", KIND_OPENAI, "bearer",
                      default_model="mistral-small-latest"),
    "together": Preset("together", "https://api.together.ai/v1", KIND_OPENAI, "bearer",
                       default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    "lmstudio": Preset("lmstudio", "http://127.0.0.1:1234/v1", KIND_OPENAI, "none"),
    "vllm": Preset("vllm", "http://127.0.0.1:8000/v1", KIND_OPENAI, "none"),
    "ollama": Preset("ollama", "http://127.0.0.1:11434", KIND_OLLAMA, "none",
                     default_model="qwen3:4b"),
    "anthropic": Preset("anthropic", "https://api.anthropic.com", KIND_ANTHROPIC,
                        "x-api-key", keyname="x-api-key",
                        default_model="claude-sonnet-4-6"),
    "gemini": Preset("gemini", "https://generativelanguage.googleapis.com", KIND_GEMINI,
                     "x-api-key", keyname="x-goog-api-key",
                     default_model="gemini-3.5-flash"),
    "custom": Preset("custom", "", KIND_OPENAI, "bearer"),
}

PRESET_ORDER: Tuple[str, ...] = tuple(PRESETS.keys())


@dataclass(frozen=True)
class Spec:
    """login User 字段解析后的完整配置（对应 .as 的 g_* 全局）。"""

    preset: str
    kind: str
    model: str
    base: str = ""
    url: str = ""
    path: str = ""
    auth: str = "bearer"
    keyname: str = ""
    body_template: Optional[str] = None
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: Optional[int] = None
    version: str = DEFAULT_ANTHROPIC_VERSION
    minimal: bool = False
    debug: bool = False
    probe: str = "none"
    extra_body: Dict[str, Any] = field(default_factory=dict)
    raw: str = ""


@dataclass(frozen=True)
class Request:
    """构造好的 HTTP 请求（headers 为请求头字典，body 为 JSON 字符串）。"""

    method: str
    url: str
    headers: Dict[str, str]
    body: str
    timeout: float
    spec: Spec
    kind: str


# ---------------------------------------------------------------------------
# 内部小工具
# ---------------------------------------------------------------------------


def _err(code: str, message: str, status: Optional[int] = None, detail: str = "") -> Err:
    return Err(code=code, message=message, status=status, detail=detail)


def _short(text: Any, limit: int = 200) -> str:
    try:
        s = str(text)
    except Exception:  # pragma: no cover
        return ""
    return s if len(s) <= limit else s[:limit] + "…"


def _decode_body(raw: Any) -> str:
    """把响应字节/字符串统一成文本；解码失败用 replacement 字符，绝不抛异常。"""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        return raw
    try:
        return str(raw)
    except Exception:  # pragma: no cover
        return ""


def _split_first(text: str, sep: str) -> Tuple[str, Optional[str]]:
    idx = text.find(sep)
    if idx < 0:
        return text, None
    return text[:idx], text[idx + len(sep):]


def _sanitize_temperature(value: Any) -> float:
    """镜像 .as：删除非 [0-9.] 字符；空串回退 0.2。非法浮点回退 0.2（ref 更稳）。"""
    raw = "" if value is None else str(value)
    cleaned = re.sub(r"[^0-9.]", "", raw)
    if not cleaned:
        return DEFAULT_TEMPERATURE
    try:
        return float(cleaned)
    except ValueError:
        return DEFAULT_TEMPERATURE


def _sanitize_max_tokens(value: Any) -> Optional[int]:
    """镜像 .as：只保留数字；空串 = 不发送。"""
    raw = "" if value is None else str(value)
    digits = re.sub(r"[^0-9]", "", raw)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:  # pragma: no cover
        return None


def _flag(value: Any) -> bool:
    """镜像 .as：仅 '1' / 'true' 视为真。"""
    return ("" if value is None else str(value)).strip().lower() in ("1", "true")


# ---------------------------------------------------------------------------
# JSON 手工转义（镜像 .as JsonEscape；供 .as 逐字符对照）
# ---------------------------------------------------------------------------

#: JSON 不允许裸 C0 控制字符；.as 直接删除除 \t \n \r 之外的控制字符
_DROP_CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def json_escape(text: Any) -> str:
    """镜像 ``.as::JsonEscape``。

    规则（与 .as 逐字符一致）：
    1. **剔除** C0 控制字符（``\\t`` / ``\\n`` / ``\\r`` 除外，即删除
       ``\\x00-\\x08``、``\\x0B``、``\\x0C``、``\\x0E-\\x1F``；``\\b``/``\\f`` 也被删除
       而不是转义；`.as` 用 ``StripChars`` 循环，上限 1024 次）；
    2. ``\\`` -> ``\\\\``、``"`` -> ``\\"``，``\\t`` / ``\\n`` / ``\\r`` 用短转义；
    3. 非 ASCII 原样保留（UTF-8 发送），``/``、``\\u007F``、``\\u2028`` 不特殊处理。
    """
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    s = _DROP_CONTROL_RE.sub("", s)
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    s = s.replace("\t", "\\t")
    return s


def json_quote(text: Any) -> str:
    """返回带外层双引号的 JSON 字符串字面量。"""
    return '"' + json_escape(text) + '"'


def _dumps_value(value: Any) -> str:
    if isinstance(value, str):
        return json_quote(value)
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ",".join(_dumps_value(item) for item in value) + "]"
    if isinstance(value, dict):
        parts = [
            json_quote(str(key)) + ":" + _dumps_value(item)
            for key, item in value.items()
        ]
        return "{" + ",".join(parts) + "}"
    return json_quote(str(value))


def json_dumps_manual(obj: Any) -> str:
    """按 `.as` 手工拼接语义序列化 JSON（字符串走 JsonEscape，控制字符被删除）。"""
    return _dumps_value(obj)


#: 日志脱敏：.as MaskKey（长度 < 16 一律 ****）
def mask_key(key: Any) -> str:
    value = "" if key is None else str(key)
    if not value:
        return "(未设置)"
    if len(value) < 16:
        return "****"
    return value[:4] + "****" + value[-4:]


def host_url_encode(text: Any) -> str:
    """镜像 ``HostUrlEncode``：percent-encode（组件级，保留字符也编码）。"""
    return urllib.parse.quote("" if text is None else str(text), safe="")


#: 日志脱敏：.as SafeUrl（auth=query 时 Key 在 URL 里，可能已被 percent-encode）
def safe_url(url: Any, key: Any = "") -> str:
    """替换 ``HostUrlEncode(key)`` 与原始 ``key`` 两种形式（与 .as 顺序一致）。"""
    raw = "" if url is None else str(url)
    secret = "" if key is None else str(key)
    if not secret:
        return raw
    masked = raw.replace(host_url_encode(secret), "****")
    masked = masked.replace(secret, "****")
    return masked


# ---------------------------------------------------------------------------
# spec 解析（镜像 .as ParseSpec）
# ---------------------------------------------------------------------------


def resolve_provider(preset: Any) -> Tuple[bool, Any]:
    """preset 名 -> Preset；未知预设返回 (False, Err(bad_preset))。"""
    try:
        name = ("" if preset is None else str(preset)).strip().lower()
        if not name:
            return False, _err("bad_preset", "provider 预设为空")
        found = PRESETS.get(name)
        if found is None:
            available = "/".join(PRESET_ORDER)
            return False, _err("bad_preset", f"未知服务商: {name}。可用: {available}")
        return True, found
    except Exception as exc:  # pragma: no cover
        return False, _err("internal_error", f"解析 provider 时发生内部错误：{exc!r}")


def default_path_for(kind: str) -> str:
    """镜像 .as DefaultPathFor。"""
    return DEFAULT_PATHS.get(kind, "")


def parse_opts(text: Any) -> Tuple[bool, Any]:
    """解析 ``key=value;key=value``。

    镜像 .as：格式不合法（无 ``=`` 或 key 为空）的片段**静默跳过**，
    未知 key 也静默忽略（向前兼容）。返回值恒为 ``(True, dict)``。
    """
    try:
        opts: Dict[str, str] = {}
        source = "" if text is None else str(text)
        for segment in source.split(";"):
            segment = segment.strip()
            if not segment:
                continue
            idx = segment.find("=")
            if idx <= 0:  # .as: eq <= 0 -> continue
                continue
            key = segment[:idx].strip()
            value = segment[idx + 1:].strip()
            if key in OPTS_KEYS:
                opts[key] = value
        return True, opts
    except Exception as exc:  # pragma: no cover
        return False, _err("internal_error", f"解析配置选项时发生内部错误：{exc!r}")


def _parse_custom_spec(spec: str) -> Tuple[bool, Any]:
    """``custom|<endpoint>|<model>|[opts]``；endpoint 后可省略 model。"""
    rest = spec[len("custom|"):]
    base, after_base = _split_first(rest, "|")
    base = base.strip()
    model = ""
    opt_str = ""
    if after_base is not None:
        model, after_model = _split_first(after_base, "|")
        model = model.strip()
        if after_model is not None:
            opt_str = after_model  # opts 内允许再出现 '|'
    if not base:
        return False, _err(
            "bad_spec", "custom 缺少 url，应为 custom|<url>|<model>|[opts]"
        )
    return _finish_spec(
        provider="custom",
        base=base,
        model=model,
        opt_str=opt_str,
        is_custom=True,
        raw=spec,
    )


def _parse_preset_spec(spec: str) -> Tuple[bool, Any]:
    """``preset[:model][|opts]``；opts 对预设形式同样生效。"""
    head, after_head = _split_first(spec, "|")
    opt_str = after_head if after_head is not None else ""
    provider, after_colon = _split_first(head, ":")
    provider = provider.strip()
    model = after_colon.strip() if after_colon is not None else ""
    return _finish_spec(
        provider=provider,
        base="",
        model=model,
        opt_str=opt_str,
        is_custom=False,
        raw=spec,
    )


def _finish_spec(
    provider: str,
    base: str,
    model: str,
    opt_str: str,
    is_custom: bool,
    raw: str,
) -> Tuple[bool, Any]:
    provider = provider.strip().lower()
    preset = PRESETS.get(provider)
    if preset is None:
        return False, _err(
            "bad_preset", f"未知服务商: {provider}。可用: {('/'.join(PRESET_ORDER))}"
        )

    ok, opts = parse_opts(opt_str)
    if not ok:
        return False, opts

    # base / model：custom 用用户 URL 且允许空 model；预设 base 由插件提供
    if is_custom:
        endpoint = base
    else:
        endpoint = preset.base
        if not endpoint:
            return False, _err(
                "bad_spec",
                "custom 需要完整 URL，例如 custom|https://host/v1/chat/completions|model",
            )
        if not model:
            model = preset.default_model

    if endpoint and len(endpoint) > 1:
        while endpoint.endswith("/"):
            endpoint = endpoint[:-1]

    auth = opts.get("auth") or preset.auth
    if auth not in AUTH_MODES:
        return False, _err("bad_opts", "auth 只能是 bearer / x-api-key / query / none")

    explicit_keyname = bool(opts.get("keyname"))
    keyname = opts.get("keyname") or preset.keyname
    if not keyname:
        if auth == "bearer":
            keyname = "Authorization"
        elif auth == "x-api-key":
            keyname = "x-api-key"
        else:
            keyname = "key"
    # .as：auth=query 时参数名必须能作为 query key 使用；用户显式 keyname= 优先
    if auth == "query" and not explicit_keyname:
        keyname = "key"

    kind = preset.kind
    path = opts.get("path") or ("" if is_custom else default_path_for(kind))
    if not path:
        path = default_path_for(KIND_OPENAI)

    probe = "none" if (is_custom or provider == "custom") else "models"
    if "probe" in opts:
        # .as 不校验 probe 取值：只要不是 none 就会执行自检
        probe = opts["probe"].strip().lower()

    temperature = _sanitize_temperature(opts.get("temp"))
    max_tokens = _sanitize_max_tokens(opts.get("max_tokens"))
    version = opts.get("version") or DEFAULT_ANTHROPIC_VERSION
    body_template = opts.get("body") or None
    extra_body: Dict[str, Any] = {} if (is_custom or provider == "custom") else dict(preset.extra_body)

    return True, Spec(
        preset=provider,
        kind=kind,
        model=model,
        base=endpoint,
        url=endpoint if (is_custom or provider == "custom") else "",
        path=path,
        auth=auth,
        keyname=keyname,
        body_template=body_template,
        temperature=temperature,
        max_tokens=max_tokens,
        version=version,
        minimal=_flag(opts.get("minimal")),
        debug=_flag(opts.get("debug")),
        probe=probe,
        extra_body=extra_body,
        raw=raw,
    )


def parse_spec(user: Any = None, default: str = DEFAULT_SPEC) -> Tuple[bool, Any]:
    """解析 login User 字段，返回 ``(True, Spec)`` 或 ``(False, Err)``。永不抛异常。

    * 空/纯空白 -> 默认 ``ollama:qwen3:4b``（首装默认；`.as` 登录时优先沿用上次保存值，
      该持久化行为不属纯函数契约，见 CONTRACT.md D-23）；
    * 以 ``custom|`` 开头 -> custom 形式（大小写敏感，与 `.as` ``StartsWith`` 一致）；
    * 其余 -> preset 形式；model 只按第一个 ``:`` 切分；``|opts`` 对两种形式都生效。
    """
    try:
        raw = "" if user is None else str(user)
        text = raw.strip()
        if not text:
            text = (DEFAULT_SPEC if default is None else str(default)).strip()
        if not text:
            text = DEFAULT_SPEC
        if text.startswith("custom|"):
            return _parse_custom_spec(text)
        return _parse_preset_spec(text)
    except Exception as exc:  # pragma: no cover
        return False, _err("internal_error", f"解析 spec 时发生内部错误：{exc!r}")


# ---------------------------------------------------------------------------
# 请求构造（镜像 .as BuildUrl / BuildHeaders / BuildBody）
# ---------------------------------------------------------------------------


def build_prompt(text: Any, src: Any = "", dst: Any = "Chinese") -> str:
    """构造 user prompt（措辞**不属于契约**，.as 另有更完整的中文提示词）。"""
    dst_text = ("" if dst is None else str(dst)).strip() or "Chinese"
    src_text = ("" if src is None else str(src)).strip()
    from_part = ""
    if src_text and src_text.lower() not in ("auto", "自动", "自动检测"):
        from_part = f" from {src_text}"
    body = "" if text is None else str(text)
    return (
        f"Translate{from_part} to {dst_text}. "
        "Output only the translated subtitle text, no explanations, no quotes; "
        "keep line breaks and punctuation as in the input:\n"
        + body
    )


def build_url(spec: Spec, key: str = "") -> str:
    """镜像 .as BuildUrl（含 auth=query 时把 Key 拼进 URL）。"""
    url = spec.url if spec.preset == "custom" else spec.base
    if spec.preset != "custom":
        if spec.kind == KIND_OPENAI:
            url = url + "/chat/completions"
        elif spec.kind == KIND_ANTHROPIC:
            url = url + "/v1/messages"
        elif spec.kind == KIND_GEMINI:
            url = url + "/v1beta/models/" + spec.model + ":generateContent"
        elif spec.kind == KIND_OLLAMA:
            url = url + "/api/chat"
    if spec.auth == "query" and key:
        sep = "?" if "?" not in url else "&"
        url = url + sep + spec.keyname + "=" + urllib.parse.quote(key, safe="")
    return url


def build_headers(spec: Spec, key: str = "") -> Dict[str, str]:
    """镜像 .as BuildHeaders（Content-Type + Accept + 认证头）。"""
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if spec.auth == "bearer" and key:
        headers["Authorization"] = "Bearer " + key
    elif spec.auth == "x-api-key" and key:
        headers[spec.keyname or "x-api-key"] = key
        if spec.kind == KIND_ANTHROPIC:
            headers["anthropic-version"] = spec.version
    return headers


def build_body(
    spec: Spec,
    prompt: str,
    text: str = "",
    src: str = "",
    dst: str = "",
) -> Tuple[bool, Any]:
    """镜像 .as BuildBody；返回 (True, body 字符串) 或 (False, Err)。

    ref 额外做“模板替换后必须仍是合法 JSON”的校验（.as 不校验，属安全增强，
    见 CONTRACT.md D-24）；其余分支与 `.as` 逐字段一致。
    """
    if spec.preset == "custom" and spec.body_template:
        rendered = spec.body_template
        replacements = {
            "{{prompt}}": prompt,
            "{{text}}": text,
            "{{model}}": spec.model,
            "{{src}}": src,
            "{{dst}}": dst,
        }
        for placeholder, value in replacements.items():
            rendered = rendered.replace(placeholder, json_escape(value))
        try:
            json.loads(rendered)
        except Exception as exc:
            return False, _err(
                "bad_body_template",
                "body 模板替换后不是合法 JSON，请检查模板与 {{占位符}}",
                detail=_short(exc),
            )
        return True, rendered

    body: Dict[str, Any] = {}
    if spec.model:
        body["model"] = spec.model
    body["messages"] = [{"role": "user", "content": prompt}]

    if spec.kind == KIND_ANTHROPIC:
        body["max_tokens"] = (
            spec.max_tokens
            if spec.max_tokens is not None
            else DEFAULT_ANTHROPIC_MAX_TOKENS
        )
        return True, json_dumps_manual(body)

    if spec.kind == KIND_GEMINI:
        generation: Dict[str, Any] = {"temperature": spec.temperature}
        if spec.max_tokens is not None:
            generation["maxOutputTokens"] = spec.max_tokens
        if not spec.minimal:
            generation["thinkingConfig"] = {"thinkingBudget": 0}
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": generation,
        }
        return True, json_dumps_manual(body)

    if spec.kind == KIND_OLLAMA:
        body["stream"] = False
        if not spec.minimal:
            body["think"] = False
            options: Dict[str, Any] = {"temperature": spec.temperature}
            if spec.max_tokens is not None:
                options["num_predict"] = spec.max_tokens
            body["options"] = options
        return True, json_dumps_manual(body)

    # openai 兼容（含 custom 默认体）
    body["stream"] = False
    if not spec.minimal:
        body["temperature"] = spec.temperature
        if spec.max_tokens is not None:
            body["max_completion_tokens"] = spec.max_tokens
        body.update(spec.extra_body)
    return True, json_dumps_manual(body)


def build_request(
    spec: Any,
    key: Any = "",
    prompt: Any = "",
    text: Any = "",
    src: Any = "",
    dst: Any = "",
    timeout: float = SEND_TIMEOUT,
) -> Tuple[bool, Any]:
    """按 spec 构造 POST 请求，返回 ``(True, Request)`` 或 ``(False, Err)``。永不抛异常。"""
    try:
        if isinstance(spec, Err):
            return False, spec
        if not isinstance(spec, Spec):
            return False, _err("config_error", "内部错误：spec 不是有效配置")
        key_text = "" if key is None else str(key).strip()
        prompt_text = "" if prompt is None else str(prompt)
        text_text = "" if text is None else str(text)
        src_text = "" if src is None else str(src)
        dst_text = "" if dst is None else str(dst)
        ok, body = build_body(spec, prompt_text, text_text, src_text, dst_text)
        if not ok:
            return False, body
        return True, Request(
            method="POST",
            url=build_url(spec, key_text),
            headers=build_headers(spec, key_text),
            body=body,
            timeout=float(timeout) if timeout else SEND_TIMEOUT,
            spec=spec,
            kind=spec.kind,
        )
    except Exception as exc:  # pragma: no cover
        return False, _err("internal_error", f"构造请求时发生内部错误：{exc!r}")


def build_probe_request(
    spec: Any, key: Any = "", timeout: float = PROBE_TIMEOUT
) -> Tuple[bool, Any]:
    """镜像 .as ProbeUrl + AppendQueryAuth + BuildHeaders：登录自检用 GET 请求。

    ``auth=query`` 时与翻译请求共用 ``AppendQueryAuth``：探测 URL 同样带
    ``?<keyname>=<urlencoded key>``，且不带任何认证头。
    """
    try:
        if isinstance(spec, Err):
            return False, spec
        if not isinstance(spec, Spec):
            return False, _err("config_error", "内部错误：spec 不是有效配置")
        if spec.preset == "custom":
            return False, _err("unsupported", "custom 预设不支持 probe=models（响应格式不固定）")
        key_text = "" if key is None else str(key).strip()
        if spec.kind == KIND_OPENAI:
            url = spec.base + "/models"
        elif spec.kind == KIND_OLLAMA:
            url = spec.base + "/api/tags"
        elif spec.kind == KIND_ANTHROPIC:
            url = spec.base + "/v1/models"
        elif spec.kind == KIND_GEMINI:
            url = spec.base + "/v1beta/models"
        else:  # pragma: no cover
            return False, _err("unsupported", f"不支持的 provider 类型：{spec.kind}")
        # 与 .as AppendQueryAuth 一致：翻译与探测共用同一段拼 Key 逻辑
        if spec.auth == "query" and key_text:
            sep = "?" if "?" not in url else "&"
            url = url + sep + spec.keyname + "=" + urllib.parse.quote(key_text, safe="")
        return True, Request(
            method="GET",
            url=url,
            headers=build_headers(spec, key_text),
            body="",
            timeout=float(timeout) if timeout else PROBE_TIMEOUT,
            spec=spec,
            kind=spec.kind,
        )
    except Exception as exc:  # pragma: no cover
        return False, _err("internal_error", f"构造模型列表请求时发生内部错误：{exc!r}")


# ---------------------------------------------------------------------------
# HTTP 执行（urllib；异常全部映射为 Err）
# ---------------------------------------------------------------------------


def perform_raw(req: Any) -> Tuple[bool, Any]:
    """执行请求并返回 ``(True, (status, raw_text))`` 或 ``(False, Err)``。"""
    timeout = DEFAULT_TIMEOUT
    try:
        if isinstance(req, Err):
            return False, req
        if not isinstance(req, Request):
            return False, _err("config_error", "内部错误：request 不是有效请求")
        timeout = float(req.timeout) if req.timeout else DEFAULT_TIMEOUT
        headers = dict(req.headers or {})
        data: Optional[bytes] = None
        if req.method.upper() != "GET":
            data = (req.body or "").encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        http_request = urllib.request.Request(
            req.url, data=data, headers=headers, method=req.method.upper()
        )
        try:
            with urllib.request.urlopen(http_request, timeout=timeout) as response:
                status = getattr(response, "status", None) or response.getcode()
                raw = response.read()
        except urllib.error.HTTPError as exc:  # 4xx/5xx：urllib 会抛异常，这里转成状态码
            status = exc.code
            try:
                raw = exc.read()
            except Exception:  # pragma: no cover
                raw = b""
        return True, (int(status), _decode_body(raw))
    except (TimeoutError, socket.timeout):
        return False, _err(
            "timeout", f"请求超时（服务端 {timeout:g} 秒内未响应）", detail="socket timeout"
        )
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return False, _err(
                "timeout", f"请求超时（服务端 {timeout:g} 秒内未响应）", detail="socket timeout"
            )
        return False, _err("network", "网络连接失败：无法连接到服务端", detail=_short(reason))
    except Exception as exc:  # pragma: no cover
        return False, _err("network", "网络连接失败：请求执行失败", detail=_short(repr(exc)))


def _status_code(status: Any) -> Optional[int]:
    try:
        if status is None:
            return None
        return int(status)
    except (TypeError, ValueError):
        return None


def _status_error(status: Any) -> Optional[Err]:
    """HTTP 状态码 -> 稳定 Err；2xx 返回 None。"""
    code = _status_code(status)
    if code is None:
        return _err("http_error", "非预期 HTTP 状态：响应中没有状态码")
    if 200 <= code < 300:
        return None
    if code == 400:
        return _err("bad_request", STATUS_MESSAGES["bad_request"], status=code)
    if code == 401:
        return _err("auth_failed", STATUS_MESSAGES["auth_failed"], status=code)
    if code == 402:
        return _err("insufficient_balance", STATUS_MESSAGES["insufficient_balance"], status=code)
    if code == 403:
        return _err("forbidden", STATUS_MESSAGES["forbidden"], status=code)
    if code == 404:
        return _err("not_found", STATUS_MESSAGES["not_found"], status=code)
    if code == 408:
        return _err("timeout", STATUS_MESSAGES["timeout"], status=code)
    if code == 413:
        return _err("payload_too_large", STATUS_MESSAGES["payload_too_large"], status=code)
    if code == 422:
        return _err("invalid_params", STATUS_MESSAGES["invalid_params"], status=code)
    if code == 429:
        return _err("rate_limited", STATUS_MESSAGES["rate_limited"], status=code)
    if 500 <= code < 600:
        return _err(
            "server_error",
            STATUS_MESSAGES["server_error"].format(status=code),
            status=code,
        )
    if 400 <= code < 500:
        return _err(
            "client_error", STATUS_MESSAGES["client_error"].format(status=code), status=code
        )
    return _err("http_error", STATUS_MESSAGES["http_error"].format(status=code), status=code)


def _extract_provider_message(obj: Any) -> str:
    """尽力从错误响应体中提取服务端原始报错（仅用于 Err.detail）。"""
    try:
        if not isinstance(obj, dict):
            return ""
        error = obj.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
            code = error.get("code")
            if isinstance(code, str) and code.strip():
                return code.strip()
        elif isinstance(error, str) and error.strip():
            return error.strip()
        for key in ("message", "detail", "msg"):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    except Exception:  # pragma: no cover
        return ""


# ---------------------------------------------------------------------------
# JSON 路径解析（镜像 .as ExtractByPath / WalkPath / NodeText）
# ---------------------------------------------------------------------------


def split_path_tokens(path: str) -> List[str]:
    """镜像 .as ``SplitStr(path, ".")``（保留空 token，与 .as 一致）。"""
    return path.split(".")


def _parse_index_token(token: str) -> Tuple[str, Optional[int]]:
    """``name[0]`` -> (name, 0)；``[0]`` -> ("", 0)；非法返回 (-, None)。

    镜像 .as ``DigitToInt``：只支持 **0-9 单数字下标**（DESIGN 6.2）。
    """
    br = token.find("[")
    if br < 0:
        return token, None
    name = token[:br]
    if not token.endswith("]"):
        return name, None
    idx_str = token[br + 1: len(token) - 1]
    if len(idx_str) != 1 or not idx_str.isdigit():
        return name, None
    return name, int(idx_str)


_MISSING = object()


def node_text(node: Any) -> str:
    """镜像 .as NodeText：字符串直取；数组用 ``\\\\n`` 连接非空项；对象跳过思考块。"""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        out = ""
        for item in node:
            piece = node_text(item)
            if piece:
                if out:
                    out += "\n"
                out += piece
        return out
    if isinstance(node, dict):
        if node.get("thought") is True:
            return ""
        node_type = node.get("type")
        if isinstance(node_type, str) and node_type in (
            "thinking",
            "redacted_thinking",
            "reasoning",
        ):
            return ""
        text = node.get("text")
        if isinstance(text, str):
            return text
        content = node.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, (list, dict)):
            return node_text(content)
        return ""
    return ""


def walk_path(node: Any, tokens: List[str], depth: int = 0) -> str:
    """镜像 .as WalkPath。"""
    if depth >= len(tokens):
        return node_text(node)
    token = tokens[depth]
    if "[" in token:
        name, index = _parse_index_token(token)
        if index is None:
            return ""
        if not name:
            if not isinstance(node, list) or index >= len(node):
                return ""
            return walk_path(node[index], tokens, depth + 1)
        if not isinstance(node, dict):
            return ""
        child = node.get(name, _MISSING)
        if not isinstance(child, list) or index >= len(child):
            return ""
        return walk_path(child[index], tokens, depth + 1)
    if not isinstance(node, dict):
        return ""
    child = node.get(token, _MISSING)
    if child is _MISSING:
        return ""
    return walk_path(child, tokens, depth + 1)


def resolve_json_path(obj: Any, path: str) -> Tuple[bool, Any]:
    """按 path 取值；取到非空文本返回 (True, text)，否则 (False, None)。"""
    try:
        if not isinstance(path, str) or not path:
            return False, None
        tokens = split_path_tokens(path)
        value = walk_path(obj, tokens)
        if not value:
            return False, None
        return True, value
    except Exception:  # pragma: no cover
        return False, None


def parse_json_path(path: str) -> Tuple[bool, Any]:
    """校验/展开 path 为 token 列表（ref 辅助函数，镜像 .as 的分隔与下标规则）。"""
    try:
        if not isinstance(path, str) or not path:
            return False, _err("bad_opts", f"path 为空或不是字符串：{path!r}")
        tokens = split_path_tokens(path)
        expanded: List[Any] = []
        for token in tokens:
            if not token:
                return False, _err("bad_opts", f"path 存在空片段：{path!r}")
            if "[" in token:
                name, index = _parse_index_token(token)
                if index is None:
                    return False, _err("bad_opts", f"path 存在非法下标：{path!r}")
                if name:
                    expanded.append(name)
                expanded.append(index)
            else:
                expanded.append(token)
        return True, expanded
    except Exception as exc:  # pragma: no cover
        return False, _err("bad_opts", f"解析 path 时发生内部错误：{exc!r}")


# ---------------------------------------------------------------------------
# 响应解析（镜像 .as SendOnce）
# ---------------------------------------------------------------------------


def _reasoning_only_hint(spec: Spec, obj: Any) -> str:
    """返回思考内容摘要；没有则空串（用于区分 reasoning_only 与 no_content）。"""
    try:
        if spec.kind == KIND_OPENAI and isinstance(obj, dict):
            choices = obj.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                message = choices[0].get("message")
                if isinstance(message, dict):
                    for key in ("reasoning_content", "reasoning"):
                        value = message.get(key)
                        if isinstance(value, str) and value.strip():
                            return value
        if spec.kind == KIND_OLLAMA and isinstance(obj, dict):
            message = obj.get("message")
            if isinstance(message, dict):
                value = message.get("thinking")
                if isinstance(value, str) and value.strip():
                    return value
        if spec.kind == KIND_ANTHROPIC and isinstance(obj, dict):
            content = obj.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") in (
                        "thinking",
                        "redacted_thinking",
                    ):
                        value = item.get("thinking")
                        if isinstance(value, str) and value.strip():
                            return value
        return ""
    except Exception:  # pragma: no cover
        return ""


def parse_response(
    spec: Any, status: Any, raw: Any, dst_lang: str = ""
) -> Tuple[bool, Any]:
    """解析 HTTP 响应，返回 ``(True, cleaned_text)`` 或 ``(False, Err)``。永不抛异常。

    顺序：状态码（4xx/5xx 优先）-> JSON -> ExtractByPath/NodeText -> CleanTranslation。
    对“200 但 content 为空且存在 reasoning/thinking”的情况返回 ref 级可区分错误码
    ``reasoning_only``（`.as` 侧表现为 SendOnce 失败，见 CONTRACT.md §3.5）。
    """
    try:
        if isinstance(spec, Err):
            return False, spec
        if not isinstance(spec, Spec):
            return False, _err("config_error", "内部错误：spec 不是有效配置")
        if isinstance(raw, (dict, list)):
            obj: Any = raw
            parsed = True
            text_body = json.dumps(raw, ensure_ascii=False)
        else:
            text_body = _decode_body(raw)
            obj = None
            parsed = False
            if text_body.strip():
                try:
                    obj = json.loads(text_body)
                    parsed = True
                except Exception:
                    parsed = False
        status_error = _status_error(status)

        if status_error is not None:
            detail = _extract_provider_message(obj)
            if detail:
                status_error = replace(status_error, detail=_short(detail))
            return False, status_error

        if not text_body.strip():
            return False, _err(
                "empty_response", "服务端返回空响应", status=_status_code(status)
            )
        if not parsed:
            return False, _err(
                "bad_json",
                "响应不是合法 JSON，无法解析",
                status=_status_code(status),
                detail=_short(text_body),
            )

        path = spec.path or default_path_for(spec.kind) or DEFAULT_CUSTOM_PATH
        found, extracted = resolve_json_path(obj, path)
        if not found:
            detail = _extract_provider_message(obj)
            if detail:
                return False, _err("provider_error", "服务端返回错误，未返回译文", detail=detail)
            reasoning = _reasoning_only_hint(spec, obj)
            if reasoning:
                return False, _err(
                    "reasoning_only",
                    "模型只返回了思考过程（reasoning_content），没有输出译文",
                    detail=_short(reasoning),
                )
            return False, _err(
                "no_content", "响应中未找到译文内容", detail=f"path={path}"
            )

        cleaned = clean_text(extracted, dst_lang=dst_lang)
        if not cleaned:
            reasoning = _reasoning_only_hint(spec, obj)
            if reasoning:
                return False, _err(
                    "reasoning_only",
                    "模型只返回了思考过程（reasoning_content），没有输出译文",
                    detail=_short(reasoning),
                )
            return False, _err("no_content", "响应中未找到译文内容", detail="清洗后文本为空")
        return True, cleaned
    except Exception as exc:  # pragma: no cover
        return False, _err("parse_error", "解析响应时发生内部错误", detail=_short(repr(exc)))


def parse_models_response(spec: Any, status: Any, raw: Any) -> Tuple[bool, Any]:
    """镜像 .as ParseModels：返回 ``(True, [model_name, ...])`` 或 ``(False, Err)``。

    注意 ``.as`` 在“JSON 合法但没有 models/data 数组”时返回空列表并放行登录，
    因此无模型列表时返回 ``(True, [])``；只有 JSON 非法才返回失败。
    """
    try:
        if isinstance(spec, Err):
            return False, spec
        if not isinstance(spec, Spec):
            return False, _err("config_error", "内部错误：spec 不是有效配置")
        if isinstance(raw, (dict, list)):
            obj: Any = raw
            text_body = json.dumps(raw, ensure_ascii=False)
        else:
            text_body = _decode_body(raw)
            obj = None
            if text_body.strip():
                try:
                    obj = json.loads(text_body)
                except Exception:
                    obj = None
        status_error = _status_error(status)
        if status_error is not None:
            detail = _extract_provider_message(obj)
            if detail:
                status_error = replace(status_error, detail=_short(detail))
            return False, status_error
        if obj is None:
            return False, _err(
                "bad_json", "响应不是合法 JSON，无法解析", detail=_short(text_body)
            )
        items: Any = obj if isinstance(obj, list) else None
        if items is None and isinstance(obj, dict):
            data = obj.get("data")
            models = obj.get("models")
            if isinstance(data, list):
                items = data
            elif isinstance(models, list):
                items = models
        names: List[str] = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str):
                    names.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                model_id = item.get("id")
                if isinstance(model_id, str):
                    names.append(model_id)
                    continue
                name = item.get("name")
                if isinstance(name, str):
                    # .as StrReplaceAll(name, "models/", "")：删除所有出现
                    names.append(name.replace("models/", ""))
        return True, names
    except Exception as exc:  # pragma: no cover
        return False, _err("parse_error", "解析模型列表时发生内部错误", detail=_short(repr(exc)))


def model_matched(models: List[str], model: str) -> bool:
    """镜像 .as ModelMatched：忽略大小写；允许 ``want:tag`` 前缀匹配。"""
    want = ("" if model is None else str(model)).lower()
    for have in models or []:
        candidate = ("" if have is None else str(have)).lower()
        if candidate == want:
            return True
        if candidate.startswith(want + ":"):
            return True
    return False


def join_models(models: List[str], max_count: int = 6) -> str:
    """镜像 .as JoinModels。"""
    out = ", ".join(list(models or [])[:max_count])
    if len(models or []) > max_count:
        out += " ..."
    return out


# ---------------------------------------------------------------------------
# 登录自检（镜像 .as ServerLogin + Probe）
# ---------------------------------------------------------------------------


def _login_status_error(spec: Spec, status: int, raw: str) -> Err:
    """镜像 .as Probe() 的状态码分支文案。"""
    code = _status_code(status)
    if code == 401:
        return _err("auth_failed", "API Key 无效或无权限（HTTP 401）", status=code)
    if code == 403:
        return _err("forbidden", "API Key 无效或无权限（HTTP 403）", status=code)
    if code == 402:
        return _err("insufficient_balance", "账户余额不足（HTTP 402），请充值后再试", status=code)
    if code == 413:
        return _err("payload_too_large", "请求体过大（HTTP 413）", status=code)
    if code == 422:
        return _err("invalid_params", "参数非法（HTTP 422）: " + _short(raw, 160), status=code)
    if code == 429:
        return _err("rate_limited", "请求过于频繁（HTTP 429），请稍后重试", status=code)
    if code is not None and code >= 500:
        return _err("server_error", f"服务端错误（HTTP {code}），请稍后重试", status=code)
    return _err(
        "http_error",
        f"登录自检失败（HTTP {code}）: " + _short(raw, 200),
        status=code,
    )


def login(
    spec_input: Any = None,
    key: Any = "",
    timeout: float = PROBE_TIMEOUT,
) -> Tuple[bool, Any]:
    """镜像 .as ServerLogin + Probe（登录自检）。

    返回 ``(True, "200 ok")`` 或 ``(False, Err)``。
    关键规则：``probe=none`` / ``custom`` 不探测；探测遇到 **HTTP 404/405**
    视为该服务没有模型列表接口，**跳过校验放行**；模型名匹配忽略大小写，
    并允许 ``model -> model:tag`` 前缀匹配（见 CONTRACT.md D-25）。
    """
    try:
        if isinstance(spec_input, Spec):
            ok, spec = True, spec_input
        else:
            ok, spec = parse_spec(spec_input)
        if not ok:
            return False, spec
        key_text = "" if key is None else str(key).strip()
        if spec.auth != "none" and not key_text and spec.preset != "custom":
            return False, _err(
                "auth_needed", "请在密码框填写 API Key（本机服务可把 auth 设为 none）"
            )
        if not spec.model and spec.kind in (KIND_ANTHROPIC, KIND_GEMINI):
            return False, _err(
                "config_error", f"该服务必须指定模型名，例如 {spec.preset}:<model>"
            )
        if spec.probe == "none" or spec.preset == "custom":
            return True, "200 ok"

        ok, req = build_probe_request(spec, key_text, timeout=timeout)
        if not ok:
            return True, "200 ok"  # .as Probe(): url 为空则跳过
        ok, result = perform_raw(req)
        if not ok:
            if result.code == "network":
                return False, _err(
                    "network",
                    f"无法连接 {spec.base or spec.url}（检查地址、端口、网络或代理）",
                    detail=result.detail,
                )
            return False, result
        status, raw = result
        status_code = _status_code(status)
        if status_code in (404, 405):
            return True, "200 ok"
        if status_code is not None and not (200 <= status_code < 300):
            return False, _login_status_error(spec, status_code, raw)

        ok, names = parse_models_response(spec, status, raw)
        if not ok:
            return True, "200 ok"  # .as: JSON 解析失败 -> ParseModels 空 -> 放行
        if spec.model and names and not model_matched(names, spec.model):
            return False, _err(
                "model_not_found",
                f"未找到模型: {spec.model}；可用示例: {join_models(names, 6)}",
            )
        return True, "200 ok"
    except Exception as exc:  # pragma: no cover
        return False, _err("internal_error", f"登录自检时发生内部错误：{exc!r}")


# ---------------------------------------------------------------------------
# clean_text（镜像 .as CleanTranslation / StripKnownPrefixes）
# ---------------------------------------------------------------------------

#: .as StripKnownPrefixes 的前缀表（顺序敏感，最多 3 轮）
KNOWN_PREFIXES: Tuple[str, ...] = (
    "翻译：", "翻译:", "译文：", "译文:", "譯文：", "譯文:",
    "Translation:", "translation:", "Translated text:", "Translation :",
    "Answer:", "输出：", "输出:", "【译文】", "译文：",
)

_ORIGINAL_PREFIXES: Tuple[str, ...] = ("原文：", "原文:", "Original:")
_QUOTE_PAIRS = (
    ('"', '"'),
    ("“", "”"),
    ("「", "」"),
    ("『", "』"),
)


def strip_known_prefixes(raw: Any) -> str:
    """镜像 .as StripKnownPrefixes。"""
    text = "" if raw is None else str(raw)
    for _ in range(3):
        removed = False
        for prefix in KNOWN_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                removed = True
                break
        if not removed:
            break
    if text.startswith(_ORIGINAL_PREFIXES):
        newline = text.find("\n")
        if newline >= 0:
            text = text[newline + 1:].strip()
    return text


def clean_text(text: Any, dst_lang: str = "") -> str:
    """镜像 .as CleanTranslation（去围栏/前缀/包裹引号、换行规范化、RTL 前缀）。"""
    if text is None:
        return ""
    try:
        s = text if isinstance(text, str) else str(text)
        s = s.strip()

        if s.startswith("```"):
            newline = s.find("\n")
            if newline >= 0:
                s = s[newline + 1:]
        if len(s) >= 3 and s.endswith("```"):
            s = s[:-3]
        s = s.strip()

        s = strip_known_prefixes(s)
        s = s.strip()

        if len(s) >= 2:
            first, last = s[0], s[-1]
            for quote_open, quote_close in _QUOTE_PAIRS:
                if first == quote_open and last == quote_close:
                    s = s[1:-1].strip()
                    break

        s = s.replace("\r\n", "\n")
        s = s.replace("\r", "\n")
        s = s.replace("<br/>", "\n")
        s = s.replace("<br />", "\n")
        s = s.replace("<br>", "\n")
        s = s.replace("\n\n\n", "\n\n")

        if dst_lang and is_rtl(dst_lang):
            s = "\u202b" + s
        return s.strip()
    except Exception:  # pragma: no cover
        return ""


def is_rtl(lang: Any) -> bool:
    """判断目标语言是否 RTL（fa/ar/he/ur 等语言码或英文名，大小写不敏感）。"""
    try:
        value = ("" if lang is None else str(lang)).strip().lower()
        if not value:
            return False
        return value in _RTL_LANGS or value.split("-")[0] in _RTL_LANGS
    except Exception:  # pragma: no cover
        return False


# ---------------------------------------------------------------------------
# 高层封装（测试与人工对照用）
# ---------------------------------------------------------------------------


def perform_request(req: Any) -> Tuple[bool, Any]:
    """执行请求并解析响应，返回 ``(True, text)`` 或 ``(False, Err)``。"""
    ok, result = perform_raw(req)
    if not ok:
        return False, result
    status, raw = result
    return parse_response(req.spec, status, raw)


def fetch_models(
    spec: Any, key: Any = "", timeout: float = PROBE_TIMEOUT
) -> Tuple[bool, Any]:
    """执行模型列表探测，返回 ``(True, [names])`` 或 ``(False, Err)``。"""
    ok, req = build_probe_request(spec, key, timeout=timeout)
    if not ok:
        return False, req
    ok, result = perform_raw(req)
    if not ok:
        return False, result
    status, raw = result
    return parse_models_response(spec, status, raw)


def translate_with_spec(
    spec: Any,
    key: Any = "",
    text: Any = "",
    src: Any = "",
    dst: Any = "Chinese",
    timeout: float = SEND_TIMEOUT,
) -> Tuple[bool, Any]:
    """用已解析的 Spec 完成一次翻译（等价插件 Translate 一次调用）。"""
    try:
        if isinstance(spec, Err):
            return False, spec
        if not isinstance(spec, Spec):
            return False, _err("config_error", "内部错误：spec 不是有效配置")
        src_text = "" if src is None else str(src)
        dst_text = "" if dst is None else str(dst)
        raw_text = "" if text is None else str(text)
        prompt = build_prompt(raw_text, src_text, dst_text)
        ok, req = build_request(
            spec,
            key,
            prompt,
            text=raw_text,
            src=src_text,
            dst=dst_text,
            timeout=timeout,
        )
        if not ok:
            return False, req
        ok, result = perform_request(req)
        if not ok:
            return False, result
        output = result if isinstance(result, str) else str(result)
        if dst_text and is_rtl(dst_text) and not output.startswith("\u202b"):
            output = "\u202b" + output
        if not output:
            return False, _err("no_content", "响应中未找到译文内容")
        return True, output
    except Exception as exc:  # pragma: no cover
        return False, _err("internal_error", f"翻译时发生内部错误：{exc!r}")


def translate(
    user: Any = None,
    key: Any = "",
    text: Any = "",
    src: Any = "",
    dst: Any = "Chinese",
    timeout: float = SEND_TIMEOUT,
) -> Tuple[bool, Any]:
    """完整链路：User 字段 -> spec -> 请求 -> 响应 -> 清洗译文。"""
    ok, spec = parse_spec(user)
    if not ok:
        return False, spec
    return translate_with_spec(spec, key, text, src, dst, timeout=timeout)


__all__ = [
    "AUTH_MODES",
    "DEFAULT_ANTHROPIC_MAX_TOKENS",
    "DEFAULT_ANTHROPIC_VERSION",
    "DEFAULT_CUSTOM_PATH",
    "DEFAULT_PATHS",
    "DEFAULT_SPEC",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_TIMEOUT",
    "Err",
    "KIND_ANTHROPIC",
    "KIND_CUSTOM",
    "KIND_GEMINI",
    "KIND_OLLAMA",
    "KIND_OPENAI",
    "KNOWN_PREFIXES",
    "OPTS_KEYS",
    "PRESETS",
    "PRESET_ORDER",
    "PROBE_MODES",
    "PROBE_TIMEOUT",
    "Preset",
    "Request",
    "SEND_TIMEOUT",
    "Spec",
    "STATUS_MESSAGES",
    "build_body",
    "build_headers",
    "build_prompt",
    "build_probe_request",
    "build_request",
    "build_url",
    "clean_text",
    "default_path_for",
    "fetch_models",
    "host_url_encode",
    "is_rtl",
    "join_models",
    "json_escape",
    "json_quote",
    "login",
    "mask_key",
    "model_matched",
    "node_text",
    "parse_json_path",
    "parse_models_response",
    "parse_opts",
    "parse_response",
    "parse_spec",
    "perform_raw",
    "perform_request",
    "resolve_json_path",
    "resolve_provider",
    "safe_url",
    "split_path_tokens",
    "strip_known_prefixes",
    "translate",
    "translate_with_spec",
    "walk_path",
]
