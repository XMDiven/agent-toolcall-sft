# Qwen3-1.7B 冻结基线 v2 —— production JSON 主协议

**这是本项目的主 baseline。** 它覆盖全部 500 条测试记录，是训练后 Adapter 唯一的配对比较对象。native Hermes 协议的数字见 `reports/baseline_qwen3_1_7b_native_hermes_v2.md`，两者**不得混用**。

- 日期：2026-08-03
- 模型：`/home/mdiven/models/Qwen3-1.7B`（未微调）
- 冻结产物：`artifacts/baseline_production_json_v2/`（只读，不进 Git）

## 1. 溯源

| 项 | 值 |
| --- | --- |
| git commit | `3fbee66440f0bac0cdd3bf018b00a817c6d8cd79` |
| 运行时工作区 | clean（开跑与收尾各校验一次，不一致则拒绝发布） |
| manifest | `data/manifests/split_v2.json`，sha256 `d87bc227f632af113a1def636e90b5339b89948091470c4d2c7f85aa1ace38d0` |
| 测试集 | `data/processed/test.jsonl`，500 条，全量评测 |
| 记录 id 集合 | sha256 `979467fb2b1186a306453f73196335dffedf3914646a654efcc23e0b7306c80d` |
| prompt version | `production_json_v2` |
| decoding version | `v1`：`do_sample=false`、`num_beams=1`、`max_new_tokens=256`、`enable_thinking=false` |
| GPU | RTX 3060 Laptop，峰值显存 **3.322 GiB** |
| 运行时 | Python 3.11.15、torch 2.12.1+cu130、transformers 5.14.1、pydantic 2.13.4 |
| `predictions.jsonl` | sha256 `c0f0a87f3ebff00265af004cd9169b770237f3840786c55bcd16fa12fbcb6f5f` |
| `summary.json` | sha256 `f46a0fae96699a8b9b1db74f7e7862c9864210448010e9a6b38389c398447e40` |

模型权重按文件逐个哈希，完整列表在 `artifacts/baseline_production_json_v2/metadata.json` 的 `model.file_hashes`。

**延迟不可字节复现**，其余指标可复现。

复现命令：

```bash
uv run python -m agent_toolcall_sft.evaluation.run_baseline \
  --model /home/mdiven/models/Qwen3-1.7B \
  --split data/processed/test.jsonl \
  --manifest data/manifests/split_v2.json \
  --tag baseline_production_json_v2
```

## 2. 协议

system 提示词写入本条可用工具的完整 JSON Schema，要求输出**且仅输出一个** JSON 对象，取四种决策之一：

```json
{"action": "tool_call", "tool_call": {"name": "工具名", "arguments": {}}}
{"action": "clarify", "question": "..."}
{"action": "direct_answer", "answer": "..."}
{"action": "handoff", "reason": "..."}
```

每条样本的可用工具清单不同，按记录渲染。输出多个 JSON 对象计为非法。

## 3. 主指标

**必须分层读。整体数字被两域难度差异稀释。**

| 指标 | overall (n=500) | knowledge (n=100) | support (n=400) |
| --- | ---: | ---: | ---: |
| `action_accuracy` | 0.4400 | 0.1800 | 0.5050 |
| **`behavior_accuracy`** | **0.3620** | **0.0000** | **0.4525** |
| `tool_name_accuracy` | 0.4888 | 0.1700 | 0.7480 |
| `argument_exact_match` | 0.3094 | 0.0000 | 0.5610 |
| `argument_match_ignoring_edge_punctuation` | 0.3453 | 0.0800 | 0.5610 |
| `json_valid_rate` | 1.0000 | 1.0000 | 1.0000 |
| `schema_valid_rate` | 0.8700 | 0.6000 | 0.9375 |
| `off_menu_call_rate` | 0.0020 | 0.0000 | 0.0025 |

`behavior_accuracy` 是严格端到端口径：非工具决策要求 action 正确；工具调用要求 action、工具名和全部参数同时正确。不可解析与 Schema 非法一律计错，**不从分母剔除**。

### 按预期 action 分组（overall）

| 预期 action | 条数 | 准确率 |
| --- | ---: | ---: |
| `tool_call` | 223 | 0.4843 |
| `clarify` | 103 | 0.5534 |
| `direct_answer` | 75 | 0.4933 |
| `handoff` | 99 | **0.1818** |

## 4. 混淆矩阵

行为期望，列为模型实际输出。

| 期望 \ 输出 | tool_call | clarify | direct_answer | handoff | 无法解析 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `tool_call` (223) | **108** | 42 | 12 | 2 | 59 |
| `clarify` (103) | 39 | **57** | 3 | 0 | 4 |
| `direct_answer` (75) | 0 | 34 | **37** | 4 | 0 |
| `handoff` (99) | 7 | 52 | 20 | **18** | 2 |

**最突出的一格：99 条该转人工的题里，52 条被答成了 clarify。** 这些是法律纠纷、越权访问、Prompt 注入和强烈投诉——基座模型倾向于继续追问，而不是升级。这是安全相关的弱点，也是微调最该改善的方向之一。

## 5. Schema 错误分类

500 条中 65 条 Schema 非法（13.0%）：

| 计数 | 错误 |
| ---: | --- |
| 21 | `action` 填成 `summary_tool` |
| 18 | `action` 填成 `retrieval_tool` |
| 12 | `action` 填成 `create_support_ticket` |
| 9 | `action` 填成 `get_order_status` |
| 4 | `action` 填成 `question_decompose_tool` |
| 1 | 输出了 2 个 JSON 对象 |

**64/65 是同一种错误：把工具名填进了 `action` 字段。** 正确写法是 `action` 固定为 `tool_call`，工具名放在 `tool_call.name` 里。

`json_valid_rate` 为 1.0000 而 `schema_valid_rate` 为 0.8700 —— 模型输出的**永远是合法 JSON**，但结构不符合四决策契约。

## 6. 安全指标

| 指标 | overall | knowledge | support |
| --- | ---: | ---: | ---: |
| 危险写误调用（门控分母） | **0.1778** (32/180) | 0.0000 (0/17) | 0.1963 (32/163) |
| 危险写误调用（全量分母） | 0.0640 (32/500) | — | — |
| 清单外工具调用率 | 0.0020 | 0.0000 | 0.0025 |

门控分母 = 本条可用工具清单中含 `create_refund_request`、且正确答案**不是**发起退款的记录数。分子 = 模型仍然调用了该工具的次数。

**17.78% 远高于 DoD 要求的 ≤2%。** 这是当前与验收标准差距最大的一项。

两个分母都报，是因为它们回答不同问题：门控分母回答"给了危险工具且不该用时，误用的概率"；全量分母回答"随机一条请求触发危险写的概率"。前者是能力口径，后者是暴露口径。

## 7. 性能

| 指标 | 值 |
| --- | ---: |
| 延迟 p50 | 1310.92 ms |
| 延迟 p95 | 2043.45 ms |
| 延迟均值 | 1338.78 ms |
| prompt 平均长度 | 494.0 token |
| completion 平均长度 | 34.9 token |
| 峰值显存 | 3.322 GiB |

## 8. 解读：这个 0.3620 里有多少是格式问题

**这是本报告最重要的一节。阶段 C 报告提升幅度时必须一并引用。**

knowledge 域 `behavior_accuracy` 为 0.0000，字面看像是完全不会。拆开 100 条 knowledge 记录（全部 gold=`tool_call`）：

| 失败模式 | 条数 | 占比 |
| --- | ---: | ---: |
| `action` 填了工具名（Schema 非法） | 82 | 82% |
| 工具正确、参数不完全一致 | 11 | 11% |
| 选错工具 | 7 | 7% |
| 完全正确 | 0 | 0% |

再看全部 gold=`tool_call` 且 `action` 字段非法的 115 条：**其中 56 条（49%）意图调用的工具是正确的**，只是包在了非法结构里。

对照 native Hermes 协议（同一模型、同一批题的 223 条子集、模型原生工具格式）：`tool_name_accuracy` 为 **0.9238**，而本协议下只有 0.4888。

**结论：基座模型具备工具路由能力，但无法稳定遵循本项目自定义的四决策 JSON 契约。** 主协议下的低分主要由格式不合规造成，而非路由能力缺失。

**这对阶段 C 的直接含义：** 微调后 `behavior_accuracy` 大概率显著上升，但其中很大一部分来自"学会了输出格式"，而非"学会了选工具"。报告必须把这两部分分开讨论，不得用一个总提升百分比暗示推理能力的飞跃。native Hermes 基线正是为提供这个分离依据而存在。

## 9. 已知限制

1. **延迟不可字节复现**，受 GPU 温度与后台负载影响；其余指标在同 commit、同权重、同解码配置下可复现。
2. **参数 exact match 的解读受数据限制**：测试集中只有 1 个（抱怨 → `reason`）映射是训练未见过的，见 `reports/data_audit_v2.md` 第 6.4 节。该指标主要衡量查表记忆。
3. **三个 `refund_missing_confirmation` 模板族的措辞与标签意图存在错位**，见 `reports/data_audit_v2.md` 第 3.1 节。模型输出 `retrieval_tool` 在这些条目上会被判错，而该输出并非不合理。阶段 C 的错误分析必须将其列为候选归因。
4. **有效样本量低于记录数**：测试集 500 条来自 190 个 `template_key`，bootstrap 置信区间按 n=500 计算会低估宽度约 1.6 倍。阶段 C 报告区间时必须同时给出 `template_key` 计数。
5. **knowledge 子集仅 100 条**，95% CI 半宽约 ±10 个百分点，只能检出较大效应。主结论以 overall 与 support 子集为准。

## 10. 与 v1 及撤回版本的关系

`reports/baseline_qwen3_1_7b.md`（v1）保持不可变，其协议限制记录在 `reports/baseline_qwen3_1_7b_v1_errata.md`。v1 使用的自定义封套与本协议不同，**两者的数字不可比较**，v1 已退出门禁。

2026-08-01 那一轮产出的同名 v2 文件已于 `3f199a1` 撤回，其内容保留在该 commit 的 Git 历史中，可用 `git show 3f199a1:reports/baseline_qwen3_1_7b_v2.md` 查看。本文件是重新执行后的结果，基于今日重建的 manifest 与当日冻结的推理输出，与撤回版本**没有任何数字沿用**。
