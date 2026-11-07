# Changelog

## 0.1.0 - 2026-11-07

首个公开版本：一个单文件 PotPlayer 字幕翻译插件，支持多协议 LLM / 翻译 API。

### 新增

- 协议适配器：OpenAI 兼容、Anthropic Messages、Gemini generateContent、Ollama 原生、自定义 JSON。
- 16 个服务商预设 + `custom|` 自定义接口语法（body 模板、JSON 路径、鉴权方式可配）。
- 登录自检：按协议探测模型列表，校验 Key 与模型名，失败返回中文可操作提示。
- 错误分类：401/402/403/404/413/422/429/5xx 分别提示。
- 自动降级：400 时改用最小请求体并记忆；200 但译文为空时重试一次。
- 诊断模式：`debug=1` 打开脚本控制台，输出请求/响应摘要与单次耗时（Key 脱敏）。
- 82 种语言的中文或母语名标签，目标语言映射为提示词中的语言名。
- 译文缓存（最近 64 条）与暂停 2 分钟自动重置上下文。
- 关闭思考模式：DeepSeek、Qwen/DashScope、SiliconFlow 预设自动追加对应参数；Gemini 设置 `thinkingBudget: 0`。
- 响应解析兼容 `content` 为数组、Anthropic 文本块、Gemini `parts`、思考块过滤。
- 品牌图标：狐狸吉祥物（机敏、适应力强），16-256 px 多尺寸 ICO + 512px PNG 预览。

### 安全与健壮性

- 登录框与诊断日志均不展示明文 Key；`SafeUrl` 同时脱敏原始与 URL 编码后的 Key。
- 登录自检失败会置"已登出"状态，运行期不再用未验证配置逐行请求。
- 重试前比较请求体，避免重复发送完全相同的最小体；单行最多 3 次请求。
- JSON 转义自实现，剔除 C0 控制字符；请求统一使用 `NoCookie=true`。
- 登录框短 Key（<16 位）只显示 `****`。

### 验证

- `tools/check_as.py` 静态检查通过（括号配平、入口点、语言表/预设表长度、13 个 Host API 签名核对）。
- `tests/` 契约测试 208 用例全部通过（Python 参考实现 + 本机 mock 服务）；Windows PowerShell 5.1 与 PowerShell 7 均验证可跑。
- 独立代码审查：P0 = 0，P1 全部修复；`HostGetStatusHTTP` 等宿主行为列为实机必验项。

### 已知限制

- 同步 HTTP，无流式输出；自定义接口仅支持 JSON。
- 模型名会随服务商更新，登录自检会列出可用模型，按提示改 `preset:model` 即可。
