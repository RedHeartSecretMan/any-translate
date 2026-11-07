# AnyTranslate 设计说明

> PotPlayer 实时字幕翻译插件，单文件 AngelScript 实现，可接入任意 LLM / 翻译 API。
> 版本：0.1.0（脚本 `GetVersion` 返回 `0.1.0`）｜作者：RedHeartSecretMan｜文档状态：实现契约

## 1. 背景与目标

PotPlayer 的实时字幕翻译通过 `Extension\Subtitle\Translate\` 下的 AngelScript 插件实现。
本项目目标：

- 用一个插件接入多类 API：OpenAI 兼容端点、DeepSeek、Kimi、智谱、硅基流动、
  OpenRouter、Anthropic、Gemini、LM Studio、vLLM、Ollama，以及任意自定义 JSON 接口；
- 配置收敛到登录框的两个输入框（spec + API Key），不要求用户改源码；
- 登录时自检 Key 与模型名，失败给出可操作的中文提示；
- 实时字幕场景优先：上下文、缓存、超时控制、失败静默不污染字幕；
- 单文件分发，复制进 `Extension\Subtitle\Translate` 即可用。

## 2. 设计取舍

| 取舍 | 选择 | 原因 |
| --- | --- | --- |
| 协议抽象 | 5 类适配器（OpenAI 兼容 / Anthropic / Gemini / Ollama / custom） | 覆盖主流云端与本机服务，custom 兜底非标准 JSON 接口 |
| 配置方式 | 登录框一行 spec + opts | PotPlayer 登录框只有两个输入框；不引入外部配置文件，降低配置错误率 |
| 流式输出 | 不使用 | `Translate()` 必须同步返回最终字符串，流式没有落点 |
| 线程/异步 | 不使用 | 同上；引入线程只增加竞态与复杂度 |
| 错误呈现 | 登录期中文提示，运行期静默返回空串 | 避免把错误文案混进字幕；诊断信息走 `debug=1` 控制台 |
| 失败降级 | 400 → 最小体并记忆；200 空 → 重试 | 兼容推理模型对参数的限制，同时避免重复请求 |
| 配置持久化 | `HostSaveString`（PotPlayer 脚本存储） | 与插件接口一致；不额外引入文件 |
| 提示词 | 中文指令 + 硬规则 + 近 4 句上下文 | 单条字幕 token 可控，上下文提升指代/术语一致性 |

## 3. 技术可行性（PotPlayer 脚本 API）

依据本机 `Extension\api.txt`（随 26.10.21.0 扩展包分发）、官方自带插件的实际用法，
以及从 `PotPlayer64.dll` 二进制中提取的宿主函数签名（见 `docs/api-signatures.txt`）。

### 3.1 使用的能力

| API | 用途 | 依据 |
| --- | --- | --- |
| `HostOpenHTTP` / `HostGetContentHTTP` / `HostGetStatusHTTP` / `HostGetHeaderHTTP` / `HostCloseHTTP` | 同步 HTTP(S)，可拿到状态码与响应头 | api.txt:107-123；`PotPlayer64.dll` 中签名 `uintptr HostOpenHTTP(...)`、`int HostGetStatusHTTP(uintptr)`；官方 `LM Studio.as` 已在用 `HostOpenHTTP` |
| `HostUrlGetString` | 备用简单 GET/POST | api.txt:101；官方 google、DeepL 插件在用 |
| `HostIncTimeOut` | 单次翻译延长脚本超时预算 | api.txt:42；签名 `void HostIncTimeOut(int)` |
| `HostLoadString` / `HostSaveString` | 持久化配置（spec、Key） | api.txt:222-226；`bool HostSaveString(const string &in, const string &in)` |
| `HostGetTickCount` | 检测长时间暂停，重置上下文 | api.txt:39；`uint HostGetTickCount()` |
| `HostOpenConsole` / `HostPrintUTF8` | `debug=1` 时输出诊断日志（Key 脱敏） | api.txt:15-22 |
| `JsonReader` / `JsonValue` | 解析响应，支持 `[int]`、`[string]` 索引 | api.txt:367-397 |
| `string` 标准方法 `findFirst` / `substr` / `length` / `empty` / `Trim` / `Left` / `Right` | 配置语法解析、文本清洗 | google.as 使用 `findFirst/substr`；LM Studio.as 使用 `Right`；官方插件使用 `Trim/empty` |

### 3.2 明确不用的能力及原因

| 能力 | 不用的原因 |
| --- | --- |
| `HostCreateThread` + `Event`/`Mutex` | `Translate()` 必须同步返回字符串，异步无法把结果送回当前字幕行；引入线程只增加复杂度与竞态风险 |
| 流式输出（SSE） | 同上，每行字幕只接受一次最终结果；`stream:false` 是唯一正确选择 |
| `HostExecuteProgram` | 会引入外部进程依赖，破坏"单文件复制即用" |
| `HostMessageBox` | 打断播放体验；错误以返回值和控制台日志呈现 |
| `IniFile` / 文件配置 | 双字段登录框之外再引入配置文件，会显著提高错误配置概率；spec 单行语法已能表达全部选项 |

### 3.3 关键约束

1. **登录框只有两个输入框**：`User` 承载服务 spec，`Pass` 承载 API Key。
   因此 spec 必须是一行可读、可粘贴的短语法。
2. **脚本 API 版本以实际构建为准**：`HostGetStatusHTTP` 等函数已在本机
   26.10.21.0 的 `PotPlayer64.dll` 中确认存在；官方 `LM Studio.as` 已实际使用
   `HostOpenHTTP`。README 标注最低版本要求。
3. **无自动化测试环境**：AngelScript 在本机无法直接执行，验证见第 9 节。

## 4. 插件契约

```
string GetTitle()                       -> "AnyTranslate"
string GetVersion()                     -> "0.1.0"
string GetDesc()                        -> 一句话说明 + 文档地址
string GetLoginTitle()                  -> 配置说明标题
string GetLoginDesc()                   -> spec 语法示例
string GetUserText()                    -> "服务: <当前 spec 摘要>"
string GetPasswordText()                -> "API Key: <脱敏>"
string ServerLogin(string User, string Pass) -> "200 ok" 或中文错误
void   ServerLogout()
array<string> GetSrcLangs()             -> ["自动检测", ...]
array<string> GetDstLangs()             -> [...]
string Translate(string Text, string &in SrcLang, string &in DstLang)
void OnInitialize() / void OnFinalize()
```

失败约定：`Translate` 返回空串（与 google、DeepL、LM Studio 官方插件一致），
不把错误文案混进字幕；`ServerLogin` 返回非 `200 ok` 时 PotPlayer 会弹错误。

## 5. 配置语法

登录框 `User` 字段：

```
preset[:model][|opts]                      例：deepseek:deepseek-v4-flash|debug=1
custom|<endpoint_url>|<model>|[opts]       例：custom|https://api.example.com/v1/chat/completions|my-model
```

- `preset` 不区分大小写；`model` 只按**第一个** `:` 切分，因此
  `ollama:qwen3:4b` 合法；
- 任意 spec 都可以在结尾用 `|` 追加 opts（预设与 custom 都支持）；
- `custom` 的 `endpoint_url` 是**完整请求地址**（不再追加协议路径），`model`
  可留空（服务端默认模型）；
- `opts` 以 `;` 分隔、`=` 赋值：`path`、`auth`、`keyname`、`body`、`temp`、
  `max_tokens`、`minimal`、`version`、`probe`、`debug`；
- `auth=query` 时 Key 拼进 URL（参数名 `keyname`，默认 `key`；Gemini 的 query
  参数名是 `key`）。能走请求头就别用 query，Key 会出现在代理/网关日志里；
  该模式只对支持 URL 鉴权的服务有意义（Gemini、部分自定义网关），
  OpenAI / Anthropic 官方接口会以 401 明确失败；
- `body` 值不能含 `;`，custom 的 URL / model / body 不能含 `|`（无转义机制）；
- `Pass` 字段单独承载 API Key；Key 为空时沿用上次保存值；
- 空 spec 使用上次保存的 spec，首次默认 `ollama:qwen3:4b`。

### 5.1 预设表

| preset | base URL | 默认模型 | 协议 | 鉴权 |
| --- | --- | --- | --- | --- |
| `openai` | `https://api.openai.com/v1` | `gpt-5.6-terra` | OpenAI 兼容 | Bearer |
| `deepseek` | `https://api.deepseek.com/v1` | `deepseek-v4-flash` | OpenAI 兼容（关闭思考） | Bearer |
| `moonshot` | `https://api.moonshot.cn/v1` | `kimi-k3.1-pro` | OpenAI 兼容 | Bearer |
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4` | `glm-5.3` | OpenAI 兼容 | Bearer |
| `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-flash` | OpenAI 兼容（关闭思考） | Bearer |
| `siliconflow` | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V4-Flash` | OpenAI 兼容（关闭思考） | Bearer |
| `openrouter` | `https://openrouter.ai/api/v1` | `openai/gpt-5.6-terra` | OpenAI 兼容 | Bearer |
| `groq` | `https://api.groq.com/openai/v1` | `openai/gpt-oss-120b` | OpenAI 兼容 | Bearer |
| `xai` | `https://api.x.ai/v1` | `grok-4.20` | OpenAI 兼容 | Bearer |
| `mistral` | `https://api.mistral.ai/v1` | `mistral-small-latest` | OpenAI 兼容 | Bearer |
| `together` | `https://api.together.ai/v1` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` | OpenAI 兼容 | Bearer |
| `lmstudio` | `http://127.0.0.1:1234/v1` | 服务端默认模型 | OpenAI 兼容 | 无 |
| `vllm` | `http://127.0.0.1:8000/v1` | 服务端默认模型 | OpenAI 兼容 | 无 |
| `ollama` | `http://127.0.0.1:11434` | `qwen3:4b` | Ollama 原生 | 无 |
| `anthropic` | `https://api.anthropic.com` | `claude-sonnet-4-6` | Anthropic | `x-api-key` |
| `gemini` | `https://generativelanguage.googleapis.com` | `gemini-3.5-flash` | Gemini | `x-goog-api-key` 头 |
| `custom` | 用户自填完整请求地址 | 用户自填 | 默认 OpenAI 兼容 | Bearer |

> 模型名是 2026-11 核对时的示例值，服务商随时会改；登录自检失败会列出该 Key
> 可用模型，按提示改 `preset:model` 即可。

### 5.2 custom 选项

| opt | 含义 | 默认 |
| --- | --- | --- |
| `path` | 响应中的译文 JSON 路径，支持 `a.b[0].c` | 按协议默认 |
| `auth` | `bearer` / `x-api-key` / `query` / `none` | `bearer` |
| `keyname` | 鉴权头名或 query 参数名 | `Authorization` / `x-api-key` / `key` |
| `body` | 请求体模板，占位符 `{{prompt}}` `{{text}}` `{{model}}` `{{src}}` `{{dst}}` | OpenAI 兼容体 |
| `temp` | 采样温度 | `0.2` |
| `max_tokens` | 输出上限（默认不发送，避免推理模型 400） | 不发送 |
| `minimal` | `1` = 强制最小请求体（只带 model/messages/stream） | `0` |
| `version` | Anthropic `anthropic-version` 头 | `2023-06-01` |
| `probe` | 登录自检：`models` 或 `none` | `custom` 默认 `none`，其余 `models` |
| `debug` | `1` 打开控制台诊断日志（Key 脱敏） | `0` |

示例：

```
deepseek:deepseek-v4-flash
openai:gpt-5.6-terra|temp=0.1
gemini:gemini-3.5-flash
custom|https://my-gateway/v1/chat/completions|my-model|path=result.translation;auth=x-api-key;keyname=X-Key
```

## 6. 适配器实现

### 6.1 请求

- **openai**：`POST {base}/chat/completions`，头 `Content-Type: application/json`、
  `Authorization: Bearer <key>`；体
  `{model, messages:[{role:"user",content:prompt}], stream:false, temperature}`。
  `model`、`temperature` 可省略；`max_completion_tokens` 仅在 `max_tokens=` 显式给出时发送。
  DeepSeek / Qwen / SiliconFlow 预设会追加关闭思考的厂商字段
  （`{"thinking":{"type":"disabled"}}`、`"enable_thinking":false`）。
- **anthropic**：`POST {base}/v1/messages`，头 `x-api-key`、
  `anthropic-version: <version>`；体
  `{model, max_tokens, messages:[{role:"user",content:prompt}]}`（`max_tokens` 必填，默认 1024）。
- **gemini**：`POST {base}/v1beta/models/{model}:generateContent`，头
  `x-goog-api-key: <key>`（不把 Key 放 URL）；体
  `{contents:[{parts:[{text:prompt}]}], generationConfig:{temperature, thinkingConfig:{thinkingBudget:0}}}`。
- **ollama**：`POST {base}/api/chat`；体
  `{model, messages:[{role:"user",content:prompt}], stream:false, think:false, options:{temperature}}`。
- **custom**：`body` 模板优先；否则按 OpenAI 兼容体。

JSON 字符串一律经 `JsonEscape`：先剔除 JSON 不允许的 C0 控制字符
（`\t`/`\n`/`\r` 除外，用 `HostRegExpRemove` 循环删除），再转义
`\`、`"`、`\n`、`\r`、`\t`（用自实现 `StrReplaceAll`，不依赖 `replace`
的原地语义）。

### 6.2 响应解析

统一走 `ExtractByPath(root, path)`：

1. 按 `.` 切分路径，`name[index]` 支持 **0-9** 单层下标；
2. 终值若为字符串直接返回；
3. 若为数组，逐项取 `text` / `content` 字符串并拼接；对象的 `thought=true`、
   `type=thinking|redacted_thinking|reasoning` 块被跳过；
4. 若为对象，取 `text` 或 `content`。

默认路径：`openai=choices[0].message.content`、`anthropic=content`、
`gemini=candidates[0].content.parts`、`ollama=message.content`。

### 6.3 清洗

去首尾空白 → 去 ``` 代码围栏 → 去常见前缀（`翻译：`、`Translation:` 等，
最多 3 轮）→ 去整体包裹的成对引号 → 规范化换行 → 目标语言为
`ar/he/fa/ur` 时前置 `U+202B`。

## 7. 错误处理与降级

| 场景 | 行为 |
| --- | --- |
| HTTP 句柄为 0 | 返回空串，`debug=1` 时打印"网络不可达" |
| 401 / 402 / 403 | 登录期返回对应中文提示；运行期静默 |
| 404 / 405（登录自检） | 视为该服务未实现模型列表，跳过校验并放行登录 |
| 429 / 5xx | 重试 1 次（`HostSleep(400)`），仍失败则静默 |
| 400 且提示参数不支持 | 用最小体（仅 model + messages + stream:false）重试 1 次；成功后本次会话固定用最小体 |
| 200 但译文为空 | 用最小体重试 1 次（常见于思考内容占满预算）；若最小体与当前体相同则跳过 |
| JSON 解析失败 / 译文为空 | 静默返回空串 |
| 连续失败 ≥ 5 次 | 清空上下文，避免污染后续翻译 |
| 登录自检失败 | 置运行期"已登出"状态，`Translate` 直接返回空串，避免用未验证配置逐行请求 |

超时：每次请求前 `HostIncTimeOut(20000)`；重试最多让单行发出 3 次请求。
Ollama（本机）首次加载模型可能较慢，可先手动 `ollama run` 预热。

## 8. 性能与成本

- **上下文窗口**：保留最近 4 句原文，作为"仅供参考、禁止翻译"的语境块；
- **缓存**：最近 64 条（原文 → 译文）线性缓存，命中直接返回，避免重复计费；
- **暂停重置**：距上次翻译超过 120 秒清空上下文与缓存；
- **提示词**：中文指令 + 4 条硬规则，单条字幕通常 < 120 输入 token；
- **单次延迟**：本机小模型 200-800 ms；云端 `gpt-5.6` / `gemini-3.5-flash` 级 300-1200 ms；
  推理模型 2-30 s。这是同步 HTTP 方案的物理下限，文档中如实说明。

## 9. 验证计划

1. **静态检查**（`tools/check_as.py`）：括号/花括号配平、14 个入口点齐全、
   三张语言表长度一致且无重复、所有 `Host*` 调用都在二进制签名表内；
2. **契约测试**（`tests/`，Python 参考实现 + mock 服务）：校验 spec 解析、
   四种协议的 URL/头/体构造、响应路径解析、错误码映射；说明见
   `docs/testing/CONTRACT.md`；
3. **独立审查**（内部记录，未随包发布）：逐 API 对照二进制签名与官方在用插件，
   覆盖语法、逻辑、安全、兼容性、行为回归；
4. **实机验证**（需用户配合，因会写入 PotPlayer 安装目录）：
   复制 `.as` → 重启 PotPlayer → 选择 `AnyTranslate` → 登录 → 播放带字幕视频
   观察译文与 `debug=1` 控制台输出。最高优先验证项：`HostGetStatusHTTP`
   返回值、`HostGetContentHTTP` 读取顺序、`HostSaveString` 跨重启持久化。

## 10. 非目标

- 不做流式输出、不内置 ASR（语音识别由 PotPlayer 的 Whisper 引擎负责）；
- 不做术语库、批量翻译整部字幕文件、多语言同时输出；
- 不自动上传/同步配置，Key 仅保存在 PotPlayer 本地；
- 不保证对非 JSON 响应协议的站点（如 Google 网页接口）兼容，这类请用官方插件。

## 11. 已知残余风险

1. AngelScript 无法在本机执行，语法/语义风险依靠官方插件同款写法 + 静态检查；
2. `HostGetStatusHTTP` 已在本机 26.10.21.0 构建中确认存在，但官方脚本无使用先例
   （api.txt 与二进制签名有），必须实机验证其返回值；`HostGetContentHTTP` 的
   读取顺序与编码同理；
3. `HostSaveString` 在 api.txt 中写作 "temporary storage"，跨重启持久化需实机确认；
4. 用户把 spec 写错时的报错质量取决于 `ServerLogin` 的提示覆盖面；
5. 若 PotPlayer 未来改变登录框行为，spec 语法需随之调整；
6. 自定义 API 只支持 JSON 请求/响应；表单编码类接口（如 DeepL 表单版）
   不在支持范围，请使用官方插件；
7. `body` 值不能含 `;`，custom 的 URL / model / body 不能含 `|`，无转义机制。

## 12. 文案与命名约定

服务商显示名、场景标签（如 `Ollama（本机）`）、术语（API Key、配置串、请求地址）、
标点与中英空格规则统一写在 `docs/STYLE.md`；`python tools/check_style.py` 做机械检查。
