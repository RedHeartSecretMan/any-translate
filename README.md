<p align="center"><img src="docs/assets/logo.png" width="132" alt="any-translate logo"></p>

<h1 align="center">any-translate</h1>

<p align="center"><b>PotPlayer 实时字幕翻译插件：一个 <code>.as</code> 文件，接入任意 LLM / JSON 翻译 API。</b></p>

<p align="center">
  <a href="CHANGELOG.md"><img alt="Version 0.1.0" src="https://img.shields.io/badge/version-0.1.0-f59e0b.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <img alt="PotPlayer 26.10+" src="https://img.shields.io/badge/PotPlayer-26.10%2B-2f6f9f.svg">
  <img alt="5 protocols" src="https://img.shields.io/badge/protocols-5-14b8a6.svg">
  <a href="https://github.com/RedHeartSecretMan/any-translate/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/RedHeartSecretMan/any-translate/actions/workflows/ci.yml/badge.svg"></a>
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#配置语法">配置语法</a> ·
  <a href="#服务商预设">服务商预设</a> ·
  <a href="#故障排查">故障排查</a> ·
  <a href="#文档">文档</a> ·
  <a href="CHANGELOG.md">更新日志</a>
</p>

---

any-translate 是 [PotPlayer](https://potplayer.daum.net/) 的实时字幕翻译插件：把一条外文字幕交给任意 LLM 或翻译 API，返回一条目标语言字幕。整个插件只有一个 AngelScript 文件，无需安装器，也不用改源码换服务商。

内置 OpenAI 兼容、Anthropic Messages、Gemini generateContent、Ollama 和自定义 JSON 五种协议；OpenAI、DeepSeek、Kimi、智谱、通义千问、硅基流动、OpenRouter、Groq、xAI、Mistral、Together、vLLM、SGLang、LM Studio、Ollama 等 17 个预设开箱即用，one-api/new-api 等网关和其他接口用一行 `custom|...` 配置接入。

## 为什么是 any-translate

- **一个脚本覆盖多协议。** 五种请求/响应适配器共用同一套配置语法，换协议不改代码。
- **配置只占一行。** 登录框的"用户"字段用 `preset:model` 或 `custom|url|model|opts` 表达，不用编辑文件。
- **失败要说人话。** 登录时自检 Key 与模型名，按 401/402/404/413/422/429/5xx 给出中文提示，并列出可用模型。
- **实时场景优先。** 上下文窗口、译文缓存、自动降级、同步 HTTP，都是为 PotPlayer 的单次字幕调用设计的。
- **按场景选风格。** `style=movie/tv/anime/doc/tech/formal/casual` 给不同题材不同的提示词规则；`contextitems=0..32` 控制前文原文+译文的参考量，默认 16 组。
- **隐私默认。** 不做任何上报，只请求你填写的 URL；Key 只保存在本机。

## 特性

| 能力 | 说明 |
| --- | --- |
| 多协议 | OpenAI 兼容、Anthropic Messages、Gemini generateContent、Ollama、自定义 JSON |
| 17 个预设 + custom | 换服务商/模型只改登录框里的一行配置 |
| 上下文翻译 | 默认保留最近 16 组原文+译文作为语境，`contextitems=0..32` 可调，提升指代、术语与语气一致性 |
| 场景风格 | `style=movie/tv/anime/doc/tech/formal/casual`，按题材切换提示词模板 |
| 译文质量门 | 回显原文、目标文字脚本、繁简不匹配、超长译文会被拦截并重试一次，失败宁可不显示；中文目标会额外拒绝明显日文/韩文 |
| 中文简繁 | 目标简体且原文是中文时直接逐字转换，避免模型保留繁体或改写语义 |
| 实时预算 | 单条字幕默认 6 s 总预算，预算内才继续降级/质量重试；`deadline=2000..20000` 可调；413 会尝试无上下文降级 |
| 非对白过滤 | 纯符号、纯数字、音乐符号行不请求 API，原样返回 |
| 缓存去重 | 相同台词命中缓存（最近 64 条），避免重复请求与计费 |
| 登录自检 | 按协议探测模型列表，校验 Key 与模型名，失败给出可操作提示 |
| 自动降级 | 服务端拒绝 `temperature` / `max_tokens` 时改用最小请求体并记住 |
| 诊断模式 | `debug=1` 查看状态码、长度与耗时摘要；`debug=2` 才输出请求/响应正文 |
| 82 种语言 | 插件返回语言代码，菜单名称由 PotPlayer 本地化显示；提示词映射为双语语言名 |
| 上下文流水线 | 默认 `split`；规则进 system，背景信息/待翻译文本分离；支持 `block`/`turns` 切换 |
| 隐私默认 | 无遥测；Key 由 PotPlayer 的 `HostSaveString` 保存在本机（非加密） |

## 快速开始

### 1. 安装插件

关闭 PotPlayer，把 `plugin/` 下的两个文件复制到：

```text
PotPlayer 安装目录\Extension\Subtitle\Translate\
```

即 `SubtitleTranslate - AnyTranslate.as` 与 `SubtitleTranslate - AnyTranslate.ico`。

也可以运行安装脚本（自动检测安装路径、备份旧文件；安装到 `Program Files` 需要管理员权限）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

只检查目标路径、不写文件：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -DryRun
```

卸载：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Uninstall
```

### 2. 启用实时字幕

重启 PotPlayer，右键画面 → **字幕** → **实时字幕翻译** → **实时字幕设置**，勾选"生成有声字幕（实时）"。然后在同一窗口选择翻译插件 **AnyTranslate**。

### 3. 登录并配置

点击插件旁边的配置/登录按钮：

- **用户** 框填服务与模型，例如 `deepseek:deepseek-v4-flash`；
- **密码** 框填 API Key（本机服务可以留空）；
- 点确定后插件会自检 Key 与模型名，失败会提示原因和可用模型。

| 场景 | 用户框 | 密码框 |
| --- | --- | --- |
| vLLM（本机） | `vllm`（默认使用已加载模型） | 留空 |
| SGLang（本机） | `sglang`（默认使用已加载模型） | 留空 |
| LM Studio（本机） | `lmstudio`（默认使用已加载模型） | 留空 |
| Ollama（本机） | `ollama:qwen3:4b`（必须显式指定模型） | 留空 |
| DeepSeek（云端） | `deepseek:deepseek-v4-flash` | `sk-...` |
| OpenAI（云端） | `openai:gpt-5.6-terra` | `sk-...` |
| Anthropic（云端） | `anthropic:claude-sonnet-4-6` | `sk-ant-...` |
| Google Gemini（云端） | `gemini:gemini-3.5-flash` | AIza... |
| 自定义接口 | `custom\|https://your-gateway/v1/chat/completions\|model-name` | 网关 Key |

模型名只是示例，以服务商当前 `/models` 列表为准；填错时登录会提示可用模型。本机服务默认不猜模型：vLLM/SGLang/LM Studio 可留空使用已加载模型，Ollama 需要显式写 `ollama:<model>`（只写 `ollama` 会在登录时提示缺模型）。

### 模型怎么选

PotPlayer 的翻译插件登录框只有文本输入，没有“服务商/模型”下拉列表：

- `preset` 或 `preset:`：使用预设的默认模型（本机预设默认留空）；
- `preset:model`：显式覆盖为该服务商的任意模型；
- 登录时会按 `probe=models` 拉取服务商的模型列表，但只用于校验和提示，不会自动改写配置；
- 模型不匹配时，错误信息会列出最多 6 个可用示例，复制到冒号后重新登录即可。

因此“自动发现模型、手动选择”在当前宿主 UI 里是**两段式**：先探测看提示，再把选中的模型写进配置串；插件不会静默替你选一个模型。PotPlayer 插件接口没有自定义下拉控件，无法在登录框内直接做“服务商 → 模型”的级联选择。

> 翻译设置里的“测试”按钮在 AnyTranslate **未登录、目标语言未选或请求失败**时会显示具体提示；提示使用 ASCII 英文，避免 PotPlayer 把测试返回值按 ANSI 解码成乱码。正常播放路径仍然静默返回空串，不会把错误写进字幕。Google 等内置引擎无需登录，所以测试会直接出结果。

想按题材调整译文语气，在配置后追加 `|style=anime`、`|style=tech` 等；上下文默认 16 组，可用 `|contextitems=8` 调整。

### 4. 播放验证

播放带字幕的视频，字幕出现后会在几秒内替换为目标语言。首次请求可能较慢（云端模型冷启动或本机模型加载）；想看每次请求的状态码与耗时，给配置追加 `|debug=1`。

## 配置语法

登录框 **用户** 字段：

```text
preset[:model][|opts]                       例：deepseek:deepseek-v4-flash|debug=1
custom|<endpoint_url>|<model>|[opts]        例：custom|https://api.example.com/v1/chat/completions|my-model|path=choices[0].message.content
```

- `preset` 不区分大小写；`model` 只按**第一个** `:` 切分，所以 `ollama:qwen3:4b` 合法。
- 任意 spec 都可以在结尾用 `|` 追加 opts（预设与 custom 都支持）。
- `custom` 的 `endpoint_url` 是完整请求地址，不再追加协议路径。
- `opts` 用 `;` 分隔、`=` 赋值；可用：`path`、`auth`、`keyname`、`body`、`headers`、`temp`、`max_tokens`、`minimal`、`version`、`probe`、`probe_timeout`、`debug`、`style`、`contextitems`、`contextmode`、`contextchars`、`glossary`、`deadline`、`dst`、`think`。
- 未知 key、缺 `=` 或空 key 会在登录时报错，不再静默忽略；拼错配置会直接显示 `未知选项: ...`。
- 旧版 `context=` 已移除，请改为 `contextitems=`；旧配置不会自动迁移，登录会明确报未知选项。
- `body` 值不能含 `;`；custom 的 URL / model / body 不能含 `|`（没有转义机制）。
- `headers` 仅对 custom 生效，格式为 `Header:Value|Header2:Value2`；`|` 分隔多个头，单个 Header 值不能含 `|` 或 `;`。
- `auth=query` 会把 Key 拼进 URL（参数名 `keyname`，默认 `key`）；能走请求头就别用 query，Key 会出现在代理/网关日志里。`auth=query` 只对支持 URL 鉴权的服务有意义（Gemini、部分自定义网关）；OpenAI / Anthropic 官方接口不接受 query 鉴权，会以 401 明确失败。
- 密码框留空时沿用上次保存的 Key；用户框留空时沿用上次保存的 spec。

### 常用选项

| 选项 | 含义 | 默认 |
| --- | --- | --- |
| `path` | 响应里的译文 JSON 路径，支持 `a.b[0].c`（下标仅 0-9） | 按协议默认 |
| `auth` | `bearer` / `x-api-key` / `query` / `none` | `bearer` |
| `keyname` | 鉴权头名，或 query 参数名 | 按 auth 类型取默认值 |
| `body` | 请求体模板，占位符 `{{prompt}}` `{{text}}` `{{model}}` `{{src}}` `{{dst}}`（后两者是语言显示名，不是语言码） | OpenAI 兼容体 |
| `headers` | custom 额外请求头，`Header:Value\|Header2:Value2` | 空 |
| `temp` | 采样温度 | `0.2` |
| `max_tokens` | 输出上限（默认不发送；Anthropic 必填，默认 1024） | 不发送 |
| `minimal` | `1` = 强制最小请求体（custom 带 body 模板时仍优先模板） | `0` |
| `version` | Anthropic `anthropic-version` 头 | `2023-06-01` |
| `probe` | 登录自检 `models` / `none` | 预设 `models`，custom `none` |
| `probe_timeout` | 登录自检超时毫秒，`1000..60000` | `10000` |
| `debug` | `1` = 诊断摘要（不打印字幕内容）；`2` = 额外打印请求/响应内容 | `0` |
| `style` | 翻译风格：`movie` / `tv` / `anime` / `doc` / `tech` / `formal` / `casual` | `movie` |
| `contextitems` | 最近原文+译文组数，`0..32` | `16` |
| `contextmode` | `split` 默认；`block` 单条 user；`turns` 历史独立轮次；custom body 模板回退 block | `split` |
| `contextchars` | 历史上下文预算（UTF-8 字节），`0..4000`；`0` 不限 | `2000` |
| `glossary` | 术语表：内联 `原文=译名,...`，或 `@路径` / `file:路径` 指向本地 UTF-8 词表；最多 32 条 | 空 |
| `deadline` | 单条字幕总预算（毫秒），`2000..20000` | `6000` |
| `dst` | 强制目标语言代码，绕过宿主目标语言缓存；接受 `ko`、`zh-CN` 等 | 跟随界面选择 |
| `think` | `0` 关闭 thinking，`1` 开启；按服务商发送对应字段（DeepSeek/Moonshot/Zhipu 的 `thinking.type`、Qwen/SiliconFlow 的 `enable_thinking`、OpenRouter 的 `reasoning.enabled`、vLLM/SGLang/LM Studio/custom 的 `chat_template_kwargs`、OpenAI/Groq/xAI/Together/Mistral 的 `reasoning_effort`、Ollama 的 `think`、Gemini 的 `thinkingConfig`） | 不发送 |

注意各选项的生效范围：`body`/`headers` 只对 `custom` 生效；`path`/`auth`/`keyname`/`probe` 对任意 spec 生效；`dst` 强制覆盖界面目标语言，适合 PotPlayer 运行中切换目标语言不生效时使用；`contextmode`/`contextchars`/`glossary` 只影响上下文流水线，默认 `split`，`custom` 带 body 模板时回退 block；`think` 按服务商映射，显式设置时会覆盖预设自带的 thinking 字段，若某服务拒绝该字段请删掉它或用 `body` 模板；`version` 只对 Anthropic 请求头生效；`probe=models` 对预设生效；`custom` 显式写 `probe=models` 时会从 `.../chat/completions` 派生 `.../models`，端点不支持时 404/405 会放行；`probe_timeout` 只影响登录自检。`headers` 仅对 custom 生效。

提示词采用官方模板的分段方式：任务与硬性要求放在 system；历史放进 `【背景信息】`；当前句放进 `【待翻译文本】`；术语使用 `A→B` 的 `【术语对照】`。这样既保留影视字幕规则，又避免把所有内容混成一大段文本。

### 本地术语表文件

`glossary` 除内联写法外，还支持本地 UTF-8 文件：

```text
glossary=@C:\Users\WangHao\Documents\any-translate\glossary.txt
glossary=file:C:\Users\WangHao\Documents\any-translate\glossary.txt
```

文件每行一个词条，支持以下分隔符：

```text
# 注释行
安妮=Annie
魔法 => magic
咒语 -> spell
魔杖 → wand
霍格沃茨 | Hogwarts
Harry	Harry
```

`Harry	Harry` 中间是制表符。

规则：

- 空行和 `#` 开头行忽略；
- 最多读取 32 条，文件最大 64 KB；
- 使用 UTF-8 编码，建议无 BOM；
- 文件在登录/确定配置时读取，修改文件后需重新登录；
- 文件不存在、无法读取或没有有效词条时，登录会返回中文错误；
- 路径不能包含 `;` 或 `|`（它们是配置串分隔符），建议使用绝对路径。

文件内容最终会写入：

```text
【术语对照】
安妮→Annie、魔法→magic
```

### 翻译风格

`style` 只影响提示词，不改变请求协议；默认 `movie`：

| style | 适用题材 | 提示词侧重 |
| --- | --- | --- |
| `movie` | 电影、通用影视 | 自然口语，贴近人物说话方式 |
| `tv` | 电视剧、连续剧 | 前后场景称呼与语气一致 |
| `anime` | 动画、番剧 | 保留语气词与角色口吻，日式专名统一 |
| `doc` | 纪录片 | 正式书面，术语使用通用译名 |
| `tech` | 技术、教程 | 术语准确，缩写保留原文 |
| `formal` | 正式场合、商务 | 敬语、完整句，避免俚语 |
| `casual` | 日常、口语内容 | 短句、生活化，保留俚语语气 |

`contextitems` 控制送给模型的最近原文+译文组数（0..32，默认 16）；设为 `0` 可关闭上下文。示例：

```text
deepseek:deepseek-v4-flash|style=anime;contextitems=8;deadline=5000
```

`deadline` 是单条字幕的总预算（毫秒），默认 6000。预算用完后不再发起 400 降级、空响应重试、429/5xx 重试或质量重试；慢模型/推理模型可调高到 20000。

风格/上下文变化会自动清空当前上下文与缓存，避免把旧风格的译文当成参考。

### 自定义接口例子

LibreTranslate（自建；占位符是语言显示名，不是语言码，下面示例固定英译中，其他语言请改 body 里的 `source`/`target`）：

```text
custom|http://127.0.0.1:5000/translate|any|body={"q":"{{text}}","source":"en","target":"zh","format":"text"};path=translatedText;auth=none
```

Azure OpenAI（Key 头名是 `api-key`，部署名在 URL 里）：

```text
custom|https://YOUR.openai.azure.com/openai/deployments/DEPLOY/chat/completions?api-version=2024-10-21|any|auth=x-api-key;keyname=api-key
```

需要额外请求头时：

```text
custom|https://example.com/v1/chat/completions|my-model|auth=none;headers=X-Client:AnyTranslate|OpenAI-Beta:assistants=v2
```

自定义 OpenAI 兼容网关（有非标准响应结构时）：

```text
custom|https://my-gateway/v1/chat/completions|my-model|path=result.translation;auth=bearer
```

## 服务商预设

| preset | 协议 | 默认模型 | 备注 |
| --- | --- | --- | --- |
| `vllm` | OpenAI 兼容 | 服务端默认模型 | 无鉴权，可留空 |
| `sglang` | OpenAI 兼容 | 服务端默认模型 | 无鉴权，可留空 |
| `lmstudio` | OpenAI 兼容 | 服务端默认模型 | 无鉴权，可留空 |
| `ollama` | Ollama | 留空（需显式指定） | 无鉴权，`think:false` |
| `openai` | OpenAI 兼容 | `gpt-5.6-terra` | 推理模型自动降级 |
| `deepseek` | OpenAI 兼容 | `deepseek-v4-flash` | 自动关闭思考模式 |
| `moonshot` | OpenAI 兼容 | `kimi-k3.1-pro` | |
| `zhipu` | OpenAI 兼容 | `glm-5.3` | 路径无 `/v1` |
| `qwen` | OpenAI 兼容 | `qwen-flash` | DashScope 兼容模式，自动关闭思考 |
| `siliconflow` | OpenAI 兼容 | `deepseek-ai/DeepSeek-V4-Flash` | 自动关闭思考 |
| `openrouter` | OpenAI 兼容 | `openai/gpt-5.6-terra` | |
| `groq` | OpenAI 兼容 | `openai/gpt-oss-120b` | |
| `xai` | OpenAI 兼容 | `grok-4.7` | |
| `mistral` | OpenAI 兼容 | `mistral-small-latest` | |
| `together` | OpenAI 兼容 | `meta-llama/Llama-3.3-70B-Instruct-Turbo` | |
| `anthropic` | Anthropic | `claude-sonnet-4-6` | `x-api-key` |
| `gemini` | Gemini | `gemini-3.5-flash` | Key 走 `x-goog-api-key` 头 |
| `custom` | 默认 OpenAI 兼容 | 用户自填 | 完整请求地址 |

## 故障排查

| 现象 | 原因与处理 |
| --- | --- |
| 菜单里没有 AnyTranslate | 文件没放对目录，或 PotPlayer 版本过旧（缺少 `HostOpenHTTP` 会导致脚本加载失败）。重启 PotPlayer 再看。 |
| 登录提示 401/403 | Key 错误、没填，或该 Key 没有该模型权限。 |
| 登录提示 402 | 账户余额不足。 |
| 登录提示 404/405 | 一般不会出现：预设服务没有 `/models` 时插件会跳过模型校验。若出现，按提示检查地址。 |
| 登录提示 429 | 限流，稍后再试。 |
| 登录提示"未找到模型" | 按提示列表里的可用模型改 `preset:model`。 |
| 个别字幕没有译文 | 运行期失败是静默的。重新登录看自检结果；或加 `debug=1`（如 `deepseek:deepseek-v4-flash\|debug=1`）后看控制台状态码与耗时。 |
| 登录失败后突然都不翻译了 | 登录自检失败会置"已登出"状态，避免用错误配置逐行请求；重新登录成功即恢复。 |
| `debug=1` 显示 `skip translate` | 目标语言为空/Auto、已登出，或 base URL 为空。先选明确目标语言并重新登录。 |
| 400 但登录正常 | 模型不接受 `temperature`/`max_tokens`；插件会自动降级，若仍失败请确认模型名。 |
| 延迟很高 | 云端推理模型会先思考；换用非推理模型，或确认预设已关闭思考。本机模型首次加载也要时间；可把 `deadline` 调高或先预热。 |
| 译文串味或不连贯 | 默认上下文 16 组；可调 `contextitems=0..32`，暂停超过 2 分钟会自动清空。 |
| 升级后列表目标语言仍是旧名称 | PotPlayer 会缓存插件上次的目标语言名称；在设置里重新选择一次目标语言，或重启 PotPlayer。 |
| 译文过长/回显原文/答错语言 | 插件会拦截并重试一次；仍不合格会留空，`debug=1` 可看到 `validation failed` 原因。 |
| 字幕里出现“- 原文/译文” | 模型复述了上下文块；新版本会判 `history_leak`，自动去掉上下文重试一次。 |

调试示例：`deepseek:deepseek-v4-flash|debug=1`。高级选项（`path`、`body`、`minimal`、`temp` 等）可以加在任意 spec 的 `|` 之后；`custom|...|...|opts` 也支持同样的 opts 语法。

## 性能与成本

- 单条字幕的输入约 100-250 tokens，输出 10-80 tokens。
- 本机小模型 200-800 ms；国内云非推理模型 0.3-1.0 s；海外/代理 0.8-3 s；推理模型 2-30 s。
- 缓存可挡掉重复台词；上下文默认 16 组原文+译文，可用 `contextitems=0..32` 调整（源码上限 `MAX_HISTORY=32`）；切换播放文件会自动清上下文和缓存。
- 单条字幕默认 6 秒总预算；预算内才会继续重试，避免拖住后续字幕。
- 每 1000 条字幕成本量级：¥0.01-0.5，随模型价差很大。

## 隐私与安全

- 插件只向你在配置里填写的 URL 发请求，没有遥测、没有硬编码第三方服务。
- API Key 通过 PotPlayer 的 `HostSaveString` 存在本地（**非加密**）；共享电脑上建议用完 `ServerLogout`（设置里清空）。
- `debug=1` 时打印的 URL 会把 Key（含 URL 编码后的形式）替换成 `****`；请求体里只有字幕和提示词，不含 Key。
- 登录框回显 Key 时，长度不足 16 位只显示 `****`，否则只显示前 4 位与后 4 位。
- 优先用请求头鉴权；`auth=query` 会把 Key 放进 URL，可能被代理/网关日志记录。
- 请求使用 `NoCookie=true`，不会带上 PotPlayer 为同域保存的 Cookie。

## 已知限制

- 同步 HTTP：一次只能翻译一条字幕，没有流式输出（PotPlayer 插件接口只接受一次性返回值）。
- 自定义接口只支持 JSON 请求/响应；表单编码接口（如 DeepL 表单版）请用官方插件。
- `path` 下标只支持单层 0-9，不支持 `[10]` 和多层嵌套下标。
- 不使用线程/timer；单条字幕受 `deadline` 总预算限制（默认 6 s，最大 20 s），慢模型可能来不及返回。
- 82 种语言是常用集，不是完整 ISO 列表；可在源码语言表里扩展。
- `contextitems` 最多 32 组；风格只通过提示词模板切换，不做自动题材识别。
- 不做自动术语提取/整片术语表；需要统一专名时，用 `style` + 上下文维持一致。
- 请求前会剔除 JSON 不允许的 C0 控制字符（`\b`/`\f` 等），不转义保留。
- `body` 值不能含 `;`，custom 的 URL / model / body 不能含 `|`（spec 语法无转义）。
- 插件尚未在全部 PotPlayer 版本上实机验证，兼容性记录见 `docs/verification.md`。

## 文档

| 文档 | 内容 |
| --- | --- |
| [design](docs/design.md) | 设计契约：宿主 API 可行性、配置语法、协议适配、错误处理、性能取舍 |
| [style](docs/style.md) | 文案与命名约定：服务商标签、术语、标点与中英空格 |
| [providers](docs/providers.md) | 各服务商的 HTTP 契约、鉴权头、请求/响应差异 |
| [verification](docs/verification.md) | 验证证据、未覆盖范围、复跑命令、实机验证清单 |
| [contract](docs/testing/contract.md) | 契约测试说明与边界决策 |
| [host-smoke](docs/testing/host-smoke.md) | PotPlayer 宿主冒烟检查清单 |
| [angelscript-validation](docs/testing/angelscript-validation.md) | AngelScript 校验工具链调研 |
| [CHANGELOG](CHANGELOG.md) | 版本变更记录 |

## 开发与验证

AngelScript 无法在本机直接执行，本项目按三层可复跑验证（另有内部独立审查；本机检查需要 Python 3.10 或更高；CI 使用 3.12）：

```powershell
# 1. 静态检查：括号配平、入口点、语言表/预设表长度、Host API 是否真实存在
python -m unittest tests.test_static -v

# 2. 契约测试：py_compile + mock 冒烟 + unittest（234 用例，含静态检查）
powershell -ExecutionPolicy Bypass -File tests\run_tests.ps1
# PATH 中没有 python 时加 -Python <path>

# 3. 实机：复制插件 → 重启 PotPlayer → 登录 → 播放带字幕视频
```

`tests/test_static.py` 默认使用仓库内的 `docs/api-signatures.txt`（从 `PotPlayer64.dll` 提取的 104 条签名）校验 Host API；在装有 PotPlayer 的 Windows 上还会尝试自动探测 `Extension\api.txt`。CI（`.github/workflows/ci.yml`）在 Windows runner 上运行同样的检查。

验证证据与未覆盖范围见 [verification](docs/verification.md)，文案约定见 [style](docs/style.md)，测试布局见 [tests/README.md](tests/README.md)。

## 致谢

- PotPlayer 扩展 API 文档与随包插件提供了 `Host*` 函数和插件文件约定的先例。
- 协议契约参考各服务商公开文档，汇总在 [providers](docs/providers.md)。

## 许可

[MIT](LICENSE) 版权所有 (c) 2026 RedHeartSecretMan
