# AngelScript 校验工具链调研

> 位置：`docs/testing/ANGELSCRIPT-VALIDATION.md` ｜ 相关代码：`tools/check_as.py`、`tests/`
>
> 调研时间：2026-11-07。

## 1. 本机探测结果

| 探测项 | 结果 |
| --- | --- |
| `cl.exe` / `cmake` / `g++` / `clang++` | 均不在 PATH |
| Visual Studio / VS Build Tools | `%ProgramFiles%\Microsoft Visual Studio`、`(x86)` 均不存在 |
| LLVM | `%ProgramFiles%\LLVM` 不存在 |
| Node.js / npm / pnpm | 均不在 PATH（`%ProgramFiles%\nodejs` 不存在） |
| AngelScript SDK | 用户目录下无 `*angel*` 目录；无 vcpkg / conan2 |
| Python 包 | `pip list` 无 angel 相关包 |
| PotPlayer 自带 | `Extension\api.txt` 说明脚本引擎就是 AngelScript；只在运行时加载插件时编译，无法离线调用 |

## 2. 离线校验需要的前置条件

AngelScript 官方 SDK（https://www.angelcode.com/angelscript/）只提供 C/C++ 源码，
离线校验需要：

1. 编译 `angelscript` 静态库（需要 C++ 编译器）；
2. 实现最小宿主，注册 PotPlayer 的 `Host*` 函数与 `JsonValue` / `JsonReader` 类型；
3. 用 `asIScriptEngine::Build` 编译待校验脚本。

## 3. 当前校验方式

### 3.1 静态检查（`tools/check_as.py`）

不解析 AngelScript，检查会导致加载失败的机械问题：

- 花括号/圆括号/方括号在字符串与注释之外是否配平；
- 语言表 `L_CODE` / `L_LABEL` / `L_PROMPT` 长度一致且无重复；
- 预设表长度与 `P_ID` 一致；
- 用到的 `Host*` API 是否都能在 `%ProgramFiles%\DAUM\PotPlayer\Extension\api.txt` 中找到；
- 必需入口函数（`GetTitle`/`ServerLogin`/`Translate`/…）是否齐全。

当前输出：

```text
L_CODE=82  L_LABEL=82  L_PROMPT=82
P_BASE=17  P_MODEL=17  P_PROTO=17  P_AUTH=17  P_KEYNAME=17  P_EXTRA=17
Host API used: 13; documented in docs/api-signatures.txt: 103
functions defined: 62
OK: static checks passed
```

```powershell
python tools/check_as.py
```

### 3.2 契约测试（`tests/`）

```powershell
python -m unittest discover -s tests -v
# 或
pwsh -File tests/run_tests.ps1
```

不执行 AngelScript，但把"配置语法 → HTTP 请求 → 响应解析"的契约固定下来；
`tests/ref_impl.py` 逐函数镜像 `.as`，人工按 `docs/testing/CONTRACT.md` §7
的清单做对照。

### 3.3 PotPlayer 实机加载

1. 把 `SubtitleTranslate - AnyTranslate.as` + `.ico` 复制到
   `<PotPlayer>\Extension\Subtitle\Translate\`
   （需要管理员权限；不要覆盖安装目录里已有的其他插件文件）；
2. 重启 PotPlayer → 右键 → 字幕 → 实时字幕翻译 → 选择插件；
3. 语法错误在加载阶段暴露；逻辑问题通过插件内 `HostOpenConsole()` / `Dbg()`
   日志排查（`.as` 提供 `debug=1` 开关）。

### 3.4 CI 方案（未实施）

在 CI 的 Linux runner 上安装 `g++` 与 AngelScript SDK，实现 PotPlayer 的
`Host*` / `JsonValue` stub 后编译脚本，可把语法校验放进流水线。npm 生态也有
AngelScript 的 Emscripten/WASM 封装（包名待确认），同样需要宿主 stub。

## 4. 校验流程

- 提交前：`python tools/check_as.py` + `pwsh -File tests/run_tests.ps1`，
  再按 `docs/testing/CONTRACT.md` §7 做人工对照；
- 发布前：PotPlayer 实机加载一次，并用真实 Key 对各服务商各翻译一条字幕
  （`tests/` 的 mock 不覆盖宿主 HTTP 行为）。
