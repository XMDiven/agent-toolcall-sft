# Qwen3-1.7B 冻结基线 v2 —— native Hermes 辅助协议

**这是辅助参考，不是主 baseline。** 它只衡量基座模型在**原生工具调用格式**下的路由能力，用于把"不会选工具"和"不会遵循自定义 JSON 契约"这两件事分开。

**本报告的数字不得与 `reports/baseline_qwen3_1_7b_v2.md` 的 `behavior_accuracy` 混用，也不得作为训练前后配对比较的基线。** 主 baseline 只有 production JSON 协议那一份。

- 日期：2026-08-03
- 模型：`/home/mdiven/models/Qwen3-1.7B`（未微调）
- 冻结产物：`artifacts/baseline_native_hermes_v2/`（只读，不进 Git）

## 1. 溯源

| 项 | 值 |
| --- | --- |
| git commit | `3fbee66440f0bac0cdd3bf018b00a817c6d8cd79` |
| 运行时工作区 | clean（开跑与收尾各校验一次） |
| manifest | `data/manifests/split_v2.json`，sha256 `d87bc227f632af113a1def636e90b5339b89948091470c4d2c7f85aa1ace38d0` |
| 测试集 | `data/processed/test.jsonl` |
| **选择规则** | `expected_action == "tool_call"` |
| 源记录 / 选中 / 实评 | 500 / 223 / 223 |
| 记录 id 集合 | sha256 `3b73fec30ac6b52927acaa32fd24f8a6c077ab7f55438569e2e9f0b3e686ac58` |
| prompt version | `native_hermes_v1` |
| decoding version | `v1`：与主协议完全相同 |
| GPU | RTX 3060 Laptop，峰值显存 3.321 GiB |
| 运行时 | Python 3.11.15、torch 2.12.1+cu130、transformers 5.14.1 |
| `predictions.jsonl` | sha256 `cc254c6eca61d65d3ecccdf82c6d38e3ba6da0ec6fc775d5cdec0b55963f8822` |
| `summary.json` | sha256 `c3121765e80fd1447bdf68a317608e6f9cf2fca41533c65fc83a39f540a10eee` |

复现命令：

```bash
uv run python -m agent_toolcall_sft.evaluation.run_native_hermes_baseline \
  --model /home/mdiven/models/Qwen3-1.7B \
  --split data/processed/test.jsonl \
  --manifest data/manifests/split_v2.json \
  --tag baseline_native_hermes_v2
```

## 2. 协议与子集选择

工具目录通过 `apply_chat_template(tools=...)` 交给模型的原生协议，渲染成 `<tools>` 块；模型以 `<tool_call>` 标签输出：

```
<tool_call>
{"name": "retrieval_tool", "arguments": {"question": "..."}}
</tool_call>
```

**只评测正确答案为 `tool_call` 的 223 条。** 原因：原生协议里不存在 `clarify` / `direct_answer` / `handoff` 这三种决策的表达方式，那 277 条题目在这个协议下无法提问，强行评测只会制造无意义的失败。

这也是本报告只能作为辅助参考的根本原因——**它评的是一个被裁剪过的、更容易的子集**。

## 3. 辅助指标

| 指标 | 值 |
| --- | ---: |
| 记录数 | 223 |
| **`tool_name_accuracy`** | **0.9238** |
| `schema_valid_rate` | 0.9955 |
| `json_valid_rate` | 0.9955 |
| `off_menu_call_rate` | **0.0000** |
| `argument_exact_match` | 0.5157 |
| `argument_match_ignoring_edge_punctuation` | 0.7265 |

Schema 错误仅 1 条：`no JSON object`（未产生任何工具调用块）。

**不报告 `action_accuracy` 与 `behavior_accuracy`**——原生协议下不存在四决策的 action 概念，报这两个指标没有意义。

## 4. 性能

| 指标 | 值 |
| --- | ---: |
| 延迟 p50 | 1242.86 ms |
| 延迟 p95 | 2039.33 ms |
| 延迟均值 | 1406.41 ms |
| prompt 平均长度 | 478.3 token |
| completion 平均长度 | 35.7 token |

## 5. 与主协议的对照

同一模型、同一批题目（主协议 500 条中的这 223 条子集）、同一解码配置，唯一差别是提问格式：

| 指标 | production JSON (500 条) | native Hermes (223 条) |
| --- | ---: | ---: |
| `tool_name_accuracy` | 0.4888 | **0.9238** |
| `schema_valid_rate` | 0.8700 | 0.9955 |
| `off_menu_call_rate` | 0.0020 | 0.0000 |
| `argument_exact_match` | 0.3094 | 0.5157 |
| `argument_match_ignoring_edge_punctuation` | 0.3453 | 0.7265 |

> 注意：两列的样本集合不同（500 全量 vs 223 gold-tool_call 子集），因此**不是严格的配对比较**。子集只含调用工具的题，本身更容易。这一列对照用于说明差异的量级，不能当作精确的差值。

**结论：基座模型在原生格式下 92.4% 能选对工具，且从不调用清单外的工具；换到自定义四决策 JSON 契约后掉到 48.9%。** 主协议里那 65 条 Schema 非法中有 64 条是同一种错误——把工具名填进了 `action` 字段。

这说明主 baseline 的低分**主要来自契约遵循能力，而非工具路由能力**。

## 6. 这份报告在阶段 C 的用途

微调后 `behavior_accuracy` 若大幅提升，必须回答一个问题：提升来自模型学会了选工具，还是仅仅学会了填格式？

本报告提供的基准是：**微调前，模型在没有格式负担时已经能选对 92.4% 的工具。** 因此主协议上的提升若主要落在 Schema 合法率与格式对齐上，就不能被表述为路由能力的增强。

阶段 C 报告需要同时给出：

1. 主协议 `behavior_accuracy` 的前后差值与 95% 置信区间（主结论）；
2. 主协议 `schema_valid_rate` 的前后差值（格式对齐贡献）；
3. 本报告的 `tool_name_accuracy` 作为路由能力的上界参照。

## 7. 已知限制

1. **子集更容易。** 223 条全部是需要调用工具的题，不含 clarify / direct_answer / handoff，与主协议的 500 条不可直接相减。
2. **参数指标受数据限制。** `argument_exact_match` 与宽松口径差 0.21，差距主要来自模型把礼貌用语一并塞进参数（如"帮我对比一下，……？谢谢。"）以及保留句末问号。同时测试集只有 1 个训练未见的（抱怨 → `reason`）映射，见 `reports/data_audit_v2.md` 第 6.4 节。
3. **不构成安全评估。** 本协议不评测危险写工具的确认语义，安全指标只以主 baseline 为准。
4. **延迟不可字节复现。**

## 8. 版本关系

本文件为首次生成，无前代版本。2026-08-01 那一轮从未产出 native Hermes 报告——当时主协议错误地使用了原生工具格式，两套协议未分离，这正是 `3f199a1` 撤回那一轮的原因之一。
