# tests

测试全部使用 Python 标准库，不依赖第三方包；需要 Python 3.10 或更高。

| 文件 | 作用 |
| --- | --- |
| `test_contract.py` | 231 项契约测试：spec 解析、style/contextitems/contextmode/contextchars/deadline、五种协议（四种内置 + custom）请求/响应、目标语言规则、非对白过滤、质量门、错误码、登录自检、E2E mock |
| `test_static.py` | 6 项插件静态检查：括号配平、入口点、`L_*` / `P_*` / `STYLE_*` 表、语言表定义、缓存 key 不含历史、`Translate` 宿主张量写回、Host API 签名（与上项合计 237） |
| `support/reference_impl.py` | Python 参考实现，逐函数镜像 `.as` |
| `support/mock_server.py` | 本机 mock LLM 服务，记录请求供断言 |
| `run_tests.ps1` | 一键运行：py_compile → mock 冒烟 → unittest → 摘要 |

## 运行

```powershell
# 一键（推荐）
pwsh -File tests/run_tests.ps1

# 直接 unittest（静态检查也在里面）
python -m unittest discover -s tests -v

# 只跑静态检查
python -m unittest tests.test_static -v
```

Windows PowerShell 5.1 与 PowerShell 7 均可运行 `run_tests.ps1`；PATH 中没有 `python` 时用
`-Python <path>`，或设置 `ANYTRANSLATE_PYTHON`。

## 约定

- `test_<kind>.py`：unittest 模块，`kind` 用简短的层名（`contract` / `static`）。
- `support/<完整名词>.py`：被测试代码复用的模块，不用缩写、不加 `test_` 前缀。
- `run_tests.ps1`：唯一入口脚本，保持 `动词_名词` 命名。
- 新增测试优先放进 `test_contract.py` 对应的 `TestCase`；新增独立关注点再建 `test_<kind>.py`。
- 静态检查与契约测试共享同一个 unittest 入口，`run_tests.ps1` 不再单独调用检查脚本。
