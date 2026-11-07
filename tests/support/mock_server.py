#!/usr/bin/env python3
"""AnyTranslate 契约测试用 mock LLM 服务（仅标准库，单进程）。

独立启动
--------
::

    python tests/support/mock_server.py --port 18080

    # 随机端口（日志里会打印 listening on http://127.0.0.1:<port>）
    python tests/support/mock_server.py --port 0

行为切换
--------
1. 路径前缀：``/s/<scenario>/...``，例如
   ``POST http://127.0.0.1:18080/s/401/v1/chat/completions``；
2. 查询参数：``?__scenario=<scenario>``；
3. 命令行默认值：``--scenario 401``（对没有前缀的请求生效）。

场景（scenario）
----------------
``ok``（别名 success/200）、``401``、``403``、``404``、``405``、``429``、``500``、
``502``（HTML 错误页）、``badjson``（200 + 非 JSON 文本）、``array``（OpenAI
content 为数组）、``reasoning``（只有 reasoning_content）、``empty``（choices
为空）、``mixed``（思考片段 + 文本片段混合）、``slow``（sleep 后返回）。

路由（按路径识别，不要求前缀）
------------------------------
* ``POST .../chat/completions``            -> OpenAI 兼容
* ``POST .../v1/messages``                 -> Anthropic Messages
* ``POST .../v1beta/models/<m>:generateContent`` -> Gemini（Key 在 ``x-goog-api-key`` 头）
* ``POST .../api/chat``                    -> Ollama 原生
* ``POST <其它路径>``                       -> 自定义 JSON API（返回多形状样例）
* ``GET  .../models`` / ``/v1/models`` / ``/v1beta/models`` / ``/api/tags``
                                            -> 模型列表

记录与断言
----------
* ``GET  /__requests`` -> JSON 数组（按到达顺序），每条含 method/path/
  route_path/scenario/route/query/headers/raw_headers/body/body_json/
  problems 等字段；``problems`` 是按契约校验请求得到的问题列表（空 = 合规；
  认证允许协议默认请求头，或 ``auth=query`` 的 URL 参数 ``key``，见 .as AppendQueryAuth）。
* ``GET  /__last``     -> 最后一条记录（无则 null）。
* ``GET  /__health``   -> ``{"ok": true, "scenario": ..., "count": ...}``。
* ``POST|DELETE|GET /__reset`` -> 清空记录。
* ``POST /__echo``     -> 回显本次请求（不写入记录）。

注意：``/s/<name>/`` 与 ``/__*`` 是保留路径前缀，自定义 URL 不要以此开头。
"""

from __future__ import annotations

import argparse
import copy
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18080
DEFAULT_SCENARIO = "ok"
DEFAULT_SLOW_SECONDS = 1.5
DEFAULT_RECORD_LIMIT = 500

SCENARIO_ALIASES = {
    "success": "ok",
    "200": "ok",
    "normal": "ok",
    "unauthorized": "401",
    "auth": "401",
    "forbidden": "403",
    "notfound": "404",
    "not_found": "404",
    "methodnotallowed": "405",
    "method_not_allowed": "405",
    "ratelimit": "429",
    "rate_limit": "429",
    "servererror": "500",
    "server_error": "500",
    "badgateway": "502",
    "bad_gateway": "502",
    "json": "array",
    "fence": "ok",
    "models": "ok",
}

KNOWN_SCENARIOS = {
    "ok",
    "401",
    "403",
    "404",
    "405",
    "429",
    "500",
    "502",
    "badjson",
    "array",
    "reasoning",
    "empty",
    "mixed",
    "slow",
}

FAILURE_SCENARIOS = {"401", "403", "404", "405", "429", "500", "502"}

# 成功响应的固定译文（测试逐字断言；修改前先同步 test_contract.py）
OPENAI_TEXT = "这是 OpenAI 兼容译文。"
OPENAI_ARRAY_PARTS = ("数组第一段，", "数组第二段。")
OPENAI_REASONING = "思考过程：先分析语境，再组织译文。"
ANTHROPIC_PARTS = ("Anthropic 第一段，", "Anthropic 第二段。")
ANTHROPIC_THINKING = "Anthropic 思考片段。"
GEMINI_PARTS = ("Gemini 第一段，", "Gemini 第二段。")
GEMINI_THOUGHT = "Gemini 思考片段。"
OLLAMA_TEXT = "Ollama 原生译文。"
OLLAMA_THINKING = "Ollama 思考片段。"
CUSTOM_TEXTS = {
    "choices[0].message.content": "自定义-choices 译文",
    "result.translation": "自定义-result 译文",
    "data[0].text": "自定义-data 译文",
    "translation": "自定义-top 译文",
}

MODELS_PAYLOADS: Dict[str, Any] = {
    "models": {
        "object": "list",
        "data": [
            {"id": "mock-model-a", "object": "model"},
            {"id": "mock-model-b", "object": "model"},
        ],
    },
    "models_gemini": {
        "models": [
            {"name": "models/gemini-mock-1", "displayName": "Gemini Mock 1"},
            {"name": "models/gemini-mock-2", "displayName": "Gemini Mock 2"},
        ]
    },
    "models_ollama": {
        "models": [
            {"name": "qwen3:4b", "size": 1234567},
            {"name": "llama3.2:3b", "size": 7654321},
        ]
    },
}


# ---------------------------------------------------------------------------
# 响应体构造
# ---------------------------------------------------------------------------


def normalize_scenario(name: Any) -> str:
    value = ("" if name is None else str(name)).strip().lower()
    if not value:
        return DEFAULT_SCENARIO
    return SCENARIO_ALIASES.get(value, value)


def success_payload(route: str, scenario: str) -> Any:
    """构造 200 成功响应体；不同 route 的 JSON 形状按契约区分。"""
    if route == "openai":
        if scenario == "array":
            content: Any = [{"type": "text", "text": part} for part in OPENAI_ARRAY_PARTS]
        elif scenario == "mixed":
            content = [
                {"type": "text", "text": OPENAI_ARRAY_PARTS[0]},
                {"type": "thinking", "text": "不应被拼接的思考片段"},
                {"type": "text", "text": OPENAI_ARRAY_PARTS[1]},
            ]
        elif scenario == "reasoning":
            return {
                "id": "chatcmpl-mock-reasoning",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "reasoning_content": OPENAI_REASONING,
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
        elif scenario == "empty":
            return {"id": "chatcmpl-mock-empty", "object": "chat.completion", "choices": []}
        else:
            content = OPENAI_TEXT
        return {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": 0,
            "model": "mock-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
        }

    if route == "anthropic":
        parts: List[Dict[str, Any]] = []
        if scenario == "mixed":
            parts.append({"type": "thinking", "thinking": ANTHROPIC_THINKING})
            parts.extend({"type": "text", "text": part} for part in ANTHROPIC_PARTS)
        elif scenario == "empty":
            parts = []
        else:
            parts.extend({"type": "text", "text": part} for part in ANTHROPIC_PARTS)
        return {
            "id": "msg_mock",
            "type": "message",
            "role": "assistant",
            "model": "mock-model",
            "content": parts,
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 8},
        }

    if route == "gemini":
        parts = []
        if scenario == "mixed":
            parts.append({"text": GEMINI_THOUGHT, "thought": True})
            parts.extend({"text": part} for part in GEMINI_PARTS)
        elif scenario == "empty":
            parts = []
        else:
            parts.extend({"text": part} for part in GEMINI_PARTS)
        return {
            "candidates": [
                {
                    "content": {"role": "model", "parts": parts},
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 8},
        }

    if route == "ollama":
        return {
            "model": "mock-model",
            "created_at": "2026-01-01T00:00:00Z",
            "message": {
                "role": "assistant",
                "content": OLLAMA_TEXT,
                "thinking": OLLAMA_THINKING if scenario == "mixed" else "",
            },
            "done": True,
            "done_reason": "stop",
        }

    # 自定义 JSON API：同一份响应同时提供多种常见形状，供不同 path 断言
    return {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": CUSTOM_TEXTS["choices[0].message.content"],
                },
                "finish_reason": "stop",
            }
        ],
        "result": {"translation": CUSTOM_TEXTS["result.translation"]},
        "data": [{"text": CUSTOM_TEXTS["data[0].text"]}],
        "translation": CUSTOM_TEXTS["translation"],
    }


def failure_payload(scenario: str) -> Dict[str, Any]:
    if scenario == "401":
        return {
            "error": {
                "message": "Incorrect API key provided: sk-***. You can find your API key at ...",
                "type": "invalid_request_error",
                "code": "invalid_api_key",
            }
        }
    if scenario == "403":
        return {
            "error": {
                "message": "You do not have permission to access this resource",
                "type": "permission_error",
                "code": "permission_denied",
            }
        }
    if scenario == "404":
        return {
            "error": {
                "message": "The model `mock-model` does not exist or you do not have access to it",
                "type": "invalid_request_error",
                "code": "model_not_found",
            }
        }
    if scenario == "405":
        return {
            "error": {
                "message": "Method Not Allowed: this service does not implement a models endpoint",
                "type": "invalid_request_error",
                "code": "method_not_allowed",
            }
        }
    if scenario == "429":
        return {
            "error": {
                "message": "Rate limit reached for requests. Please try again later.",
                "type": "rate_limit_error",
                "code": "rate_limit_exceeded",
            }
        }
    if scenario == "500":
        return {
            "error": {
                "message": "The server had an error while processing your request",
                "type": "server_error",
                "code": None,
            }
        }
    return {
        "error": {
            "message": "mock: unknown error scenario",
            "type": "mock_error",
            "code": "unknown_scenario",
        }
    }


FAILURE_STATUS = {
    "401": 401,
    "403": 403,
    "404": 404,
    "405": 405,
    "429": 429,
    "500": 500,
    "502": 502,
}


# ---------------------------------------------------------------------------
# 契约校验（把问题记录到 problems，测试断言其为空）
# ---------------------------------------------------------------------------


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _has_query_key(query: Dict[str, str]) -> bool:
    """auth=query 模式下 Key 以 ?key=... 形式出现（参数名默认 key）。"""
    return bool((query.get("key") or "").strip())


def validate_request(
    route: str, headers: Dict[str, str], query: Dict[str, str], body: Any
) -> List[str]:
    """按 docs/testing/contract.md 的请求契约校验；返回问题列表（空 = 合规）。

    认证允许两种形式：协议默认请求头，或 ``auth=query`` 的 URL 参数 ``key``
    （见 .as AppendQueryAuth；探测与翻译共用）。
    """
    problems: List[str] = []
    query_auth = _has_query_key(query)
    content_type = (headers.get("content-type") or "").lower()
    if "application/json" not in content_type:
        problems.append(f"Content-Type 应为 application/json，实际为 {headers.get('content-type')!r}")

    if route in ("openai", "anthropic", "gemini", "ollama", "custom"):
        if body is None:
            problems.append("请求体不是合法 JSON")
            return problems
        if not isinstance(body, dict):
            problems.append("请求体 JSON 根节点应为对象")
            return problems

    if route == "openai":
        if not isinstance(body.get("model"), str) or not body["model"].strip():
            problems.append("body.model 应为非空字符串")
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            problems.append("body.messages 应为非空数组")
        else:
            first = messages[0]
            if not isinstance(first, dict) or first.get("role") != "user":
                problems.append("messages[0].role 应为 user")
            if not isinstance(first, dict) or not isinstance(first.get("content"), str):
                problems.append("messages[0].content 应为字符串")
        if body.get("stream") is not False:
            problems.append("body.stream 应为 false")
        if not _is_number(body.get("temperature")):
            problems.append("body.temperature 应为数字")
        auth = headers.get("authorization") or ""
        if not (auth.startswith("Bearer ") and len(auth) > len("Bearer ")) and not query_auth:
            problems.append("缺少 Authorization: Bearer <key> 或 URL 查询参数 key")

    elif route == "anthropic":
        if not query_auth:
            if not (headers.get("x-api-key") or "").strip():
                problems.append("缺少 x-api-key 请求头（或使用 auth=query 的 URL key 参数）")
            if (headers.get("anthropic-version") or "") != "2023-06-01":
                problems.append("anthropic-version 应为 2023-06-01")
        if not isinstance(body.get("model"), str) or not body["model"].strip():
            problems.append("body.model 应为非空字符串")
        max_tokens = body.get("max_tokens")
        if not (isinstance(max_tokens, int) and max_tokens > 0):
            problems.append("body.max_tokens 应为正整数")
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            problems.append("body.messages 应为非空数组")
        else:
            first = messages[0]
            if not isinstance(first, dict) or first.get("role") != "user":
                problems.append("messages[0].role 应为 user")
            if not isinstance(first, dict) or not isinstance(first.get("content"), str):
                problems.append("messages[0].content 应为字符串")

    elif route == "gemini":
        # 契约：默认 Key 走 x-goog-api-key 头；auth=query 时走 URL 参数 key
        if not (headers.get("x-goog-api-key") or "").strip() and not query_auth:
            problems.append("缺少 x-goog-api-key 请求头（或使用 auth=query 的 URL key 参数）")
        contents = body.get("contents")
        if not isinstance(contents, list) or not contents:
            problems.append("body.contents 应为非空数组")
        else:
            first = contents[0]
            parts = first.get("parts") if isinstance(first, dict) else None
            if not isinstance(parts, list) or not parts:
                problems.append("contents[0].parts 应为非空数组")
            elif not isinstance(parts[0], dict) or not isinstance(parts[0].get("text"), str):
                problems.append("contents[0].parts[0].text 应为字符串")
        generation = body.get("generationConfig")
        if not isinstance(generation, dict) or not _is_number(generation.get("temperature")):
            problems.append("body.generationConfig.temperature 应为数字")

    elif route == "ollama":
        if not isinstance(body.get("model"), str) or not body["model"].strip():
            problems.append("body.model 应为非空字符串")
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            problems.append("body.messages 应为非空数组")
        else:
            first = messages[0]
            if not isinstance(first, dict) or first.get("role") != "user":
                problems.append("messages[0].role 应为 user")
            if not isinstance(first, dict) or not isinstance(first.get("content"), str):
                problems.append("messages[0].content 应为字符串")
        if body.get("stream") is not False:
            problems.append("body.stream 应为 false")
        options = body.get("options")
        if not isinstance(options, dict) or not _is_number(options.get("temperature")):
            problems.append("body.options.temperature 应为数字")
        if body.get("think") is not False:
            problems.append("body.think 应为 false（字幕翻译不需要思考过程）")

    return problems


# ---------------------------------------------------------------------------
# 路由识别
# ---------------------------------------------------------------------------


def classify_route(method: str, path: str) -> str:
    """请求路径 -> 路由类型；未知 GET 返回 unknown_get。"""
    if ":generateContent" in path:
        return "gemini"
    if method.upper() == "GET":
        clean = path.rstrip("/")
        if clean.endswith("/api/tags"):
            return "models_ollama"
        if clean.endswith("/v1beta/models"):
            return "models_gemini"
        if clean.endswith("/models"):
            return "models"
        return "unknown_get"
    if path.endswith("/chat/completions"):
        return "openai"
    if path.endswith("/messages"):
        return "anthropic"
    if path.endswith("/api/chat"):
        return "ollama"
    return "custom"


def split_scenario(path: str) -> tuple:
    """剥离 ``/s/<scenario>`` 前缀，返回 (scenario_or_empty, route_path)。"""
    parts = path.split("/")
    # path 以 "/" 开头，parts[0] == ""
    if len(parts) >= 3 and parts[1] == "s" and parts[2]:
        rest = "/" + "/".join(parts[3:]) if len(parts) > 3 else "/"
        return parts[2].lower(), rest
    return "", path


# ---------------------------------------------------------------------------
# 记录状态
# ---------------------------------------------------------------------------


class MockState:
    """线程安全的请求记录容器。"""

    def __init__(
        self,
        scenario: str = DEFAULT_SCENARIO,
        record_limit: int = DEFAULT_RECORD_LIMIT,
        slow_seconds: float = DEFAULT_SLOW_SECONDS,
        verbose: bool = False,
    ) -> None:
        self.scenario = normalize_scenario(scenario)
        self.record_limit = max(1, int(record_limit))
        self.slow_seconds = float(slow_seconds)
        self.verbose = bool(verbose)
        self._lock = threading.Lock()
        self._records: List[Dict[str, Any]] = []
        self._next_id = 1

    def add(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            entry["id"] = self._next_id
            self._next_id += 1
            entry["received_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            self._records.append(entry)
            if len(self._records) > self.record_limit:
                del self._records[: len(self._records) - self.record_limit]
            return copy.deepcopy(entry)

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._records)

    def last(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._records[-1]) if self._records else None

    def reset(self) -> int:
        with self._lock:
            count = len(self._records)
            self._records.clear()
            return count

    def count(self) -> int:
        with self._lock:
            return len(self._records)


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AnyTranslateMock/1.0"
    sys_version = ""

    # -- 基础设施 ---------------------------------------------------------

    @property
    def state(self) -> MockState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        if self.state.verbose:
            print("[mock] " + (format % args), flush=True)

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle("DELETE")

    def do_PUT(self) -> None:  # noqa: N802
        self._handle("PUT")

    # -- 响应工具 ---------------------------------------------------------

    def _send_bytes(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # 客户端超时/主动断开（例如 slow 场景）时静默
            pass

    def _send_json(self, status: int, obj: Any) -> None:
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, payload, "application/json; charset=utf-8")

    def _send_text(self, status: int, text: str, content_type: str) -> None:
        self._send_bytes(status, text.encode("utf-8"), content_type)

    def _read_body(self, method: str) -> bytes:
        if method.upper() in ("GET", "HEAD", "DELETE"):
            length_header = self.headers.get("Content-Length")
            length = int(length_header) if length_header and length_header.isdigit() else 0
        else:
            length_header = self.headers.get("Content-Length")
            length = int(length_header) if length_header and length_header.isdigit() else 0
        if length <= 0:
            return b""
        try:
            return self.rfile.read(length)
        except Exception:  # pragma: no cover
            return b""

    # -- 主流程 -----------------------------------------------------------

    def _handle(self, method: str) -> None:
        raw_target = self.path or "/"
        raw_path, _, raw_query = raw_target.partition("?")
        if raw_path.startswith("/__"):
            self._handle_meta(method, raw_path, raw_query)
            return

        query = dict(urllib.parse.parse_qsl(raw_query, keep_blank_values=True))
        prefix_scenario, route_path = split_scenario(raw_path)
        scenario = normalize_scenario(
            query.get("__scenario") or prefix_scenario or self.state.scenario
        )
        route = classify_route(method, route_path)

        body_bytes = self._read_body(method)
        body_text = body_bytes.decode("utf-8", "replace")
        body_json: Any = None
        if body_text.strip():
            try:
                body_json = json.loads(body_text)
            except Exception:
                body_json = None
        headers = {key.lower(): value for key, value in self.headers.items()}
        raw_headers = [[key, value] for key, value in self.headers.items()]

        problems = (
            validate_request(route, headers, query, body_json)
            if method.upper() in ("POST", "PUT", "PATCH")
            else []
        )
        entry = {
            "method": method.upper(),
            "path": raw_path,
            "route_path": route_path,
            "scenario": scenario,
            "route": route,
            "query": query,
            "headers": headers,
            "raw_headers": raw_headers,
            "body": body_text,
            "body_json": body_json,
            "body_ok": (not body_text.strip()) or body_json is not None,
            "content_length": len(body_bytes),
            "client": "%s:%s" % self.client_address[:2],
            "problems": problems,
        }
        self.state.add(entry)
        if self.state.verbose:
            print(
                "[mock] %s %s route=%s scenario=%s problems=%d"
                % (method, raw_path, route, scenario, len(problems)),
                flush=True,
            )

        if scenario not in KNOWN_SCENARIOS:
            self._send_json(
                400,
                {
                    "error": {
                        "message": f"mock: 未知场景 {scenario!r}（可用：{', '.join(sorted(KNOWN_SCENARIOS))}）",
                        "type": "mock_error",
                        "code": "unknown_scenario",
                    }
                },
            )
            return

        if scenario == "slow":
            time.sleep(self.state.slow_seconds)

        if scenario in FAILURE_SCENARIOS:
            status = FAILURE_STATUS[scenario]
            if scenario == "502":
                self._send_text(
                    status,
                    "<html><head><title>502 Bad Gateway</title></head>"
                    "<body><h1>502 Bad Gateway</h1></body></html>",
                    "text/html; charset=utf-8",
                )
                return
            self._send_json(status, failure_payload(scenario))
            return

        if scenario == "badjson":
            self._send_text(
                200,
                "this is not json <<< mock server intentionally returns plain text",
                "text/plain; charset=utf-8",
            )
            return

        if route.startswith("models"):
            self._send_json(200, MODELS_PAYLOADS.get(route, MODELS_PAYLOADS["models"]))
            return

        if route == "unknown_get":
            self._send_json(
                404,
                {
                    "error": {
                        "message": f"mock: 未识别的 GET 路径 {route_path!r}",
                        "type": "mock_error",
                        "code": "not_found",
                    }
                },
            )
            return

        self._send_json(200, success_payload(route, scenario))

    # -- /__* 元接口 -------------------------------------------------------

    def _handle_meta(self, method: str, path: str, raw_query: str) -> None:
        clean = path.rstrip("/") or "/"
        method = method.upper()
        if clean == "/__health" and method == "GET":
            self._send_json(
                200,
                {
                    "ok": True,
                    "scenario": self.state.scenario,
                    "count": self.state.count(),
                    "routes": [
                        "POST /chat/completions",
                        "POST /v1/messages",
                        "POST /v1beta/models/<model>:generateContent",
                        "POST /api/chat",
                        "POST <custom-path>",
                        "GET /models | /v1/models | /v1beta/models | /api/tags",
                        "GET /__requests | /__last | /__health",
                        "POST/DELETE/GET /__reset",
                    ],
                },
            )
            return
        if clean == "/__requests" and method == "GET":
            self._send_json(200, self.state.snapshot())
            return
        if clean == "/__last" and method == "GET":
            last = self.state.last()
            self._send_json(200, last if last is not None else None)
            return
        if clean == "/__reset" and method in ("POST", "DELETE", "GET"):
            cleared = self.state.reset()
            self._send_json(200, {"ok": True, "cleared": cleared})
            return
        if clean == "/__echo" and method in ("POST", "PUT", "PATCH"):
            body_bytes = self._read_body(method)
            body_text = body_bytes.decode("utf-8", "replace")
            try:
                body_json: Any = json.loads(body_text) if body_text.strip() else None
            except Exception:
                body_json = None
            self._send_json(
                200,
                {
                    "method": method,
                    "path": path,
                    "query": dict(urllib.parse.parse_qsl(raw_query, keep_blank_values=True)),
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body_text,
                    "body_json": body_json,
                },
            )
            return
        self._send_json(
            404,
            {
                "error": {
                    "message": f"mock: 未知元接口 {method} {path}",
                    "type": "mock_error",
                    "code": "not_found",
                }
            },
        )


class MockHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer + 共享记录状态；关闭时不打印客户端断连堆栈。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple, state: MockState, handler: type = MockHandler) -> None:
        self.state = state
        super().__init__(address, handler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        if getattr(self, "state", None) is not None and self.state.verbose:
            super().handle_error(request, client_address)


class MockServer:
    """在后台线程中运行 mock 服务；测试与脚本共用。"""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = 0,
        scenario: str = DEFAULT_SCENARIO,
        record_limit: int = DEFAULT_RECORD_LIMIT,
        slow_seconds: float = DEFAULT_SLOW_SECONDS,
        verbose: bool = False,
    ) -> None:
        self.state = MockState(
            scenario=scenario,
            record_limit=record_limit,
            slow_seconds=slow_seconds,
            verbose=verbose,
        )
        self.httpd = MockHTTPServer((host, int(port)), self.state)
        self._thread: Optional[threading.Thread] = None

    # -- 生命周期 ---------------------------------------------------------

    def start(self) -> "MockServer":
        if self._thread is not None:
            return self
        self._thread = threading.Thread(
            target=self.httpd.serve_forever,
            kwargs={"poll_interval": 0.02},
            name="anytranslate-mock",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._thread is None:
            return
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=3.0)
        self._thread = None

    def __enter__(self) -> "MockServer":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()

    # -- 属性 -------------------------------------------------------------

    @property
    def host(self) -> str:
        return str(self.httpd.server_address[0])

    @property
    def port(self) -> int:
        return int(self.httpd.server_address[1])

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def reset(self) -> int:
        return self.state.reset()

    def requests(self) -> List[Dict[str, Any]]:
        return self.state.snapshot()

    def last_request(self) -> Optional[Dict[str, Any]]:
        return self.state.last()


# ---------------------------------------------------------------------------
# 独立启动
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="AnyTranslate 契约测试 mock LLM 服务（仅标准库）"
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="监听地址（默认 127.0.0.1）")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="监听端口（默认 18080；0 = 随机）"
    )
    parser.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO,
        help="无 /s/<scenario>/ 前缀时的默认场景（默认 ok）",
    )
    parser.add_argument("--slow-seconds", type=float, default=DEFAULT_SLOW_SECONDS)
    parser.add_argument("--record-limit", type=int, default=DEFAULT_RECORD_LIMIT)
    parser.add_argument("--verbose", action="store_true", help="打印每条请求日志")
    args = parser.parse_args(argv)

    state = MockState(
        scenario=args.scenario,
        record_limit=args.record_limit,
        slow_seconds=args.slow_seconds,
        verbose=args.verbose,
    )
    httpd = MockHTTPServer((args.host, args.port), state)
    host, port = httpd.server_address[0], httpd.server_address[1]
    base = f"http://{host}:{port}"
    print(f"AnyTranslate mock server listening on {base}", flush=True)
    print(
        "  endpoints: POST /chat/completions | /v1/messages | "
        "/v1beta/models/<m>:generateContent | /api/chat | <custom>",
        flush=True,
    )
    print(
        "  scenario 切换: 路径前缀 /s/<scenario>/... 或 ?__scenario=<name>"
        f"（默认 {normalize_scenario(args.scenario)}）",
        flush=True,
    )
    print("  tests: GET /__requests  GET /__last  GET /__health  POST /__reset", flush=True)
    print("  Ctrl+C 停止", flush=True)
    try:
        httpd.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        print("mock server stopped", flush=True)
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
