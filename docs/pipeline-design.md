# 上下文感知翻译流水线设计

状态：Phase 1（Prompt 拆分）+ Phase 2（`split`）+ Phase 3（`turns`，默认关闭）已实现；Phase 4 的UTF-8 字节预算、历史过滤和 glossary 已实现基础版。默认 `contextmode=split`；提示词结构参考 Index-Translate / Hy-MT2 官方模板。

## 1. 目标

把当前“规则 + 历史 + 当前句拼成一条 user 文本”的单轮调用，演进为职责清晰的翻译流水线：

```text
Context Manager
      ↓
Prompt Builder / Protocol Adapter
      ↓
Translator（单次模型调用）
      ↓
Quality Gate / Repair（必要时一次）
      ↓
Cache / History
```

目标：

- 给上下文和待翻译文本建立真实的消息边界；
- 降低模型复述历史、串入上一句译文的概率；
- 改善人名/术语一致性；
- 保持实时字幕的延迟可控；
- 保持 `block` 模式作为兼容回退，不破坏现有 provider / custom body 模板。

非目标：

- 不引入 planner、工具调用、多 agent 辩论或自主循环；
- 不要求插件读取完整字幕文件或做全片预翻译；
- 不改变 PotPlayer 的宿主目标语言缓存行为（已有 `dst` 覆盖项）。

## 2. 当前实现的边界

`Translate` 当前按以下顺序工作：

1. 非对白过滤；
2. 目标语言解析，支持 `dst` 覆盖；
3. 上下文 key 变化时清缓存；
4. `CacheFind(raw)`；
5. `BuildPrompt`：固定规则 + 风格 + 目标语言规则 + 最近 4 组历史 + 当前句；
6. `BuildBody`：按 OpenAI / Anthropic / Gemini / Ollama / custom 拼请求；
7. 清洗、字体转换、质量校验、最多一次重试；
8. 成功时写缓存和历史。

主要问题：

- 规则、历史值和当前句属于同一条 user 文本，模型没有强制的“参考区”边界；
- 历史块使用 `- 原文 / 译文` 形式，模型可能整体复述；
- 历史过滤只有固定窗口，没有UTF-8 字节预算、重复句过滤或术语表；
- 质量修复是通用 strict prompt，没有按错误类型分流。

## 3. 目标组件

### 3.1 Context Manager

职责：

- 维护最近 N 组成功译文；
- 过滤重复行、纯语气词、低信息量片段（保留正常短对白）；
- 限制上下文UTF-8 字节预算，先丢最旧；
- 暂停超过阈值时清空；
- （可选）维护用户提供的术语表；
- 失败/被拒绝的译文不进入历史。

数据：

```text
g_history_src[]
g_history_dst[]
g_last_tick
g_context_limit
g_glossary[]
```

现有 `g_history_*` 保留，新增UTF-8 字节预算和过滤策略，避免大改状态结构。

### 3.2 Prompt Builder

拆成三个可独立测试的文本：

```text
SystemPrompt  固定规则、风格、目标语言、术语表
ContextText   最近台词 / 结构化上下文
UserText      当前待翻译字幕
```

对应函数建议：

```text
string BuildSystemPrompt(const string &in dstName, const string &in dstLabel)
string BuildContextText()
string BuildUserText(const string &in text)
```

`block` 模式用 `ContextText + UserText` 拼回单条提示词，作为兼容回退；默认使用 `split`，不按模型路由。

### 3.3 Protocol Adapter

不同协议的系统角色能力不同：

| 协议 | system 位置 | 历史承载 |
| --- | --- | --- |
| OpenAI 兼容 | `messages[0].role=system` | 前几轮 user/assistant，或 user 内结构化块 |
| Anthropic | 顶层 `system` | messages 的 user/assistant 轮次 |
| Gemini | `systemInstruction` | contents 的 user/model 轮次 |
| Ollama | messages 的 `system` | 前几轮 user/assistant |
| custom | 由模板决定 | 默认只用 block，不强制角色 |

建议保留现有 `BuildBody` 作为 `block` 包装，新增：

```text
string BuildBodyEx(systemText, contextText, userText, text, srcName, dstName,
                   minimal, mode)
```

`custom` 没有 `body` 模板时可以复用 OpenAI system；有模板时仍由用户控制，默认不注入角色。

### 3.4 质量门与修复

质量错误分类：

```text
empty
echo
wrong_script
traditional / simplified
history_leak
too_long
```

修复策略：

| 错误 | 处理 |
| --- | --- |
| `history_leak` | 使用无历史上下文重试 |
| `traditional` / `simplified` | 优先本地确定性字形转换 |
| `echo` | 强化“只翻译当前句”，无历史重试 |
| `too_long` | 使用紧凑提示词重试 |
| `empty` | 使用 minimal body 重试 |
| 网络/4xx/5xx | 沿用现有 deadline 和降级策略 |

无论哪种模式，历史泄漏检测和最终静默失败都保留。

## 4. 配置设计

新增：

```text
contextitems=0..32
contextmode=block|split|turns
glossary=Name=译名,Name2=译名2
```

- `block`：兼容回退，单条 user；
- `split`：固定规则进 system，上下文和当前句留在 user；
- `turns`：固定规则进 system，历史作为独立轮次，当前句最后一条 user；
- `glossary`：可选，限制条目数和总长度，值内不允许 `;`/`|`；
- 现有 `contextitems=0..32` 控制历史组数。

兼容策略：

- 不写 `contextmode` 按 `split`；
- custom body 模板默认保持 block；
- 提示词参考 Index-Translate 的 instTrans 分段方式：`【硬性要求】`、`【源文】`、`【约束要求】`、`【术语对照】 A→B`；
- 同时参考 Hy-MT2 的 `【背景信息】` + `【待翻译文本】` 结构，历史作为背景而不是当前句；
- `contextmode=turns` 仅在协议支持角色轮次时启用，否则自动回退 `split` 或 `block`；
- 不能用角色模式时记录 debug 日志，不报错。

## 5. 迁移阶段

### Phase 0：基线

- 保存当前 532 条唯一字幕、234 项测试的结果；
- 记录历史泄漏率、目标字形错误、延迟、token；
- 不改变输出。

### Phase 1：Prompt 拆分，行为不变

- 引入 `BuildSystemPrompt / BuildContextText / BuildUserText`；
- `block` 模式输出与当前完全一致；
- 用现有测试锁定 block 回归。

验收：所有测试通过，block 输出逐字不变。

### Phase 2：`split` 模式

- OpenAI / Ollama：`system` + `user`；
- Anthropic：顶层 `system` + `messages`；
- Gemini：`systemInstruction` + `contents`；
- custom：保持 block；
- 默认 `split`；`block` / `turns` 可显式切换；不按模型路由。

验收：

- mock server 校验请求结构；
- 532 条字幕历史泄漏不高于 block；
- 延迟和 token 有记录。

### Phase 3：`turns` 模式

- 历史按 user/assistant 轮次发送；
- 只发送成功、去重后的历史；
- 限制轮数和总字符；
- 失败自动回退 `split`。

验收：

- 对比 block / split / turns 三种模式；
- 如果 turns 导致模型对话化或延迟明显，保持 opt-in 或删除。

### Phase 4：上下文 Manager 与 glossary

- 重复句/低信息量过滤；
- UTF-8 字节预算；
- 用户术语表；
- 缓存 key 加入 provider/model/target/style/glossary；
- 失败句不进入历史。

### Phase 5：修复分流与可观测性

- 按质量错误选择修复策略；
- debug 日志增加 mode、history 数、上下文字符数、修复类型；
- 评测脚本输出每条字幕的模式、延迟、错误类型。

## 6. 测试与验收

### 单元/契约

- 现有 234 项测试；
- 新增每个协议的 `block/split/turns` 请求体断言；
- system 内容不包含当前字幕；
- custom body 模板不受影响；
- 无 `contextmode` 时输出与基线一致；
- 历史过滤/UTF-8 字节预算/glossary 的边界测试。

### 真实字幕回归

使用：

```text
vincent-film/dist/*.srt   # 繁中 → 简中
ipx-485.srt                                   # 日文 → 简中
```

指标：

- 历史泄漏率；
- 回显率；
- 目标字形错误率；
- 空输出率；
- p50/p95 延迟；
- token 增量；
- 人名/术语一致性抽检。

验收原则：

- block 模式无回归；
- 新模式的最终历史泄漏必须为 0；
- 延迟和 token 增量在可接受范围内，否则保留 opt-in；
- 不为了“更像 agent”牺牲实时性。

## 7. 风险

| 风险 | 处理 |
| --- | --- |
| 角色分离后模型变得对话化 | 强 system 约束 + 质量门 + block 回退 |
| 小模型不遵循 system | 保留历史泄漏重试，不以角色分离替代校验 |
| 不同服务 system 支持不一致 | 协议能力表，未知 provider 用 block |
| token 增加、云端成本上升 | UTF-8 字节预算、历史去重、turns 仅 opt-in |
| custom body 模板被破坏 | 默认不注入角色，保留模板优先 |
| 目标语言宿主缓存仍存在 | 继续支持 `dst=`，不纳入本流水线 |

## 8. 推荐决策

先实现 Phase 1 + Phase 2：

1. 抽 Prompt 三段文本，block 输出不变；
2. 对 OpenAI/Anthropic/Gemini/Ollama 增加 `split`；
3. 用 532 条字幕做 A/B；
4. 数据证明 split 更好后，再讨论是否让 `turns` 成为默认。

不建议直接进入多 agent/多轮 critic 架构。翻译任务的目标明确，确定性上下文管理和结构化消息的收益，通常高于增加 LLM 轮次。
