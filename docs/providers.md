# 多服务 LLM / 翻译 API 契约手册

> 配套 `docs/design.md` 的适配器实现契约。面向 PotPlayer AngelScript 插件（同步 `HostOpenHTTP` + jsoncpp，无流式）。
> 核对日期：2026-11-07。全部示例 `stream:false`；`model` 名仅为示例，运行期以各服务 `/models` 或控制台为准；标「待验证」的条目未在官方文档直接确认。

## 0. 通用约定

- 请求：`POST`，`Content-Type: application/json`，UTF-8；**不要开流式**（插件一次只要最终文本）。
- 鉴权：OpenAI 兼容族 `Authorization: Bearer <key>`；Anthropic `x-api-key`（2026 文档推荐 `Authorization: Bearer`，旧头仍兼容）；Gemini `?key=` 或 `x-goog-api-key`；Ollama 无鉴权。
- 超时 10 s；`429`/`5xx` 退避重试 ≤ 2 次；`400` 不重试，改用最小请求体降级。
- 译文提取 = 一个 JSON path（§8）；错误提取 = 优先 `error.message`，退化到 `message` / `code` / 原始 body。

## 1. OpenAI Chat Completions 兼容族

统一端点：`POST {url}`（下表给出各服务完整 URL；`base_url` 已含 `/v1` 的不要重复拼）。官方文档：[Chat Completions](https://platform.openai.com/docs/api-reference/chat/create)。

### 1.1 请求（curl + 完整 JSON）

```bash
curl -sS https://api.openai.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -d '{
    "model": "gpt-5.6-terra",
    "messages": [
      {"role": "system", "content": "你是字幕翻译器。只输出译文，不要解释、不要加引号。"},
      {"role": "user", "content": "把下面英文字幕翻译成简体中文：\nHello, world."}
    ],
    "max_completion_tokens": 256,
    "stream": false
  }'
```

### 1.2 成功响应（非流式）

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1793942400,
  "model": "gpt-5.6-terra",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "你好，世界。", "refusal": null},
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 48,
    "completion_tokens": 8,
    "total_tokens": 56,
    "completion_tokens_details": {"reasoning_tokens": 0}
  }
}
```

取译文：`choices[0].message.content`。`finish_reason`：`stop` 正常；`length` 被截断；`content_filter` 被过滤；`tool_calls` 非预期。

### 1.3 各服务差异表

| 服务 | 完整请求 URL（POST） | 示例 model | 2026 要点 |
| --- | --- | --- | --- |
| OpenAI | `https://api.openai.com/v1/chat/completions` | `gpt-5.6-terra` | 推理模型用 `max_completion_tokens`；`temperature` 支持因模型而异 |
| DeepSeek | `https://api.deepseek.com/chat/completions`（`/v1` 亦可） | `deepseek-v4-flash` | **thinking 默认开启**，翻译必须显式关；错误码含 402/422 |
| Moonshot Kimi | 国内 `https://api.moonshot.cn/v1/chat/completions`；国际 `https://api.moonshot.ai/v1/chat/completions` | `kimi-k3.1-pro` | 响应含 `reasoning_content`；两种域名 key 不通用 |
| 智谱 GLM | 国内 `https://open.bigmodel.cn/api/paas/v4/chat/completions`；国际 `https://api.z.ai/api/paas/v4/chat/completions` | `glm-5.3` | **路径无 `/v1`**；`temperature` 上限 1（待验证）；`thinking` 可选 |
| 阿里云 DashScope | `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions`（旧 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`） | `qwen-flash` | 2026 官方建议迁移 workspace 专属域名；`enable_thinking` 为非标准参数 |
| 硅基流动 SiliconFlow | `https://api.siliconflow.cn/v1/chat/completions`（国际 `https://api.siliconflow.com/v1/chat/completions`） | `deepseek-ai/DeepSeek-V4-Flash` | 非标准参数 `enable_thinking` / `thinking_budget`；`max_tokens` 不含思维链 |
| OpenRouter | `https://openrouter.ai/api/v1/chat/completions` | `openai/gpt-5.6-terra` | `model` 为 `厂商/模型`；`HTTP-Referer`/`X-Title` 可选 |
| Groq | `https://api.groq.com/openai/v1/chat/completions` | `openai/gpt-oss-120b` | `n` 只能为 1（否则 400）；`max_tokens` 已弃用 |
| xAI | `https://api.x.ai/v1/chat/completions` | `grok-4.20` | 采样参数超出模型上限会被截到上限，不报错 |
| Mistral | `https://api.mistral.ai/v1/chat/completions` | `mistral-small-latest` | 仍用 `max_tokens`；`response_format` 支持 `json_object` |
| Together | `https://api.together.ai/v1/chat/completions`（旧 `api.together.xyz`） | `Qwen/Qwen3.5-9B` | 2026 官方 server 为 `api.together.ai` |
| LM Studio | `http://localhost:1234/v1/chat/completions` | `/v1/models` 返回的 id | 无鉴权；`model` 必填且必须匹配已加载模型 |
| vLLM | `http://localhost:8000/v1/chat/completions` | 启动参数 `--served-model-name` | `model` 必须是 served name；推理解析需启动 `--reasoning-parser` |
| one-api / new-api | `http://host:3000/v1/chat/completions` | 渠道映射后的名字 | 模型映射开启时会重构请求体，未识别字段可能丢失 |

### 1.4 会导致 400 的参数差异（重点）

- **OpenAI 推理模型**：`max_tokens` 与 o 系列不兼容，返回 400 `Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.`；`reasoning_effort:"none"` 在 GPT-6 Astra / GPT-6.1 Sol 上返回 400；GPT-6 Astra / GPT-6.1 Sol 的 Chat Completions 不支持 function calling。
- **DeepSeek**：不传 `thinking` 时默认开启思考（`reasoning_effort` 未传也一样）；低延迟翻译必须传 `"thinking": {"type": "disabled"}`。`max_tokens` 非思考默认 8K、思考默认 64K。
- **Kimi / GLM / SiliconFlow**：思考模式可能返回 `reasoning_content` 并让 `content` 为空；`temperature` 在思考模式下可能被忽略或拒绝（待验证，建议翻译时关思考）。
- **Groq**：`n != 1` 直接 400；`frequency_penalty` / `presence_penalty` / `logprobs` 官方标注未支持（忽略，不报错）。
- **GLM**：路径是 `/api/paas/v4/chat/completions`，按 OpenAI 习惯拼 `/v1/chat/completions` 会 404；`temperature` 范围上限 1。
- **DashScope**：`enable_thinking` 是顶层非标准参数；QwQ 系列 system message 无效；旧域名仍可用但官方建议迁移。
- **vLLM**：`model` 不存在返回 404；`top_k`、`repetition_penalty` 等是非标准扩展参数。
- **one-api / new-api**：开启模型映射后请求体被重新构造，`max_completion_tokens` 等新字段可能丢失（官方 README 已说明）。
- **Mistral / Together / LM Studio**：把上限写成 `max_completion_tokens` 可能被忽略（不截断），官方文档字段是 `max_tokens`；统一发 `max_tokens` 更稳。

### 1.5 `reasoning_content` 与空 `content`

- 返回 `reasoning_content` 的服务：DeepSeek（思考模式）、Kimi、GLM、SiliconFlow、vLLM（启用 reasoning parser）。OpenAI 自身不返回思考内容。
- OpenRouter 把思考放在 `choices[0].message.reasoning`（`reasoning_content` 作为别名同样接受），另有 `reasoning_details` 数组。
- 若 `content` 为空字符串而 `reasoning_content` 非空、`finish_reason=="length"`，说明 token 预算被思考耗尽：**增大 `max_tokens` 或关闭思考**，不要当译文使用。

### 1.6 登录自检：`GET {base_url}/models`

```bash
curl -sS https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"
```

```json
{
  "object": "list",
  "data": [
    {"id": "gpt-5.6-terra", "object": "model", "created": 1780000000, "owned_by": "openai", "shutdown_date": null},
    {"id": "gpt-5.6-luna", "object": "model", "created": 1780000000, "owned_by": "openai", "shutdown_date": "2026-10-23"}
  ]
}
```

校验规则：HTTP 200 + `data[].id` 包含配置的 model（忽略大小写）。部分服务（LM Studio、vLLM、one-api）忽略鉴权或返回精简结构，只要 `data` 数组存在即可判 Key 有效。

## 2. Anthropic Messages API（[文档](https://docs.anthropic.com/en/api/messages)）

### 2.1 请求

```bash
curl -sS https://api.anthropic.com/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2026-10-21" \
  -d '{
    "model": "claude-sonnet-4-6",
    "max_tokens": 256,
    "system": "你是字幕翻译器。只输出译文，不要解释。",
    "messages": [
      {"role": "user", "content": "把下面英文字幕翻译成简体中文：\nHello, world."}
    ]
  }'
```

- `anthropic-version` **必填**；`max_tokens` **必填**（漏了即 400）；`system` 是顶层字段，不要塞进 `messages`。
- 鉴权：`x-api-key` 仍可用；2026 文档把 `Authorization: Bearer <key>` 列为首选，二者择一即可。
- `temperature` 范围 0–1；启用 extended thinking 的模型可能拒绝自定义 `temperature`（待验证）；部分新模型不支持 assistant prefill，末尾为 assistant 消息会 400。

### 2.2 成功响应

```json
{
  "id": "msg_01ABCdef",
  "type": "message",
  "role": "assistant",
  "model": "claude-sonnet-4-6",
  "content": [{"type": "text", "text": "你好，世界。"}],
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {"input_tokens": 40, "output_tokens": 8}
}
```

- 取译文：`content` 数组里所有 `type=="text"` 的 `text` 拼接；`type=="thinking"` / `"redacted_thinking"` 跳过。
- `stop_reason`：`end_turn` 正常；`max_tokens` 截断；`refusal` 拒答；`tool_use` 非预期。
- 数组型 `content` 是常态，插件必须按块过滤，不能 `content[0].text` 硬取。

### 2.3 错误与模型列表

```json
{"type": "error", "error": {"type": "invalid_request_error", "message": "max_tokens: Field required"}, "request_id": "req_011CSHoEeqs5C35K2UUqR7Fy"}
```

```bash
curl -sS https://api.anthropic.com/v1/models?limit=20 \
  -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2026-10-21"
```

```json
{
  "data": [
    {"type": "model", "id": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6", "created_at": "2025-11-01T00:00:00Z", "lifecycle": "active"}
  ],
  "has_more": false,
  "first_id": "claude-sonnet-4-6",
  "last_id": "claude-sonnet-4-6"
}
```

错误类型：400 `invalid_request_error`、401 `authentication_error`、402 `billing_error`、403 `permission_error`、404 `not_found_error`、413 `request_too_large`、429 `rate_limit_error`、500 `api_error`、504 `timeout_error`、529 `overloaded_error`。

## 3. Google Gemini generateContent（[文档](https://ai.google.dev/api/generate-content)）

### 3.1 请求（key 在 query）

```bash
curl -sS "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key=$GEMINI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "systemInstruction": {"parts": [{"text": "你是字幕翻译器。只输出译文，不要解释。"}]},
    "contents": [
      {"role": "user", "parts": [{"text": "把下面英文字幕翻译成简体中文：\nHello, world."}]}
    ],
    "generationConfig": {
      "temperature": 0.2,
      "maxOutputTokens": 256,
      "thinkingConfig": {"thinkingBudget": 0}
    }
  }'
```

- URL 形态：`POST https://generativelanguage.googleapis.com/{v1beta|v1}/models/{model}:generateContent?key=<key>`；也支持 `x-goog-api-key: <key>` 头。query key 会进日志/代理，能用头就用头。
- snake_case 与 camelCase 字段名在线上等价；未知字段直接 400 `INVALID_ARGUMENT`。
- `contents` / `parts` 必填；`role` 只能是 `user` / `model`；最后一条必须是 user。
- `thinkingConfig.thinkingBudget: 0` 用于关闭思考（是否对所有模型有效待验证）；不设时思考模型可能先输出 `thought` 块。

### 3.2 成功响应

```json
{
  "candidates": [
    {
      "content": {"parts": [{"text": "你好，世界。"}], "role": "model"},
      "finishReason": "STOP",
      "index": 0
    }
  ],
  "usageMetadata": {"promptTokenCount": 32, "candidatesTokenCount": 8, "totalTokenCount": 40},
  "modelVersion": "gemini-3.5-flash"
}
```

- 取译文：`candidates[0].content.parts` 中过滤掉 `thought == true` 的块，其余 `text` 拼接。
- `finishReason`：`STOP` 正常；`MAX_TOKENS` 截断；`SAFETY` / `RECITATION` 内容被拦；`OTHER` 未知。
- `candidates` 为空时看 `promptFeedback.blockReason`（如 `SAFETY`），此时没有任何译文。

### 3.3 错误与模型列表

```json
{"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT", "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]}}
```

```bash
curl -sS "https://generativelanguage.googleapis.com/v1beta/models?key=$GEMINI_API_KEY"
```

```json
{
  "models": [
    {
      "name": "models/gemini-3.5-flash",
      "displayName": "Gemini 3.5 Flash",
      "description": "Fast model",
      "inputTokenLimit": 1048576,
      "outputTokenLimit": 65536,
      "supportedGenerationMethods": ["generateContent", "countTokens"]
    }
  ]
}
```

模型名要带 `models/` 前缀返回，调用 URL 里写 `models/{id}`；登录校验时去掉前缀再与配置比较。

## 4. Ollama 原生 API（[文档](https://docs.ollama.com/api/chat)）

### 4.1 `/api/chat` 请求

```bash
curl -sS http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma4",
    "messages": [
      {"role": "system", "content": "你是字幕翻译器。只输出译文，不要解释。"},
      {"role": "user", "content": "把下面英文字幕翻译成简体中文：\nHello, world."}
    ],
    "stream": false,
    "think": false,
    "options": {"temperature": 0.2, "num_predict": 256}
  }'
```

- **默认流式**，插件必须显式 `"stream": false`，否则拿到 NDJSON 多行。
- `think`：布尔或 `low`/`medium`/`high`/`max`；开启后思考内容在 `message.thinking`（具体版本字段待验证），`content` 才是最终答案。
- 采样参数放 `options`：`temperature`、`num_predict`（最大输出 token）、`top_p`、`num_ctx`；没有 OpenAI 的 `max_tokens`。

### 4.2 成功响应

```json
{
  "model": "gemma4",
  "created_at": "2026-11-07T06:00:00.000000Z",
  "message": {"role": "assistant", "content": "你好，世界。"},
  "done": true,
  "done_reason": "stop",
  "total_duration": 174560334,
  "load_duration": 101397084,
  "prompt_eval_count": 11,
  "prompt_eval_duration": 13074791,
  "eval_count": 18,
  "eval_duration": 52479709
}
```

`done_reason`：`stop` 正常、`length` 达到 `num_predict` 截断、`load` 仅加载。所有时长为纳秒。

### 4.3 `/api/tags` 与错误

```bash
curl -sS http://localhost:11434/api/tags
```

```json
{
  "models": [
    {"name": "gemma4", "model": "gemma4", "modified_at": "2025-10-03T23:34:03.409490317-07:00", "size": 9608350245, "digest": "c6eb396d...", "details": {"format": "gguf", "family": "gemma4", "parameter_size": "8.0B", "quantization_level": "Q4_K_M"}}
  ]
}
```

错误体是单字段对象，HTTP 404/400：`{"error": "model 'foo' not found"}`。Ollama 同时提供 OpenAI 兼容端点 `http://localhost:11434/v1/chat/completions`（支持 `/v1/models`），但原生 `/api/chat` 对 `think`/`options` 支持更完整。

## 5. 通用「自定义 JSON API」

design.md 的 `custom|<base_url>|<model>|[opts]` 用 body 模板 + 响应路径覆盖任意 REST 翻译接口（参考 [DeepL](https://developers.deepl.com/docs/api-reference/translate)、[Google v2](https://cloud.google.com/translate/docs/reference/rest/v2/translate)、[LibreTranslate](https://libretranslate.com/docs/)）。

- 请求体模板：`body={"q":"{{text}}","source":"{{src}}","target":"{{dst}}","format":"text"}`（`{{prompt}}` 为完整提示词，`{{model}}` 为模型名）。
- 占位符替换前先做 JSON 转义（`\`、`"`、换行、控制字符），否则含引号的字幕会破坏 JSON。
- 路径语法：点号 + 单层下标，如 `translatedText`、`data.translations[0].translatedText`；终值为数组时逐项取 `text`/`content` 拼接。
- `auth`：`bearer`（`Authorization: Bearer <key>`）、`x-api-key`、`query`（拼 `?<keyname>=<key>`）、`none`。

常见第三方示例：

| 服务 | 请求 | 取译文路径 |
| --- | --- | --- |
| LibreTranslate | `POST {base}/translate`，body `{"q":"Hello","source":"en","target":"zh","format":"text"}` | `translatedText` |
| DeepL | `POST https://api-free.deepl.com/v2/translate`，头 `Authorization: DeepL-Auth-Key <key>`，body `{"text":["Hello"],"target_lang":"ZH"}` | `translations[0].text` |
| Google v2 | `POST https://translation.googleapis.com/language/translate/v2?key=<key>`，body `{"q":["Hello"],"target":"zh-CN","format":"text"}` | `data.translations[0].translatedText` |

google 系响应可能对文本做 HTML 实体转义（`&#39;`），插件侧需反转义或改用 `format=text`。

## 6. 错误码与重试策略（OpenAI 错误语义见[官方文档](https://platform.openai.com/docs/guides/error-codes)）

| HTTP | 语义 | 插件行为 |
| --- | --- | --- |
| 400 | 参数/JSON 错误、思考预算不足、参数不被模型支持 | 不重试；改用最小体（model + messages + stream:false）重试 1 次 |
| 401 | Key 缺失/无效/过期 | 登录期提示 Key 无效；运行期静默 |
| 402 | 余额不足（DeepSeek、OpenRouter 等） | 提示充值，不重试 |
| 403 | 无权限、地区限制、内容策略 | 不重试，提示检查账号/地域 |
| 404 | 路径错或模型名不存在 | 提示检查 base URL 是否多/少 `/v1` 与 model 名 |
| 413 | 请求体过大 | 缩短提示词/上下文后重试一次 |
| 422 | 参数非法（DeepSeek 等） | 修正参数，不重试 |
| 429 | 限流/配额/并发超限 | 读 `Retry-After`，退避 1 s、2 s，最多 2 次 |
| 5xx / 529 | 服务端错误 / Anthropic 过载 | 退避重试 ≤ 2 次，仍失败返回空串 |
| 超时/连接失败 | 网络或服务不可达 | 重试 1 次后返回空串，下次字幕再试 |

错误体形态（解析时按顺序尝试）：

- OpenAI / DeepSeek / Groq / vLLM / LM Studio / one-api：`{"error": {"message": "...", "type": "invalid_request_error", "param": null, "code": "invalid_api_key"}}`
- Anthropic：`{"type": "error", "error": {"type": "invalid_request_error", "message": "..."}, "request_id": "req_..."}`
- Gemini：`{"error": {"code": 400, "message": "...", "status": "INVALID_ARGUMENT", "details": [...]}}`
- Ollama：`{"error": "model 'foo' not found"}`（字符串，不是对象）
- Mistral：`{"object": "error", "message": "...", "type": "...", "param": null, "code": "..."}`（待验证）
- GLM / SiliconFlow：可能是顶层 `{"code": ..., "message": ...}` 而非 `error` 包裹（待验证）
- DashScope 兼容模式：多数为 OpenAI 形态；原生 DashScope 可能 HTTP 200 但 body 带 `code`/`message`，不可只看状态码。

解析顺序：字符串 `error` → `error.message` → `error.code` → 顶层 `message` → `code` → 原始 body 截断 200 字符。

## 7. Token、延迟与推荐参数

| 项目 | 经验值（不同 tokenizer 差异 ±30%） |
| --- | --- |
| 单条字幕（< 80 字） | 中文约 20–60 tokens；英文约 15–45 tokens |
| 固定提示词+system | 60–150 tokens（越短越省，建议 ≤ 120） |
| 单次总输入 | 100–250 tokens |
| 输出译文 | 10–80 tokens |
| `max_tokens` / `max_completion_tokens` | 256 足够；长句或英译中建议 512 |
| `temperature` | 0–0.3（支持时；推理模型可能忽略或拒绝） |
| 单次延迟 p50 | 国内云非推理 0.3–1.0 s；海外/代理 0.8–3 s；推理模型 2–30 s |
| 成本量级 | 每 1000 条字幕约 ¥0.01–0.5，随模型价差大 |

建议：一次一条 cue、不带历史（或只带 1–2 句上文）、固定短 system prompt、关闭思考、`stream:false`、HTTP 超时 10 s。实时字幕场景不要用推理模型。

## 8. 插件侧解析规则清单

1. HTTP 层：`HostGetStatusHTTP == 200` 且 body 是合法 JSON；否则走错误路径（§6）。
2. OpenAI 兼容：`choices[0].message.content`；`content` 为 `null`/`""` 时检查 `reasoning_content` 与 `finish_reason`。
3. `content` 是字符串直接用；是数组时遍历，取 `type=="text"` 的 `text` 拼接（部分兼容实现会返回数组）。
4. `finish_reason=="length"` 视为截断：可重试一次更大上限，或回退原文，不要显示半句译文。
5. Anthropic：`content[]` 过滤 `type=="text"` 拼 `text`；忽略 `thinking`/`redacted_thinking`；`stop_reason=="max_tokens"` 截断。
6. Gemini：`candidates[0].content.parts[]` 跳过 `thought==true`，拼接其余 `text`；`finishReason=="MAX_TOKENS"` 截断；无 candidates 时读 `promptFeedback.blockReason`。
7. Ollama：`message.content`；`done_reason=="length"` 截断；`message.thinking` 忽略。
8. 自定义：按配置路径取值（`a.b[0].c`）；数组终值时逐项取 `text`/`content` 拼接；对象终值时取 `text`/`content`。
9. jsoncpp 取值前先判类型：`isString()` / `isArray()` / `isNull()`；不要对 `null` 直接 `asString()`。
10. 后处理：`Trim` → 去 Markdown 代码围栏（三个反引号）与语言标记 → 去常见前缀（`翻译：`、`Translation:`）→ 去整体成对引号 → 规范化换行。
11. 空结果、长度 > 4×原文、含 "As an AI" 等拒答特征时回退原文；连续失败 ≥ 5 次清空上下文。
12. UTF-8 解码失败或 body 以 `<` 开头（HTML 错误页）时按错误处理。

## 9. 官方文档索引与待验证

- OpenAI：[Chat](https://platform.openai.com/docs/api-reference/chat/create)、[Models](https://platform.openai.com/docs/api-reference/models/list)、[Errors](https://platform.openai.com/docs/guides/error-codes)、[Reasoning](https://platform.openai.com/docs/guides/reasoning)
- 国内兼容服务：DeepSeek [Chat](https://api-docs.deepseek.com/api/create-chat-completion) / [Errors](https://api-docs.deepseek.com/quick_start/error_codes)、Kimi [Chat](https://platform.kimi.ai/docs/api/chat)、GLM [Chat](https://docs.z.ai/api-reference/llm/chat-completion)、DashScope [兼容模式](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions)、SiliconFlow [Chat](https://docs.siliconflow.cn/api-reference/chat-completions/chat-completions)
- 海外兼容服务：OpenRouter [Chat](https://openrouter.ai/docs/api-reference/chat-completion) / [Reasoning](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)、Groq [API](https://console.groq.com/docs/api-reference)、xAI [API](https://docs.x.ai/docs/api-reference)、Mistral [Chat](https://docs.mistral.ai/api/)、Together [Chat](https://docs.together.ai/reference/chat-completions)
- 本机/自建：LM Studio [OpenAI 兼容](https://lmstudio.ai/docs/app/api/endpoints/openai)、vLLM [服务端](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html)、one-api [GitHub](https://github.com/songquanpeng/one-api) / new-api [API](https://docs.newapi.pro/api/)
- 专用协议：Anthropic [Messages](https://docs.anthropic.com/en/api/messages) / [Models](https://docs.anthropic.com/en/api/models-list) / [Errors](https://docs.anthropic.com/en/api/errors)、Gemini [generateContent](https://ai.google.dev/api/generate-content) / [Models](https://ai.google.dev/api/models)、Ollama [Chat](https://docs.ollama.com/api/chat) / [Tags](https://docs.ollama.com/api/tags)

待验证：GLM `temperature` 上限与错误体；Mistral 错误体；SiliconFlow 错误体；Kimi/GLM 思考模式对 `temperature` 的约束；Gemini `thinkingBudget: 0` 在全部模型上的效果；Ollama `message.thinking` 字段名；Anthropic `anthropic-version: 2023-06-01` 在 2026 是否仍被接受。

与 `docs/design.md` 预设表的差异（2026 核对）：Anthropic 版本头示例已为 `2026-10-21`；DeepSeek 模型为 `deepseek-v4-flash`/`deepseek-v4-pro` 且 thinking 默认开；Kimi 为 `kimi-k3.1-pro`；GLM 为 `glm-5.3`；DashScope 建议迁移 workspace 专属域名；Together 官方 server 为 `api.together.ai`。预设表中的旧模型名（`gpt-4o-mini`、`deepseek-chat`、`qwen-plus`、`gemini-2.0-flash` 等）需在代码与文档中同步更新为当前可用模型。
