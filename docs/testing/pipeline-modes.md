# 三种 contextmode 实测记录

日期：2026-11-08  
模型：本地 `index2b`（`http://127.0.0.1:18080/v1/chat/completions`，OpenAI 兼容）  
样本：`vincent-film/dist/Vincent_van_Gogh_1080p_light.srt` 前 14 条  
方向：中文 → 英文（故意选非中文目标，避免简繁直转绕过模型）  
历史：最近 4 组成功译文  
参数：`temperature=0.2`、`max_tokens=256`、`stream=false`，每条模式先做一次预热请求

## 请求结构

- `block`：1 条 user，包含规则、历史、当前句；
- `split`：system（规则/风格/语言）+ user（历史块 + 当前句）；
- `turns`：system（规则/风格/语言/只翻译最后一条 user）+ 历史 user/assistant 对 + 当前 user。

## 汇总结果

| 模式 | HTTP 200 | 校验失败 | 历史泄漏 | 平均延迟 | p95 | 总 token |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| block | 14/14 | 0 | 0 | 0.11 s | 0.14 s | 5798 |
| split | 14/14 | 0 | 0 | 0.12 s | 0.13 s | 5872 |
| turns | 14/14 | 0 | 0 | 0.11 s | 0.13 s | 5809 |

所有请求均被本地服务接受，三种模式都没有出现 400；本地服务对 system 消息和 assistant 历史角色均兼容。

## 输出观察

- block 与 split 的译文高度接近，差异主要是语序和个别措辞：
  - split：`Above Xue County, I saw eight black stones.`
  - block：`I saw eight black stones above Xue County.`
- turns 第 1 条把 `提要` 译成 `Summary`，block/split 译成 `Synopsis`；第 10 条 turns 的 `retreat` 与 block/split 的 `take ... back` 语义不同。
- 三种模式都把第 9 条的 `一百万个句子` 译成了 `a million giants`，这是模型本身的词义错误，不是模式差异。
- 第一轮未预热测试中，turns 第 2 条曾出现把上一条的 `Synopsis:` 前缀带进当前句的现象；预热后复测未复现。说明 turns 对本地小模型有上下文串线风险，但不能据此认定稳定复现。

## 结论

1. 三种模式均可被本地 OpenAI 兼容服务接受，请求结构没有协议错误。
2. 本轮 14 条样本中 split 没有表现出明显质量收益，token 只增加约 1.3%，延迟无显著差异。
3. turns 在当前小模型上出现过上下文前缀串线，暂不建议作为默认模式。
4. 默认 `contextmode=split`；`block`/`turns` 仍可通过参数切换。Index/Hy-MT2 仅作为提示词结构参考，不做模型路由。
5. 本测试是**请求结构级实测**，不是 PotPlayer 宿主内实测；安装目录当时仍是旧版，宿主内 A/B 需要安装最新源码后进行。

## 通用 split 提示词优化实测

参考官方模板把通用提示词改成：

- system：任务 + `【硬性要求】` + 风格/语言规则；
- user：`【背景信息】` + `【待翻译文本】`；
- 术语：`【术语对照】 A→B`。

同一批 14 条、同一历史窗口、同一 `index2b`、中文 → 英文：

| 模板 | 校验失败 | 平均延迟 | p95 | 总 token |
| --- | ---: | ---: | ---: | ---: |
| 旧 split（长规则 + 最近台词块） | 0 | 0.11 s | 0.14 s | 5932 |
| 新 split（官方分段结构） | 0 | 0.12 s | 0.15 s | 5444 |

最终版本比旧模板 token 下降约 8.2%，14 条请求全部通过校验。输出基本一致，差异主要是：

- 第 2 条：`Above Xue County, I saw eight black stones.`（旧：`I saw eight black stones above Xue County.`）
- 第 14 条：`We stayed.`（旧：`We stayed behind.`）

这次只说明提示词结构更紧凑、没有引入明显格式错误；不代表质量一定优于旧模板，决定默认 `split` 后仍建议用长片继续观察。

## 提示词结构参考

- [Index-Translate-2B](https://huggingface.co/IndexTeam/Index-Translate-2B)
- [Index-Translate canonical instTrans client](https://github.com/bilibili/Index-Translate/blob/main/inference/llm/call_api.py)
- [Hy-MT2-1.8B](https://huggingface.co/tencent/Hy-MT2-1.8B)
- [Hy-MT2 official template implementation](https://github.com/aadebuger/ComfyUI-HyMT2/blob/main/nodes/runtime.py)
