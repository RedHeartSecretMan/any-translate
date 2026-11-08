# 契约测试说明与边界决策

> 位置：`docs/testing/contract.md` ｜ 对应代码：`tests/` ｜ 随 `.as` 契约变更同步
>
> **契约唯一事实来源：`plugin/SubtitleTranslate - AnyTranslate.as` + `docs/design.md`。**
> 当本文件描述与 `.as` 冲突时，以 `.as` 实现与 `docs/design.md` 为准。
> `tests/support/reference_impl.py` 逐函数镜像 `.as`，`tests/test_contract.py` 断言契约，
> `tests/support/mock_server.py` 在网络上复现契约；三者与 `.as` 的对应关系见 §7。

- `ref` = `tests/support/reference_impl.py`（Python 参考实现）
- `.as` = `plugin/SubtitleTranslate - AnyTranslate.as`（行号随迭代漂移，**以函数名为准**）
- design = `docs/design.md`（实现契约文档）

---

## 1. 文件与运行方式

| 文件 | 作用 |
| --- | --- |
| `tests/support/mock_server.py` | 单进程 mock LLM 服务（仅标准库）；记录请求供断言 |
| `tests/support/reference_impl.py` | Python 参考实现：`parse_spec` / `build_request` / `parse_response` / `clean_text` / `login` / `probe` 等，**永不抛异常**，统一返回 `(ok, payload\|Err)` |
| `tests/test_contract.py` | 原生 unittest，**215 个用例**（含 subTest 合计 1100+ 条断言） |
| `tests/run_tests.ps1` | 一键运行：py_compile → 独立 mock 冒烟 → unittest → 摘要 |
| `docs/testing/contract.md` | 本文件 |
| `docs/testing/angelscript-validation.md` | AngelScript 校验工具链调研 |

```powershell
# 一键运行
pwsh -File tests/run_tests.ps1

# 直接 unittest
python -m unittest discover -s tests -v

# 单独启动 mock（默认 18080；--port 0 为随机端口）
python tests/support/mock_server.py --port 18080
python tests/support/mock_server.py --port 18080 --scenario 401
python tests/support/mock_server.py --port 18080 --scenario 405   # 模拟 /models 未实现（登录放行）
```

Python 解释器使用 PATH 中的 `python`（3.10+，契约测试只用标准库）；也可用
`run_tests.ps1 -Python <path>` 或环境变量 `ANYTRANSLATE_PYTHON` 指定。

## 2. mock_server 使用要点

- 路由按**路径后缀**识别，不依赖 host/端口：
  `.../chat/completions`（OpenAI 兼容）、`.../v1/messages`（Anthropic）、
  `.../v1beta/models/<m>:generateContent`（Gemini，Key 在 `x-goog-api-key` 头）、
  `.../api/chat`（Ollama）、其它 POST 路径（自定义 API）、
  `GET .../models|/v1beta/models|/api/tags`（模型列表）。
- 场景切换：路径前缀 `/s/<scenario>/...`、查询参数 `?__scenario=<name>`、
  或启动参数 `--scenario`。场景：
  `ok/success`、`401`、`403`、`404`、`405`、`429`、`500`、`502`(HTML)、
  `badjson`(200+非 JSON)、`array`(OpenAI content 数组)、`reasoning`(仅 reasoning_content)、
  `empty`(choices 空)、`mixed`(思考片段+文本片段)、`slow`(sleep 后返回，用于超时)。
  **404/405 同时用于验证“登录自检遇到未实现 /models 时放行”**。
- 记录接口：`GET /__requests`（JSON 数组，按到达顺序）、`GET /__last`、
  `GET /__health`、`POST|DELETE|GET /__reset`、`POST /__echo`。
  每条记录含 `method/path/route_path/scenario/route/query/headers/raw_headers/
  body/body_json/problems`。
- `problems`：mock 按本契约校验请求得到的问题列表（空 = 合规）。测试在
  E2E happy path 断言 `problems == []`；`test_mock_validation_flags_bad_request`
  反向验证校验器本身有效。`minimal=1` / 本机无 Key 等合法变体不强制 `problems==[]`。
- 固定译文常量（测试逐字断言，改 mock 文案需同步 `test_contract.py`）：
  `OPENAI_TEXT`、`OPENAI_ARRAY_PARTS`、`ANTHROPIC_PARTS`、`GEMINI_PARTS`、
  `OLLAMA_TEXT`、`CUSTOM_TEXTS`。

## 3. 契约矩阵（与 `.as` / design.md 对齐）

### 3.1 login User 字段语法

```
spec   := preset [":" model] ["|" opts]
        | "custom" "|" url ["|" model ["|" opts]]
opts   := kv (";" kv)*        kv := key "=" value
keys   := path | auth | keyname | body | temp | max_tokens | probe | debug | version | minimal | style | context | deadline
auth   := bearer | x-api-key | query | none
```

- 空/纯空白 spec → 默认 `ollama:qwen3:4b`（首装默认；`ServerLogin` 会优先沿用上次
  保存的 spec，见 D-23）。Pass 字段单独承载 API Key，Key 为空时沿用上次保存值。
- preset 形式**只按第一个 `:` 切分**：`ollama:qwen3:4b` → model=`qwen3:4b`。
- **opts 对任意 spec 都生效**：`deepseek:deepseek-chat|debug=1`、
  `openai|max_tokens=512` 均合法。
- **只写 preset（无 model）→ 使用预设默认模型**（`P_MODEL`，18 项见 §3.2）。
- custom 的 url 是**完整请求地址**（不再追加协议路径）；model 可省略。
- preset 名大小写不敏感；`custom|` 前缀大小写敏感（`.as` 用 `StartsWith`）。
- opts 容错（镜像 `.as`）：缺 `=` / key 为空 / 未知 key 的片段**静默跳过**；
  `temp` 删除非 `[0-9.]` 字符后为空则回退 0.2，`.5`→`0.5`、`1.`→`1`；
  `max_tokens` 只保留数字，为空则不发送；`debug` / `minimal` 仅 `1` 或 `true` 为真；
  `version` 原样透传；`context` 只取数字并夹到 0..8；`style` 默认 `movie`；
  `deadline` 只取数字并夹到 2000..20000，默认 6000。
- 非法值报错（与 `.as` 文案一致）：未知服务商、custom 缺 URL、auth 取值非法、
  style 不在 `movie/tv/anime/doc/tech/formal/casual` 内。

### 3.2 provider 预设（base / 默认模型 / 协议 / 鉴权）

| preset | base URL | 默认模型 | kind | 默认 auth / keyname |
| --- | --- | --- | --- | --- |
| vllm | `http://127.0.0.1:8000/v1` | 服务端默认模型 | openai | none |
| sglang | `http://127.0.0.1:30000/v1` | 服务端默认模型 | openai | none |
| lmstudio | `http://127.0.0.1:1234/v1` | 服务端默认模型 | openai | none |
| ollama | `http://127.0.0.1:11434` | 留空（用 `ollama:<model>` 指定） | ollama | none |
| openai | `https://api.openai.com/v1` | `gpt-5.6-terra` | openai | bearer |
| deepseek | `https://api.deepseek.com/v1` | `deepseek-v4-flash` | openai | bearer（追加关闭思考字段） |
| moonshot | `https://api.moonshot.cn/v1` | `kimi-k3.1-pro` | openai | bearer |
| zhipu | `https://open.bigmodel.cn/api/paas/v4` | `glm-5.3` | openai | bearer |
| qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-flash` | openai | bearer（追加关闭思考字段） |
| siliconflow | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V4-Flash` | openai | bearer（追加关闭思考字段） |
| openrouter | `https://openrouter.ai/api/v1` | `openai/gpt-5.6-terra` | openai | bearer |
| groq | `https://api.groq.com/openai/v1` | `openai/gpt-oss-120b` | openai | bearer |
| xai | `https://api.x.ai/v1` | `grok-4.7` | openai | bearer |
| mistral | `https://api.mistral.ai/v1` | `mistral-small-latest` | openai | bearer |
| together | `https://api.together.ai/v1` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` | openai | bearer |
| anthropic | `https://api.anthropic.com` | `claude-sonnet-4-6` | anthropic | x-api-key / `x-api-key` |
| gemini | `https://generativelanguage.googleapis.com` | `gemini-3.5-flash` | gemini | x-api-key / `x-goog-api-key` |
| custom | 用户自填完整请求地址 | 服务端默认模型 | openai（默认） | bearer |

厂商扩展字段（`.as P_EXTRA`，仅 OpenAI 兼容、非 custom、非 minimal）：
`deepseek` 追加 `{"thinking":{"type":"disabled"}}`；`qwen`、`siliconflow` 追加
`{"enable_thinking":false}`。

### 3.3 URL / 请求头 / 请求体（ref 断言口径）

所有 URL 都是 `base.rstrip("/")` 后拼接；所有请求统一头
`Content-Type: application/json` + `Accept: application/json`：

| kind | URL | 认证 | 请求体（非 minimal） |
| --- | --- | --- | --- |
| openai | `{base}/chat/completions` | `Authorization: Bearer <key>`（key 非空） | `{model?, messages:[{role:"user",content:prompt}], stream:false, temperature:0.2, [max_completion_tokens], 厂商扩展字段}` |
| anthropic | `{base}/v1/messages` | `x-api-key: <key>`（key 非空）+ `anthropic-version: <version>` | `{model?, max_tokens:1024(可覆盖), messages:[{role:"user",content:prompt}]}` |
| gemini | `{base}/v1beta/models/{model}:generateContent`（**Key 不进 URL**） | `x-goog-api-key: <key>`（key 非空） | `{contents:[{parts:[{text:prompt}]}], generationConfig:{temperature, [maxOutputTokens], thinkingConfig:{thinkingBudget:0}}}` |
| ollama | `{base}/api/chat` | 默认无认证 | `{model?, messages:[…], stream:false, think:false, options:{temperature, [num_predict]}}` |
| custom | 用户 URL 原样 | 按 auth：bearer/x-api-key/query/none | body 模板优先；否则 OpenAI 兼容体 |

补充：
- `minimal=1`：openai/custom 只保留 `{model?, messages, stream:false}`；
  ollama 只保留 `{model?, messages, stream:false}`；gemini 去掉
  `thinkingConfig`（保留 temperature）；anthropic 无 minimal 分支。
  custom 带 `body` 模板时模板优先，`minimal` 不生效。
- `max_tokens=` 映射：openai/custom → `max_completion_tokens`；ollama →
  `options.num_predict`；gemini → `generationConfig.maxOutputTokens`；
  anthropic → `max_tokens`。默认不发送（anthropic 回退 1024）。
- `auth=query`：`{url}?{keyname}={urlencode(key)}`，已有 `?` 用 `&`；
  未显式 `keyname=` 时参数名**归一化为 `key`**（即使预设默认 keyname 是
  `x-goog-api-key`/`x-api-key`）；显式 `keyname=` 优先。翻译与登录自检共用
  `AppendQueryAuth`，日志必须脱敏（`SafeUrl`，见 §4）。
- `auth=x-api-key` 头名取 `keyname`（默认按 auth 类型：`x-api-key` / `key`）；
  `version` 只影响 anthropic 的 `anthropic-version`。
- 自定义 `body` 模板占位符（与 `.as` 一致）：`{{prompt}}`、`{{text}}`、
  `{{model}}`、`{{src}}`、`{{dst}}`，替换值为 JsonEscape 后的文本；`{{src}}`/`{{dst}}`
  是提示词语言显示名，不是语言码。
  ref 额外校验替换后仍是合法 JSON（`.as` 不校验，见 E-16）。
- 请求体是 **UTF-8、单行、合法 JSON**；字符串转义规则见 §4。
- OpenAI 兼容请求体 `model` 为空时省略该字段（lmstudio/vllm/sglang/custom）。

### 3.4 响应提取（统一 `ExtractByPath` + `NodeText`）

默认 path：openai `choices[0].message.content`、anthropic `content`、
gemini `candidates[0].content.parts`、ollama `message.content`、custom
`choices[0].message.content`；任意 spec 可用 `path=` 覆盖。

- 路径按 `.` 切分，`name[index]` 只支持 **0-9 单数字下标**（DESIGN 6.2）；
  支持根数组 `[0].text`。
- 终值：
  - 字符串 → 直接返回；
  - 数组 → 逐项取文本，**用 `\n` 连接非空项**（多段文本块 → 多行）；
  - 对象 → `thought=true` 跳过；`type=thinking|redacted_thinking|reasoning`
    跳过；否则取 `text`，再取 `content`（字符串/数组/对象递归）。
- 所有成功响应再过 `clean_text`（§3.6）。
- `reasoning_only` 是 ref 级的可区分错误码（`200` 但提取为空且存在
  reasoning_content/thinking）；`.as` 侧表现为 `SendOnce` 失败返回空串。

### 3.5 错误码（稳定中文，供断言）

| 条件 | `Err.code` | `Err.message` |
| --- | --- | --- |
| HTTP 400 | bad_request | 请求参数错误 (HTTP 400) |
| HTTP 401 | auth_failed | API Key 无效或已过期 (HTTP 401) |
| HTTP 402 | insufficient_balance | 账户余额不足 (HTTP 402) |
| HTTP 403 | forbidden | 没有访问权限 (HTTP 403) |
| HTTP 404 | not_found | 接口地址或模型不存在 (HTTP 404) |
| HTTP 408 | timeout | 请求超时 (HTTP 408) |
| HTTP 413 | payload_too_large | 请求体过大 (HTTP 413) |
| HTTP 422 | invalid_params | 参数非法 (HTTP 422) |
| HTTP 429 | rate_limited | 请求过于频繁，请稍后重试 (HTTP 429) |
| HTTP 5xx | server_error | 服务端错误 (HTTP {status})，请稍后重试 |
| 其它 4xx | client_error | 请求被拒绝 (HTTP {status}) |
| 其它/3xx | http_error | 非预期 HTTP 状态 (HTTP {status}) |
| 200 但非 JSON | bad_json | 响应不是合法 JSON，无法解析 |
| 200 但空 body | empty_response | 服务端返回空响应 |
| JSON 无译文 | no_content | 响应中未找到译文内容 |
| 只有思考内容 | reasoning_only | 模型只返回了思考过程（reasoning_content），没有输出译文 |
| 200 但含 `error` 对象 | provider_error | 服务端返回错误，未返回译文 |
| 超时 / 连接失败 | timeout / network | 请求超时… / 网络连接失败… |
| spec 语法/预设/opts | bad_spec / bad_preset / config_error / bad_opts | 中文说明（对齐 `.as` 文案） |

约定：**服务端原始报错只放进 `Err.detail`**，`Err.message` 只用于稳定映射。
`.as` 不向 UI 展示错误码（`Translate` 失败返回空串，`debug=1` 时 Dbg 输出
`ErrorHint()` 中文），两者语义对照见 §7 第 8 条。

### 3.6 clean_text（镜像 `CleanTranslation` / `StripKnownPrefixes`）

顺序：trim → 若以 ``` 开头去掉到第一个换行 → 若以 ``` 结尾去掉后 3 字符 →
trim → 去常见前缀（14 项表，最多 3 轮）→ `原文：/Original:` 去掉首行 →
去整体包裹的成对引号（`""` `“”` `「」` `『』`）→ CRLF/CR 规范化 →
`<br/>`/`<br />`/`<br>` 转换行 → `\n\n\n` → `\n\n` → RTL（ar/he/fa/ur，
按 `L_CODE`/`L_LABEL` 映射；菜单返回语言代码，本地化名称由 PotPlayer 提供）前置 U+202B → trim。

注意：`Here is the translation:` **不在** `.as` 前缀表中，不会被去掉；
`<BR>`（大写）不会被替换；`.as` 只把 3 连换行压成 2 连，不是无限压缩。

### 3.7 登录自检（`ServerLogin` + `Probe`）

- `probe` 默认：预设 `models`，custom `none`；`probe=none` 或 custom 不探测。
- 探测 URL：openai `{base}/models`、ollama `{base}/api/tags`、
  anthropic `{base}/v1/models`、gemini `{base}/v1beta/models`
  （`auth=query` 时与翻译共用 `AppendQueryAuth`，URL 追加 `?key=<key>`，
  且不带任何认证头）。
- 探测请求复用同一套请求头（Content-Type/Accept；认证头取决于 auth 模式，
  query 模式无认证头）。
- 状态码：**404/405 视为该服务未实现模型列表 → 跳过校验、放行登录**；
  401/403 → “API Key 无效或无权限（HTTP n）”；402/413/422/429/5xx →
  对应中文文案（与 `.as` Probe 逐字一致）；其它非 2xx → “登录自检失败（HTTP n）: body”。
- 模型匹配：大小写不敏感；允许 `model -> model:tag` 前缀匹配
  （如 `qwen3` 匹配 `qwen3:4b`）；不匹配时提示
  “未找到模型: X；可用示例: …”。
- 登录前置校验：非 none 认证且非 custom 时 Key 必填；anthropic/gemini/ollama
  必须有模型名（anthropic/gemini 由预设默认模型保证非空，ollama 必须显式
  `ollama:<model>`）；custom 允许无 Key。

## 4. JSON 转义与日志脱敏（`.as` 对齐）

`reference_impl.json_escape` 镜像 `.as::JsonEscape`（`.as` 用 `StripChars` 循环剔除，
上限 1024 次）：

1. **剔除 C0 控制字符（`\t` / `\n` / `\r` 除外）**：删除 `\x00-\x08`、
   `\x0B`、`\x0C`、`\x0E-\x1F`；因此 `\b`(0x08)、`\f`(0x0C) 也被删除而
   **不是**转义成 `\b`/`\f`（JSON 不允许裸控制符）；
2. `\` → `\\`、`"` → `\"`，`\t` / `\n` / `\r` 用短转义；
3. 非 ASCII 原样保留（UTF-8 发送）；`/`、`\u007F`、`\u2028/\u2029` 不特殊处理。

测试 corpus 见 `TestJsonEscaping.CORPUS`（空串、引号、反斜杠、换行/制表/回车、
控制字符含 `\b`/`\f`、中文、emoji、`<script>`、`\u2028`、DEL）。
`test_roundtrip_after_control_removal` 断言
`json.loads('"'+json_escape(t)+'"') == 剔除控制字符后的 t`；请求体仍必须是合法 JSON。
**注意**：ref 不再保证与 `json.dumps` 逐字符相等（控制字符处理不同），这是
`.as` 的既定行为。

日志脱敏（fail-safe，P1 修复后）：
- `SafeUrl(url)`：**先替换 `HostUrlEncode(key)`，再替换原始 key** 为 `****`
  （`auth=query` 时 Key 在 URL 中且可能已被 percent-encode；两种形式都要脱敏）；
- `MaskKey(key)`：空 → `(未设置)`；长度 **< 16** → `****`；否则 `前4****后4`。
测试用含 `+ / =` 的 Key 断言编码形式与原始形式都不出现在脱敏后 URL 中，
并覆盖 9/15/16 位边界。

## 5. E 列表：与 `.as` 的差异处理结果（按当前实现对齐后）

图例：✅ resolved/tests aligned = ref 与用例已按 `.as` + design.md 对齐并通过；
📌 保留差异（已文档化，非冲突）；⏳ 不在本测试范围。

| # | 主题 | 对齐结果 | 状态 |
| --- | --- | --- | --- |
| E-01 | together 域名 | 以 `.as`/providers.md 为准：`https://api.together.ai/v1` | ✅ resolved |
| E-02 | Gemini Key 位置 | 以 `.as` 为准：`x-goog-api-key` 请求头，Key 不进 URL | ✅ resolved |
| E-03 | 只写 preset 的 model | 用 `P_MODEL` 预设默认模型（18 项，DESIGN §5.1） | ✅ resolved |
| E-04 | Anthropic `max_tokens` | 默认 1024，可 `max_tokens=` 覆盖 | ✅ resolved |
| E-05 | 默认 temperature | 0.2（`temp=` 可覆盖，非法字符清除后回退 0.2；`.5`→`0.5`、`1.`→`1`） | ✅ resolved |
| E-06 | 数组/多文本块拼接 | 用 `\n` 连接非空项（Anthropic 多块=多段） | ✅ resolved |
| E-07 | 请求体厂商扩展字段 | `P_EXTRA` 的 deepseek/qwen/siliconflow 关思考字段 + Gemini generationConfig | ✅ resolved |
| E-08 | 额外请求头 | 所有请求（含 probe）统一带 `Accept: application/json` | ✅ resolved |
| E-09 | opts 扩展 | 任意 spec 支持 opts（竖线分隔）；新增 `max_tokens`/`version`/`minimal`；body 占位符 `{{prompt}}{{text}}{{model}}{{src}}{{dst}}` | ✅ resolved |
| E-10 | 登录自检 | probe 默认、404/405 放行、Key 必填、模型名匹配、custom 不探测 | ✅ resolved |
| E-11 | 重试策略 | `.as` 的 400/空响应/429/5xx/质量重试都受单条 `deadline` 预算约束；单请求 mock 无法断言次数，测试不覆盖。质量门判定由 `validate_translation` 单测覆盖 | ⏳ out of scope（次数） |
| E-12 | clean_text 细节 | 前缀表/去包裹引号/换行压缩/`<br>` 均按 `.as` 对齐 | ✅ resolved |
| E-13 | 错误呈现方式 | ref 用稳定错误码 + `Err.detail` 供断言；`.as` 返回空串 + `ErrorHint` Dbg，不向字幕混入错误文案（DESIGN §4） | 📌 interface difference |
| E-14 | lmstudio/vllm/sglang 认证 | auth=none，无需 Key（`P_AUTH`） | ✅ resolved |
| E-15 | 默认 probe | 预设 `models`、custom `none`（DESIGN §5.2） | ✅ resolved |
| E-16 | body 模板 JSON 校验 | `.as` 不校验；ref 额外校验并返回 `bad_body_template`（安全增强，防注入/坏请求） | 📌 ref stricter |
| E-17 | path 下标限制 | 只支持 0-9 单数字（DESIGN 6.2）；多位数 `[10]` 在 `.as` 与 ref 中都取不到值 | ✅ aligned |
| E-18 | 持久化/上下文/缓存/重试 | `HostSaveString`、历史窗口、缓存、暂停重置等状态行为不属纯契约函数 | ⏳ out of scope |
| E-19 | **P1 修复回归**（2026-11-07） | `SafeUrl` 先替换 `HostUrlEncode(key)` 再替换原始 key；`auth=query` 未显式 keyname 时归一化为 `key`；`AppendQueryAuth` 同时用于翻译与 Probe（probe URL 带 `?key=`、无认证头）；`MaskKey` 长度 <16 → `****`；`ErrorHint` 404 文案 = “接口地址或模型不存在”；`JsonEscape` 用 `StripChars` 剔除 C0（`\t\n\r` 除外，含 `\b`/`\f`） | ✅ resolved |

## 6. D 列表：契约歧义与 ref 决策

| # | 歧义/边界 | ref 决策（测试断言） | 状态 |
| --- | --- | --- | --- |
| D-01 | 空 spec 语义 | `parse_spec("")` → `ollama:qwen3:4b`；登录时 `.as` 优先沿用上次保存 spec（持久化） | 已文档化 |
| D-02 | 只写 preset | 用 P_MODEL 默认模型（同 E-03） | resolved |
| D-03 | custom 省略 model | 合法（custom、竖线、url，model 可空）；默认请求体省略 model | aligned |
| D-04 | custom 任意 scheme | `.as` 不校验 URL scheme，ref 同样接受（运行期由 HTTP 层失败） | aligned |
| D-05 | opts 容错 | 缺 `=`/空 key/未知 key 静默跳过；重复 key 后者覆盖；值内允许 `\|`（custom opts） | aligned |
| D-06 | 非法 auth | 报 `bad_opts`，文案与 `.as` 一致 | aligned |
| D-07 | temp/max_tokens 清洗 | 非数字字符删除；temp 空/多小数点→0.2，`.5`→0.5、`1.`→1；max_tokens 空→不发送 | aligned |
| D-08 | probe 取值 | `.as` 不校验，只要不是 `none` 就自检 | aligned |
| D-09 | path 覆盖范围 | 任意 spec 可用 `path=` 覆盖默认提取路径 | aligned |
| D-10 | 路径下标 | 0-9 单数字；根数组 `[0].text` 支持 | aligned |
| D-11 | 数组拼接 | `\n` 连接非空项 | resolved |
| D-12 | 思考块 | `thought=true` 与 type=thinking/redacted_thinking/reasoning 跳过 | aligned |
| D-13 | reasoning-only | ref 返回 `reasoning_only` 便于断言；`.as` 表现为失败返回空串 | interface difference |
| D-14 | 200 含 error 对象 | ref 返回 `provider_error` 并提取 `error.message` 到 detail | ref abstraction |
| D-15 | 状态码文案 | ref 稳定文案与 `.as` `ErrorHint`/`Probe` 语义对应；登录期文案逐字对齐 | aligned |
| D-16 | 空 Key 认证头 | 不发认证头（含 anthropic-version）；登录期另行校验 Key 必填 | aligned |
| D-17 | auth=query 编码 | URL encode；日志经 SafeUrl 脱敏 | aligned |
| D-18 | JSON 控制字符 | 删除 C0（除 \t\n\r）而非转义（同 `.as`） | aligned |
| D-19 | clean_text 前缀 | 采用 `.as` 14 项前缀表；不处理 “Here is the translation:” | aligned |
| D-20 | 包裹引号 | 成对引号整体去除（`""`/`“”`/`「」`/`『』`） | aligned |
| D-21 | prompt 措辞 | 不逐字属契约；tests 断言结构、风格块、语言规则、上下文块、原文位置与结尾约束；`.as BuildPrompt` 与 ref 结构对齐 | free |
| D-22 | 402/413/422 | 单列错误码，与 `.as` Probe/ErrorHint 对齐 | aligned |
| D-23 | 登录持久化 | `ServerLogin` 空 spec/空 Key 沿用保存值；ref 纯函数用默认值，持久化不测 | out of scope |
| D-24 | 模板 JSON 校验 | ref 额外校验（E-16） | ref stricter |
| D-25 | 模型匹配 | 忽略大小写；`want:tag` 前缀匹配（`.as ModelMatched`） | aligned |
| D-26 | 探测请求头 | 复用 BuildHeaders（Content-Type/Accept/认证头）；`auth=query` 时 probe 与翻译共用 AppendQueryAuth（URL 带 `?key=`、无认证头） | aligned |
| D-27 | auth=query 参数名 | 未显式 `keyname=` 时归一化为 `key`（P1 修复）；显式 keyname 优先 | aligned |
| D-28 | SafeUrl 脱敏 | 先替换 `HostUrlEncode(key)` 再替换原始 key（两种形式都变 `****`） | aligned |
| D-29 | MaskKey 阈值 | 长度 <16 → `****`；≥16 才显示前4/后4 | aligned |
| D-30 | JsonEscape C0 | 剔除 C0（`\t\n\r` 除外），`\b`/`\f` 也剔除而非转义；`StripChars` 上限 1024 | aligned |
| D-31 | 404 文案 | `ErrorHint` 404 = “接口地址或模型不存在”；ref 稳定文案含同一短语 | aligned |
| D-32 | style/context/deadline | `style` 默认 `movie`，非法值报 `bad_opts`；`context` 默认 4、夹到 0..8；`deadline` 默认 6000、夹到 2000..20000；三者都参与运行时行为，不改变 HTTP 协议 | aligned |
| D-33 | 译文质量门 | `validate_translation` 返回 `empty` / `echo` / `wrong_script` / `too_long`；`validation_reason_zh` 提供重试提示中文原因；拉丁短名/缩写放行 | ref abstraction |
| D-34 | 非对白过滤 | 纯符号/数字/音乐符号行由 `is_non_dialogue_text` 判定，本地原样返回，不请求 API | ref abstraction |

## 7. 人工交叉核对清单（`.as` ↔ tests）

按此顺序核对，可覆盖全部三层契约（`.as` 以函数名为准）：

1. **常量**：`PRESETS` ↔ `P_ID/P_BASE/P_MODEL/P_PROTO/P_AUTH/P_KEYNAME/P_EXTRA`
   （18 行逐项，`test_all_presets_resolve_to_expected_defaults` +
   `test_all_preset_headers` + `test_all_preset_chat_urls`）；
   `DEFAULT_SPEC`、`DEFAULT_TEMPERATURE=0.2`、`DEFAULT_ANTHROPIC_MAX_TOKENS=1024`、
   `DEFAULT_ANTHROPIC_VERSION=2023-06-01`。
2. **spec 解析**：`parse_spec` ↔ `ParseSpec`；对照 `TestSpecParsing` 全部用例：
   空 spec、preset 默认模型、第一个 `:` 切分、任意 spec 的 `|opts`、
   13 个 opts key、容错与非法输入文案、custom 省略 model、大小写。
3. **URL**：`build_url` ↔ `BuildUrl` + `AppendQueryAuth`；`test_all_preset_chat_urls`、
   `test_gemini_key_never_in_url`、custom/`auth=query` 用例
   （gemini/openai/anthropic 的 `?key=`、显式 keyname、无认证头）。
4. **请求头**：`build_headers` ↔ `BuildHeaders`；`test_all_preset_headers`、
   `test_anthropic_request`、`test_anthropic_version_override`、
   `test_gemini_request`、`test_custom_auth_*`、`test_auth_query_*`、
   `test_content_type_and_accept_on_every_provider`。
5. **请求体**：`build_body` ↔ `BuildBody`；各 `test_*_request`、`test_minimal_bodies`、
   `test_max_tokens_maps_per_protocol`、厂商扩展字段用例、
   `test_body_is_single_line_valid_json_and_controls_removed`；
   再核对 `JsonEscape`（§4 corpus）。
6. **响应提取**：`parse_response` ↔ `SendOnce` + `ExtractByPath` + `WalkPath` +
   `NodeText`；对照 `TestResponseParsing`：默认 path、路径覆盖、`\n` 拼接、
   思考块跳过、根数组、单数字下标、reasoning-only 判定、清洗。
7. **清洗**：`clean_text`/`strip_known_prefixes` ↔ `CleanTranslation`/
   `StripKnownPrefixes`；对照 `TestCleanText.test_clean_text_cases`。
8. **提示词/质量门**：`build_prompt`/`validate_translation`/`validation_reason_zh`/
   `target_rules`/`is_non_dialogue_text` ↔ `BuildPrompt`/`ValidateTranslation`/
   `ValidationReasonZh`/`TargetRules`/`IsNonDialogueText`；对照 `test_build_prompt_*`、
   `test_validate_translation`、`test_non_dialogue_filter`、`test_target_rules`。
9. **错误**：`_status_error` 稳定文案 ↔ `SendOnce` 状态判断 + `ErrorHint` 语义；
   对照 `test_status_code_mapping_is_stable_chinese` 与 `ErrorHint` 分支
   （400/401/402/403/404/413/422/429/5xx）。
10. **模型列表/登录**：`build_probe_request`/`parse_models_response`/
    `model_matched`/`login` ↔ `ProbeUrl`/`Probe`/`ParseModels`/`ModelMatched`/
    `ServerLogin`；对照 `TestProbeAndLoginUnit` + `TestMockServerE2E` 登录用例
    （404/405 放行、401/429/500 文案、大小写、ollama tag 前缀、custom 不探测、
    `auth=query` 时 probe URL 带 `?key=` 且无认证头）。
11. **脱敏**：`safe_url`/`mask_key`/`host_url_encode` ↔ `SafeUrl`/`MaskKey`/`HostUrlEncode`；
    `test_safe_url_masks_encoded_and_raw_key`、`test_mask_key`（9/15/16 位边界）。
12. **入口函数**：`GetTitle/GetVersion/ServerLogin/Translate/...` 与
    `tests/test_static.py` 的入口检查对齐（该工具已覆盖）。

## 8. 下次同步清单（`.as` 或 design.md 再变更时）

> 任何人修改 `.as` 的以下任一处，都必须同步更新 `tests/support/reference_impl.py` +
> `tests/test_contract.py` + `tests/support/mock_server.py`（如涉及）+ 本文件，并跑
> `pwsh -File tests/run_tests.ps1` 与 `python -m unittest tests.test_static -v`。

1. 预设表 7 列（`P_ID/P_BASE/P_MODEL/P_PROTO/P_AUTH/P_KEYNAME/P_EXTRA`）任一项；
2. 默认常量：`DEFAULT_SPEC`、默认 temperature、anthropic `max_tokens`/`version`；
3. `ParseSpec` 语法或 opts key 集合/容错规则/错误文案（含 `style`/`context`/`deadline`）；
4. `BuildUrl`/`BuildHeaders`/`BuildBody` 任一分支（URL 后缀、认证头、minimal、
   max_tokens 映射、厂商扩展字段、body 模板占位符）；
5. `BuildPrompt`/`ValidateTranslation`/`TargetRules`/`IsNonDialogueText`（风格模板、
   语言规则、上下文块、质量门、非对白过滤）；
6. `ProbeUrl`/`Probe`/`ServerLogin`（探测路径、404/405 放行规则、Key/模型前置
   校验、错误文案）；
7. `ExtractByPath`/`WalkPath`/`NodeText`（默认 path、`[n]` 规则、数组分隔符、
   思考块 type 集合、对象取值顺序）；
8. `CleanTranslation`/`StripKnownPrefixes`（前缀表、围栏、包裹引号、换行规则）；
9. `JsonEscape`/`SafeUrl`/`MaskKey`/`StripChars`（C0 剔除规则、先编码后原始 Key
   的脱敏顺序、MaskKey 阈值 <16）；
10. 新增协议/预设：同步 mock 路由与 `problems` 契约校验、DESIGN §5/§6、本文件 §3；
11. 回归命令：`pwsh -File tests/run_tests.ps1`（含独立 mock 冒烟）+
    `python -m unittest tests.test_static -v` + 人工按 §7 抽查。

## 9. 未覆盖范围

- 不执行/编译 AngelScript（见 `angelscript-validation.md`）；`.as` 语法与
  PotPlayer 运行时行为需实机验证。
- `.as` 的重试策略、上下文滑动窗口、缓存、暂停重置、语言表映射、登录持久化、
  UI 文案不在契约测试范围（E-11/E-18、D-23）；质量门的判定函数由
  `validate_translation` 单测覆盖，但"哪次请求触发重试"仍属状态行为。
- PotPlayer `HostOpenHTTP`/`HostGetStatusHTTP` 的超时单位与编码行为属宿主行为，
  ref 用 urllib 模拟。
- 真实供应商 API 未调用（全部走 mock，不产生费用、不依赖外网）。
- 本机 Windows 安全策略把“连接被拒绝”表现为超时，`test_e2e_connection_failure`
  同时接受 `network`/`timeout`；`network` 的稳定映射用未知 URL scheme 单独覆盖。

---

最后更新：2026-11-07（0.1.0：style/context/deadline、目标语言规则、译文质量门、
非对白过滤；同时回归 SafeUrl 编码脱敏 / auth=query 归一化 / MaskKey <16 /
ErrorHint 404 / JsonEscape 剔除 C0；216 用例全部通过，`run_tests.ps1` 一键 PASS）。
