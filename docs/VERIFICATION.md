# 验证记录（2026-11-07）

本文件记录 AnyTranslate v0.1.0 在交付前的验证证据、复跑命令与未覆盖范围。

## 1. 环境

| 项 | 值 |
| --- | --- |
| PotPlayer | 26.10.21.0（`C:\Program Files\DAUM\PotPlayer`） |
| 系统 | Windows，x64 |
| Python（测试用） | 3.12.14（本次验证环境；脚本自动检测 PATH 中的 `python`，可用 `-Python` 覆盖） |
| PowerShell | 7.6.9 与 Windows PowerShell 5.1 均验证 |

## 2. 验证结果

### 2.1 静态检查（`tools/check_as.py`）

```text
L_CODE=82  L_LABEL=82  L_PROMPT=82
P_BASE=17  P_MODEL=17  P_PROTO=17  P_AUTH=17  P_KEYNAME=17  P_EXTRA=17
Host API used: 13; documented: 99
functions defined: 62
OK: static checks passed
```

覆盖：括号/花括号配平、14 个入口点齐全、三张语言表长度一致且无重复、
6 张预设表与 `P_ID` 等长、`Host*` 调用全部存在于 `Extension\api.txt`、
无重复函数定义。

### 2.2 契约测试（`tests/`）

```text
pwsh -NoProfile -File tests/run_tests.ps1
→ py_compile OK；独立 mock 冒烟 OK（problems=0）
→ Ran 208 tests in 1.8s / OK
→ 通过率 100%，mock 冒烟通过，结果 PASS
```

覆盖：17 个 spec 形式（16 预设 + custom）、四种协议 URL/头/体、
登录自检（`/models`、`/api/tags`、`/v1/models`、`/v1beta/models`）、
JSON 路径与 thinking 过滤、错误码映射、JSON 转义与 C0 控制字符、
`SafeUrl` 编码/原文双重脱敏、`MaskKey` 边界、`auth=query` 归一化、
E2E 真实 HTTP（mock）。契约细节与边界决策见 `docs/testing/CONTRACT.md`。

> 该层验证的是 Python 参考实现（`tests/ref_impl.py`）与 `.as` 的契约镜像，
> 不等于 AngelScript 运行时证明。

### 2.3 独立代码审查

- 初查：P0 = 0，P1 = 3，P2 = 18。
- 修复复核：3 项 P1 全部确认修复；P0 仍为 0；新增 7 条 P2，随后全部收尾。
- 审查覆盖：AngelScript 语法/语义（含 `&in`/`&out`、`JsonValue`、前向引用、
  `MakeLower` 等返回值语义）、逻辑、安全、兼容性、行为回归、可维护性；
  逐项对照官方在用脚本先例。

### 2.4 宿主 API 真实性

`docs/api-signatures.txt` 由本机 `PotPlayer64.dll` 二进制提取，共 104 条签名。
插件使用的 13 个 API 全部命中，且与 `Extension\api.txt` 一致：

`HostOpenHTTP`、`HostGetContentHTTP`、`HostGetStatusHTTP`、`HostCloseHTTP`、
`HostIncTimeOut`、`HostGetTickCount`、`HostLoadString`、`HostSaveString`、
`HostPrintUTF8`、`HostOpenConsole`、`HostRegExpRemove`、`HostUrlEncode`、
`HostUrlGetString`（备用）。

> `HostGetStatusHTTP` 在官方随扩展包分发的 17 个脚本中无使用先例（仅
> api.txt 与二进制签名），是最高优先级的实机验证项。

### 2.5 文档样式检查（`tools/check_style.py`）

```text
OK: 文档样式检查通过
```

覆盖：服务商命名（统一写成“Ollama（本机）”这类“名称（部署方式）”的形式）、
术语（“本机服务”“请求地址”等）、中文与英文/数字之间的空格、行尾空格。
约定见 `docs/STYLE.md`。

## 3. 未验证范围（必须实机）

1. `HostGetStatusHTTP` 的返回值语义（是否与真实 HTTP 状态码一致）。
2. `HostGetContentHTTP` 的读取顺序、编码、gzip/重定向行为。
3. `HostSaveString` 是否跨 PotPlayer 重启持久化（api.txt 写作 temporary storage）。
4. `HostIncTimeOut(20000)` 在慢请求下的实际效果。
5. `HostRegExpRemove` 对 `[\x00-\x08…]` 的 std::regex 支持。
6. `&in` 参数写回（`SrcLang/DstLang = "UTF8"`）是否被宿主读取。
7. `GetVersion "0.1.0"`、`GetTitle` 多语言标签的菜单显示。
8. 各真实服务商的 Key/模型名与真实网络环境（含代理）下的端到端翻译。

实机验证顺序：安装 → 重启 PotPlayer → 选择 AnyTranslate → 用错误 Key 登录
（期望中文 401）→ 用正确 Key 登录（期望 200 ok）→ 播放 3 条以上字幕 →
`debug=1` 观察状态码/耗时 → 用本机运行的 `tests/mock_server.py` + custom spec
验证状态码与响应体解析。

## 4. 交付物

| 文件 | 说明 |
| --- | --- |
| `plugin/SubtitleTranslate - AnyTranslate.as` | 插件（单文件，SHA256 见 Release 说明） |
| `plugin/SubtitleTranslate - AnyTranslate.ico` | 图标（16-256 px 多尺寸） |
| `docs/assets/logo.png` | 图标 512px PNG 预览 |
| `install.ps1` | 安装/卸载脚本（需管理员权限） |
| `README.md` | 安装、配置、故障排查 |
| `docs/DESIGN.md` | 设计契约 |
| `docs/STYLE.md` | 文案与命名约定 |
| `docs/testing/CONTRACT.md` | 契约测试说明与边界决策 |
| `docs/testing/ANGELSCRIPT-VALIDATION.md` | AngelScript 校验工具链调研 |
| `docs/providers.md` | 各服务 HTTP 契约 |
| `tests/` | mock 服务 + Python 参考实现 + 208 用例 |
| `tools/check_as.py` / `tools/check_style.py` | 静态检查 / 样式检查 |

## 5. 复跑命令

```powershell
cd any-translate
python tools/check_as.py
python tools/check_style.py
powershell -ExecutionPolicy Bypass -File tests\run_tests.ps1   # 或 pwsh -File
python tests/mock_server.py --port 18080                       # 独立 mock
```

图标为位图资产：`docs/assets/logo.png`（512px 预览）与 `plugin/SubtitleTranslate - AnyTranslate.ico`（16-256 px 九档）。
