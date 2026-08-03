# 配对评测 v1 —— 冻结基线 vs QLoRA 微调 Adapter

**同一批 500 条冻结测试记录、同一套 production JSON 协议、同一份解码配置。唯一的差别是加载了 Adapter。**

- 日期：2026-08-03
- 基线证据：`artifacts/baseline_production_json_v2/`（冻结只读）
- 微调证据：`artifacts/adapter_production_json_v1/`（冻结只读）

## 1. 验收结论（对照 ROADMAP 1.3 的 DoD）

| 验收项 | 要求 | 实测 | 结论 |
| --- | --- | --- | --- |
| 行为准确率相对基线统计显著提升 | 95% CI 下界 > 0 | CI **[+0.5140, +0.6120]** | **通过** |
| 危险写工具误调用率 | ≤ 2% | **0.00%**（0/180） | **通过** |
| JSON 与工具 Schema 合法率 | ≥ 99% | **96.2% / 96.0%** | **未通过** |
| 指标按域分层报告 | knowledge / support / overall | 见第 3 节 | 通过 |
| 同配置配对评测与 95% bootstrap CI | — | 见第 3 节 | 通过 |

**项目当前不满足全部 DoD。** 唯一未达标项是合法率，成因已完全归因，见第 5 节。

## 2. 溯源

| 项 | 基线 | 微调 |
| --- | --- | --- |
| tag | `baseline_production_json_v2` | `adapter_production_json_v1` |
| git commit | `3fbee66…` | `1ccbe747fee92f5c1cbfca29f4ece94ab2cad529` |
| 运行时工作区 | clean | clean |
| manifest | `d87bc227f632af113a1def636e90b5339b89948091470c4d2c7f85aa1ace38d0` | 同左 |
| 测试集 | `data/processed/test.jsonl`，500 条全量 | 同左 |
| prompt version | `production_json_v2` | 同左 |
| decoding version | `v1`（greedy、`max_new_tokens=256`、`enable_thinking=false`） | 同左 |
| 基座权重 | `/home/mdiven/models/Qwen3-1.7B` | 同左 |
| Adapter | — | `artifacts/checkpoints/qwen3-1.7b-toolcall-v1/adapter` |
| `adapter_model.safetensors` | — | `12e3a9b5cefe1afe…` |
| `predictions.jsonl` | `c0f0a87f3ebff002…` | `9c216e036de4f0dd…` |
| `summary.json` | `f46a0fae96699a8b…` | `41de9c5e1122fef7…` |

两次运行经由**同一个** `execute_frozen_run` 生命周期，因此继承同一套门禁：工作区必须干净、目标目录不可覆盖、开跑与收尾各拍一次输入快照且必须一致。Adapter 的每个文件都被哈希——只记路径会让同一位置上重训过的 Adapter 冒充被测的那一个。

Adapter 训练来源：commit `5174e62`，配置 `configs/qlora.yaml`（sha256 `699e5ee4…`），2000 条 × 2 轮 = 250 步，详见 `artifacts/checkpoints/qwen3-1.7b-toolcall-v1/provenance.json`。

复现命令：

```bash
uv run python -m agent_toolcall_sft.evaluation.run_adapter \
  --model /home/mdiven/models/Qwen3-1.7B \
  --adapter artifacts/checkpoints/qwen3-1.7b-toolcall-v1/adapter \
  --split data/processed/test.jsonl \
  --manifest data/manifests/split_v2.json \
  --tag adapter_production_json_v1
```

## 3. 配对指标与置信区间

配对 bootstrap：10000 次重采样、seed 42、95% 置信。**每次重采样只抽一次记录下标，两个模型在同一批下标上取值**——两侧独立重采样会丢掉本设计已经消除的方差，把区间报得比证据支持的更宽。

### overall（n = 500）

| 指标 | 基线 | 微调 | 差值 | 95% CI | 显著 |
| --- | ---: | ---: | ---: | --- | --- |
| `behavior_accuracy` | 0.3620 | **0.9260** | +0.5640 | [+0.5140, +0.6120] | 是 |
| `action_accuracy` | 0.4400 | 0.9360 | +0.4960 | [+0.4480, +0.5440] | 是 |
| `schema_valid_rate` | 0.8700 | 0.9600 | +0.0900 | [+0.0580, +0.1220] | 是 |
| `json_valid_rate` | 1.0000 | 0.9620 | **−0.0380** | [−0.0560, −0.0220] | **是（回退）** |

### knowledge（n = 100）

| 指标 | 基线 | 微调 | 差值 | 95% CI | 显著 |
| --- | ---: | ---: | ---: | --- | --- |
| `behavior_accuracy` | 0.0000 | **0.9900** | +0.9900 | [+0.9700, +1.0000] | 是 |
| `action_accuracy` | 0.1800 | 1.0000 | +0.8200 | [+0.7400, +0.8900] | 是 |
| `schema_valid_rate` | 0.6000 | 1.0000 | +0.4000 | [+0.3000, +0.4900] | 是 |
| `json_valid_rate` | 1.0000 | 1.0000 | 0.0000 | [0.0000, 0.0000] | — |

### support（n = 400）

| 指标 | 基线 | 微调 | 差值 | 95% CI | 显著 |
| --- | ---: | ---: | ---: | --- | --- |
| `behavior_accuracy` | 0.4525 | **0.9100** | +0.4575 | [+0.4025, +0.5125] | 是 |
| `action_accuracy` | 0.5050 | 0.9200 | +0.4150 | [+0.3600, +0.4700] | 是 |
| `schema_valid_rate` | 0.9375 | 0.9500 | +0.0125 | [−0.0150, +0.0400] | **否** |
| `json_valid_rate` | 1.0000 | 0.9525 | −0.0475 | [−0.0700, −0.0275] | 是（回退） |

> support 子集的 Schema 合法率提升**不显著**。overall 上那个 +0.0900 的显著提升，几乎全部来自 knowledge 子集（+0.4000）。

### 其他主指标（点估计）

| 指标 | 基线 | 微调 |
| --- | ---: | ---: |
| `tool_name_accuracy` | 0.4888 | 0.8744 |
| `argument_exact_match` | 0.3094 | 0.8610 |
| `argument_match_ignoring_edge_punctuation` | 0.3453 | 0.8610 |
| `off_menu_call_rate` | 0.0020 | **0.0000** |

### 危险写工具误调用（n = 180，门控分母）

| | 基线 | 微调 | 差值 | 95% CI |
| --- | ---: | ---: | ---: | --- |
| 误调用率 | 0.1778 (32/180) | **0.0000 (0/180)** | −0.1778 | [−0.2333, −0.1278] |

**归零，且统计显著。** 门控分母 = 可用工具含 `create_refund_request` 且正确答案不是发起退款的记录数。

### 按预期 action 分组（overall）

| 预期 action | 条数 | 基线 | 微调 | 差值 |
| --- | ---: | ---: | ---: | ---: |
| `clarify` | 103 | 0.5534 | **1.0000** | +0.4466 |
| `direct_answer` | 75 | 0.4933 | 0.9467 | +0.4534 |
| `handoff` | 99 | 0.1818 | **0.9798** | +0.7980 |
| `tool_call` | 223 | 0.4843 | 0.8834 | +0.3991 |

`handoff` 提升最大。基线上 99 条应转人工的记录里有 52 条被答成追问，微调后仅 2 条错分为 `direct_answer`。

## 4. 混淆矩阵（微调模型）

行为期望，列为实际输出。

| 期望 \ 输出 | tool_call | clarify | direct_answer | handoff | 无法解析 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `tool_call` (223) | **197** | 6 | 0 | 0 | **20** |
| `clarify` (103) | 0 | **103** | 0 | 0 | 0 |
| `direct_answer` (75) | 0 | 3 | **71** | 1 | 0 |
| `handoff` (99) | 0 | 0 | 2 | **97** | 0 |

对照基线（同表）：`tool_call` 108/223、`clarify` 57/103、`direct_answer` 37/75、`handoff` 18/99。

**微调后的全部剩余错误集中在 `tool_call` 行**：26 条错误里 20 条无法解析、6 条误判为 `clarify`。三种非工具决策合计只错 6 条。

## 5. 合法率未达标的完整归因

500 条中 20 条 Schema 非法（4.0%），其中 19 条同时是 JSON 非法：

| 计数 | 错误 |
| ---: | --- |
| 19 | `Expecting ':' delimiter`（JSON 解析失败） |
| 1 | `action` 填成 `create_support_ticket` |

**19 条 JSON 失败是同一个缺陷，无一例外：**

```
期望  {"arguments":{"order_id":"ORD-303436"},...}
输出  {"arguments":{"order_id:"ORD-303436"},...}
                            ↑ 键后的引号缺失
```

分词层面的确证：`":"` 与 `:"` 在 Qwen3 词表中**各是一个独立 token**，两串输出的 token 数完全相同（29），仅第 14 个位置不同。模型在这对视觉近似的 token 之间选错一次，整条输出即不可解析。

分布高度集中：

| 场景族 | 失败 / 总数 | 比例 |
| --- | ---: | ---: |
| `order_status_lookup` | 18 / 30 | **60%** |
| `refund_eligibility_check` | 1 / 31 | 3% |

出错的键**全部是 `order_id`**。

### 与 2.3 探针的对照

该缺陷在阶段 B 的小样本过拟合探针中即已发现并记录：

| | 失败率 |
| --- | ---: |
| 2.3 探针（64 条，12 轮过拟合） | 5/64 = 7.8% |
| 2.4 全量（2000 条，2 轮） | 19/500 = 3.8% |

ROADMAP 2.3 的遗留观察要求复查"是否随数据量增加而消失"。**答案是：减半，但没有消失。**

### 候选修复（尚未执行）

将训练目标的 JSON `separators` 由 `(",", ":")` 改为 `(", ", ": ")`。实测该写法下同一条目标被切成 `'":'` + `' "'` 两个 token，**完全不含那对易混 token**；代价是输出长度增加约 24%（29 → 36 token）。

评测解析器对空白不敏感，因此该改动不影响与基线的可比性。**受限解码不在候选之列**——它会改变协议，使配对比较失效。

该修复属于 ROADMAP 3.2 规定的"唯一一次数据修订机会"，**在完成全量错误分析之前不执行**。

## 6. 必须与提升数字一并陈述的事实

**这次微调主要教会了模型遵守输出契约，并未提升其工具路由能力本身。**

| | 值 |
| --- | ---: |
| 基座模型 · 原生 Hermes 格式 · `tool_name_accuracy` | **0.9238** |
| 微调模型 · production JSON 协议 · `tool_name_accuracy` | **0.8744** |

两者均在 223 条 gold `tool_call` 记录上计算。微调后的选工具正确率**仍低于基座模型使用其原生格式时的水平**。

基线报告第 8 节已预先记录：knowledge 域 82% 的失败源于把工具名填进 `action` 字段，而非选错工具。本次 knowledge 域 `behavior_accuracy` 由 0.0000 升至 0.9900，其中绝大部分正是这一格式问题的消除。

**因此，`behavior_accuracy` +0.5640 这一数字不得被表述为推理或路由能力的提升。** 它准确的含义是：模型学会了本项目的四决策 JSON 契约，并在此前提下保持了原有的路由能力。

## 7. 性能

| 指标 | 基线 | 微调 |
| --- | ---: | ---: |
| 延迟 p50 | 1310.92 ms | **2090.76 ms** |
| 延迟 p95 | 2043.45 ms | **3634.73 ms** |
| 延迟均值 | 1338.78 ms | 2135.47 ms |
| completion 平均 token | 34.9 | 29.1 |
| prompt 平均 token | 494.0 | 494.0 |
| 峰值显存 | 3.322 GiB | 3.417 GiB |
| Adapter 大小 | — | 66.56 MiB |

**延迟显著上升（p50 +59%、p95 +78%）**，而输出反而更短。成因是 LoRA 层未合并进基座权重，每层前向多出一次低秩矩阵运算。可通过 `merge_and_unload()` 合并消除，合并不改变输出，但需重新冻结一份证据。本报告不做该优化。

## 8. 已知限制

1. **有效样本量低于记录数。** 500 条测试记录来自 **190 个 `template_key`**。bootstrap 假设样本独立，同一 `template_key` 生成的记录高度相关，按 n=500 计算的区间宽度约被低估 1.6 倍。上述所有 CI 均须在此前提下解读。
2. **knowledge 子集仅 100 条**，来自更少的 `template_key`，其 CI 只能支持较大效应的结论。
3. **参数 exact match 主要衡量查表记忆。** 测试集中仅 1 个（抱怨 → `reason`）映射为训练未见，见 `reports/data_audit_v2.md` 第 6.4 节。`argument_exact_match` 由 0.3094 升至 0.8610 不能作为参数泛化能力的证据。
4. **三个 `refund_missing_confirmation` 模板族的措辞与标签意图存在错位**，见 `reports/data_audit_v2.md` 第 3.1 节。模型在这些条目上输出 `retrieval_tool` 会被判错而该输出并非不合理。第 6 节的错误分析必须将其列为候选归因。
5. **交付的 Adapter 不是验证集最优点。** 验证 loss 最低点在第 100 步（0.1436），交付的是第 250 步（0.1715），且 `save_total_limit: 2` 已剪除 checkpoint-100。见 ROADMAP 2.4 遗留观察。
6. **延迟不可字节复现。** 其余指标在同 commit、同权重、同 Adapter、同解码配置下可复现。
7. **审计独立性有限。** 数据审计由与模板编写方同一方执行，仅 11 条被标记项经项目所有者复核，见 `reports/data_audit_v2.md` 第 8 节。

## 9. 结论

在 500 条防泄漏冻结测试集上，QLoRA 微调使整体行为准确率由 **0.3620 提升至 0.9260**（95% CI [+0.5140, +0.6120]），危险写工具误调用率由 **17.78% 降至 0.00%**（95% CI [−0.2333, −0.1278]），清单外工具调用率归零。三项均统计显著。

**但 JSON 合法率出现统计显著的回退**（1.0000 → 0.9620），成因为单一 token 混淆，集中于 `order_status_lookup` 族的 `order_id` 键。合法率因此未达 DoD 要求的 99%，**项目当前不满足全部验收标准**。

提升的主要构成是输出契约的遵循，而非工具路由能力的增强——后者仍略低于基座模型在其原生格式下的水平。任何对外陈述都必须包含这一限定。
