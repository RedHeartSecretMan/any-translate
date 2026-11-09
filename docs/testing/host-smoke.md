# PotPlayer 宿主冒烟检查清单

用于覆盖发布前最关键的宿主行为。自动化测试（`tests/`）只能验证解析、请求体和静态契约，不能替代本清单。

## 1. 安装核对

```powershell
$repo = "C:\path\to\any-translate"
$source = Join-Path $repo "plugin\SubtitleTranslate - AnyTranslate.as"
$target = "C:\Program Files\DAUM\PotPlayer\Extension\Subtitle\Translate\SubtitleTranslate - AnyTranslate.as"
Get-FileHash $source, $target -Algorithm SHA256
```

源文件和目标文件 SHA256 必须一致；否则重新运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

## 2. 启动与选择

1. 完全退出 PotPlayer 后重新启动。
2. 打开 `字幕 -> 实时字幕翻译`。
3. 确认能看到 `AnyTranslate`。
4. 确认目标语言与预期一致；如宿主缓存旧语言，用 `dst=` 临时覆盖验证。

## 3. 登录与 probe

1. 配置本地或云端服务。
2. 若使用 `probe=models`，确认登录成功或错误信息可操作。
3. custom + `probe=models` 时，确认派生 `/models` 不阻塞登录；没有模型列表接口时 404/405 应放行。
4. 故意填错模型名，确认登录错误能显示可用模型或明确原因。

## 4. 字幕播放

播放一段有连续对白的视频，确认：

- 字幕有译文，且没有把原文、`【背景信息】`、`【待翻译文本】` 或 `'''` 输出到画面；
- 非对白行（纯符号、数字、音乐符号）不触发请求；
- 长句不会被截断成异常短句；
- 连续播放 3 分钟没有明显卡顿；
- `debug=1` 时控制台只显示摘要，不显示字幕正文；
- 需要完整请求/响应时使用 `debug=2`，并确认这是临时排障配置。

## 5. 历史与切换

1. 观察连续几句的称呼、术语是否一致。
2. 暂停超过 2 分钟，确认上下文被清空。
3. 切换到另一个视频文件，确认上下文和缓存不会串到新视频。
4. 修改目标语言、style 或 glossary 后重新登录，确认旧缓存不命中。

## 6. 失败路径

- 断网/错误端口：运行期应静默返回空串，不把错误文案写入字幕；
- 429/5xx：确认会在 deadline 内重试，且不会阻塞后续字幕；
- 401/403：登录期提示，运行期不持续请求；
- 400 参数错误：确认最小体重试只发生一次；
- 超大响应或非法 JSON：不应崩溃，字幕保持空串。

## 7. 记录

记录：

- PotPlayer 版本；
- 插件源/目标 SHA256；
- 模型与协议；
- 目标语言；
- 是否使用 `contextmode=split/block/turns`；
- 观察到的延迟、空字幕率和串线情况。
