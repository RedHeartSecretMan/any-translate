# 验证记录（2026-11-07）

本文件记录 any-translate v0.1.0 在交付前的验证证据、复跑命令与未覆盖范围。

## 1. 环境

| 项 | 值 |
| --- | --- |
| PotPlayer | 26.10.21.0（默认安装路径） |
| 系统 | Windows，x64 |
| Python（测试用） | 3.12.14（本次验证环境；脚本自动检测 PATH 中的 `python`，可用 `-Python` 覆盖） |
| PowerShell | 7.6.9 与 Windows PowerShell 5.1 均验证 |

## 2. 验证结果

### 2.1 静态检查（`tests/test_static.py`）

```text
python -m unittest tests.test_static -v
→ test_host_lang_writeback_in_translate ... ok
→ test_language_tables_defined ... ok
→ test_pipeline_contract ... ok
→ test_plugin_contract ... ok
→ test_zh_t2s_mapping_integrity ... ok
→ Ran 5 tests / OK
```

覆盖：括号/花括号配平、14 个入口点齐全、`Translate` 内宿主张量写回、语言表 `L_CODE/L_LABEL/L_PROMPT/LATIN_LANG_CODES` 定义与长度一致且无重复、
`P_*` 预设表与 `P_ID` 等长、本机预设位于表头且模型留空、`STYLE_IDS`/`STYLE_RULES` 等长且无重复、
`GetTitle` 语言标签顺序、`Host*` 调用全部存在于签名列表、保留字 `out` 仅允许出现在
`&out` 参数或字面量中、安装脚本保留 PS5.1 所需 UTF-8 BOM
（默认 `docs/api-signatures.txt`，Windows 上可自动探测 `Extension\api.txt`）、
无重复函数定义。

### 2.2 测试套件（`tests/`）

```text
pwsh -NoProfile -File tests/run_tests.ps1
→ py_compile OK；独立 mock 冒烟 OK（problems=0）
→ Ran 236 tests in 1.8s / OK
→ 通过率 100%，mock 冒烟通过，结果 PASS
```

覆盖 231 项契约用例 + 5 项静态检查：18 个 spec 形式（17 预设 + custom）、五种协议（四种内置协议 + custom）URL/头/体、
`style`/`contextitems`/`deadline` 选项、目标语言排版规则、非对白过滤、
提示词模板与译文质量门（empty/history_leak/wrong_script/echo/traditional/simplified/too_long）、
登录自检（`/models`、`/api/tags`、`/v1/models`、`/v1beta/models`）、
JSON 路径与 thinking 过滤、错误码映射、JSON 转义与 C0 控制字符、
`SafeUrl` 编码/原文双重脱敏、`MaskKey` 边界、`auth=query` 归一化、
E2E 真实 HTTP（mock）。契约细节与边界决策见 `docs/testing/contract.md`。

> 该层验证的是 Python 参考实现（`tests/support/reference_impl.py`）与 `.as` 的契约镜像，
> 不等于 AngelScript 运行时证明。

### 2.3 独立代码审查

- 初查：P0 = 0，P1 = 3，P2 = 18。
- 修复复核：3 项 P1 全部确认修复；P0 仍为 0；新增 7 条 P2，随后全部收尾。
- 审查覆盖：AngelScript 语法/语义（含 `&in`/`&out`、`JsonValue`、前向引用、
  `MakeLower` 等返回值语义）、逻辑、安全、兼容性、行为回归、可维护性；
  逐项对照官方在用脚本先例。

### 2.4 宿主 API 真实性

`docs/api-signatures.txt` 由本机 `PotPlayer64.dll` 二进制提取，共 104 条签名。
插件使用的 21 个 API 全部命中，且与 `Extension\api.txt` 一致：

`HostOpenHTTP`、`HostGetContentHTTP`、`HostGetStatusHTTP`、`HostGetHeaderHTTP`、`HostCloseHTTP`、
`HostIncTimeOut`、`HostGetTickCount`、`HostLoadString`、`HostSaveString`、
`HostPrintUTF8`、`HostOpenConsole`、`HostRegExpRemove`、`HostUrlEncode`、
`HostSleep`、`HostFileExist`、`HostFileOpen`、`HostFileLength`、`HostFileRead`、`HostFileClose`、
`HostGetPlayingFileName`、`HostGetPlayingTitle`。

> `HostGetStatusHTTP` 在官方随扩展包分发的 17 个脚本中无使用先例（仅
> api.txt 与二进制签名），是最高优先级的实机验证项。

## 3. 未验证范围（必须实机）

1. `HostGetStatusHTTP` 的返回值语义（是否与真实 HTTP 状态码一致）。
2. `HostGetContentHTTP` 的读取顺序、编码、gzip/重定向行为。
3. `HostSaveString` 是否跨 PotPlayer 重启持久化（api.txt 写作 temporary storage）。
4. `HostIncTimeOut(deadline)` 在慢请求下的实际效果（默认 6 s，最大 20 s）。
5. `HostRegExpRemove` 对 `[\x00-\x08…]` 的 std::regex 支持。
6. `&in` 参数写回（`SrcLang/DstLang = "UTF8"`）是否被宿主读取。
7. `GetVersion "0.1.0"`、`GetTitle` 多语言标签的菜单显示；`style`/`deadline` 在真实模型上的效果。
8. 各真实服务商的 Key/模型名与真实网络环境（含代理）下的端到端翻译。

实机验证顺序：安装 → 重启 PotPlayer → 选择 AnyTranslate → 用错误 Key 登录
（期望中文 401）→ 用正确 Key 登录（期望 200 ok）→ 播放 3 条以上字幕 →
`debug=1` 观察状态码/耗时 → 用本机运行的 `tests/support/mock_server.py` + custom spec
验证状态码与响应体解析。

## 4. 交付物

| 文件 | 说明 |
| --- | --- |
| `plugin/SubtitleTranslate - AnyTranslate.as` | 插件（单文件，SHA256 见 Release 说明） |
| `plugin/SubtitleTranslate - AnyTranslate.ico` | 图标（16-256 px 多尺寸） |
| `docs/assets/logo.png` | 图标 512px PNG 预览 |
| `scripts/install.ps1` | 安装/卸载脚本（需管理员权限） |
| `README.md` | 安装、配置、故障排查 |
| `docs/design.md` | 设计契约 |
| `docs/style.md` | 文案与命名约定 |
| `docs/testing/contract.md` | 契约测试说明与边界决策 |
| `docs/testing/angelscript-validation.md` | AngelScript 校验工具链调研 |
| `docs/providers.md` | 各服务 HTTP 契约 |
| `tests/` | mock 服务 + Python 参考实现 + 236 用例（231 契约 + 5 静态） |
| `tests/test_static.py` | 静态检查（unittest 发现，含风格表等长） |

## 5. 复跑命令

```powershell
cd any-translate
python -m unittest tests.test_static -v
powershell -ExecutionPolicy Bypass -File tests\run_tests.ps1   # 或 pwsh -File
python tests/support/mock_server.py --port 18080              # 独立 mock
```

图标为位图资产：`docs/assets/logo.png`（512px 预览）与 `plugin/SubtitleTranslate - AnyTranslate.ico`（16-256 px 九档）。
