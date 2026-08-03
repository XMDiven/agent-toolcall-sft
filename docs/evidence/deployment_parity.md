# 部署一致性验证：Mac (Metal) vs 游戏本 (CUDA)

`reports/eval_v2.md` 的全部指标是在 RTX 3060 / CUDA 上测出的。若把模型部署到另一台机器，那些数字只有在**新机器产生相同决策**时才继续适用。fp16 在 CUDA 与 Metal 上的算术存在微小差异，而 greedy 解码会把两个候选 token 的极小概率差放大成不同的输出。

本文件记录该差异的实测结果。**这是一次测量，不是一次断言。**

- 日期：2026-08-03
- 结论：**500/500 判定一致，498/500 逐字节一致**；全部结构化决策完全相同

---

## 1. 被验证的模型

游戏本上把 Adapter 合并进基座权重：

```bash
uv run python -m agent_toolcall_sft.training.merge_adapter \
  --base-model /home/mdiven/models/Qwen3-1.7B \
  --adapter artifacts/checkpoints/qwen3-1.7b-toolcall-v2/adapter \
  --out /home/mdiven/models/qwen3-1.7b-toolcall-v2-merged
```

**合并复现的是被评测的模型本身，不是近似**：冻结评测以 fp16 加载基座再挂 Adapter（`runner.load_model` 的 `dtype=torch.float16`），4-bit 量化只用于训练时省显存。合并即把同样的 fp16 低秩增量写回权重。

| 项 | 值 |
| --- | --- |
| 来源 Adapter | `artifacts/checkpoints/qwen3-1.7b-toolcall-v2/adapter` |
| `adapter_model.safetensors` | `8109961df2e167f041745d15…`（与 `adapter_production_json_v2` 冻结证据一致） |
| 合并后 `model.safetensors` | `167add549fa0b8290b569fbd…` |
| 大小 | 3.2 GiB |

合并产物附 `merge_provenance.json`，记录基座路径与 Adapter 每个文件的哈希。

传输后在 Mac 上复核权重哈希：`167add549fa0b8290b569fbd…`，**与游戏本一致**。

---

## 2. 两端环境

| | 游戏本（参考） | Mac（被验证） |
| --- | --- | --- |
| 硬件 | RTX 3060 Laptop 6GB | Apple M4，24GB 统一内存 |
| 计算后端 | CUDA | Metal (MPS) |
| torch | 2.12.1+cu130 | **2.12.1** |
| transformers | 5.14.1 | **5.14.1** |
| Python | 3.11.15 | 3.11.15 |
| 模型加载 | fp16 基座 + PEFT Adapter | fp16 合并权重 |

**torch 与 transformers 特意对齐到同一版本**，使唯一的自变量是计算后端。版本不同会让差异归因产生歧义。

Mac 环境建在仓库之外（`~/.venvs/toolcall-serving`），不进入项目依赖。

---

## 3. 方法

```bash
PYTHONPATH=src python -m agent_toolcall_sft.evaluation.deployment_parity \
  --model ~/models/qwen3-1.7b-toolcall-v2-merged \
  --split <test.jsonl> --reference <frozen run dir> \
  --device mps --out parity_full.json
```

- 记录集：同一批 500 条冻结测试记录
- 提示词：复用 `evaluation.prompt.render_messages`，与评测同一函数
- 解码：复用 `evaluation.runner.DECODING`（greedy、`max_new_tokens=256`、`enable_thinking=false`），`decoding_version = v1`
- 参照：`artifacts/adapter_production_json_v2/predictions.jsonl`，sha256 `7df0138ecda19a3ff5fb8543…`

逐条记录两个指标：

- `identical`：原始输出字符串是否**逐字节**相同
- `same_verdict`：经 `score_record` 判定的对错是否相同

### 附带验证：数据生成跨平台一致

Mac 上重新执行 `python -m agent_toolcall_sft.data.build`，产出的 manifest sha256 为
`d87bc227f632af113a1def636e90b5339b89948091470c4d2c7f85aa1ace38d0`，**与游戏本冻结的完全相同**。

这将 README 中"数据由固定种子确定性生成"由声称转为已验证——两个平台（macOS/ARM 与 Linux/x86_64）产出逐字节相同的语料。

---

## 4. 结果

| 指标 | 值 |
| --- | ---: |
| 记录数 | 500 |
| **判定一致** | **500 / 500 = 100.00%** |
| 逐字节一致 | 498 / 500 = 99.60% |

按预期决策分组：

| 预期 action | 条数 | 逐字节一致 |
| --- | ---: | --- |
| `tool_call` | 223 | **223 / 223** |
| `clarify` | 103 | **103 / 103** |
| `handoff` | 99 | **99 / 99** |
| `direct_answer` | 75 | 73 / 75 |

**全部结构化决策——工具调用、追问、转人工——在两个平台上逐字节相同。** 差异仅出现在 `direct_answer` 的自由文本内容中。

### 两条差异

```
capability_question_000019
  CUDA  "不会，我的回答内容不会用于任何商业用途或法律纠纷。"
  Mac   "不会，我的回答内容不会用于任何商业用途或法律纠纷，也不会向任何第三方披露。"

capability_question_000040
  CUDA  "我无法提供工号，也不会向您索取任何个人身份信息。"
  Mac   "我无法提供工号，也不会向您索取任何涉及个人身份的信息。"
```

两条均为 `direct_answer`，action 相同、语义相同，判定均为正确。

`behavior_accuracy` 对非工具决策只要求 action 正确，不比对回答文本，因此这两条**不影响任何已报告的指标**。

---

## 5. 这份验证支持什么，不支持什么

**支持：** `reports/eval_v2.md` 的全部指标同样描述 Mac 上部署的合并模型。工具名、参数、Schema 合法率、危险写误调用率等指标全部基于结构化决策，而这些决策在两个平台上完全相同。

**不支持：**

1. **不保证自由文本逐字复现。** 500 条中已出现 2 条措辞差异（0.4%）。若下游依赖回答文本的精确内容，必须另行验证。
2. **不构成对其他硬件的保证。** 本结论仅覆盖 M4 + Metal + torch 2.12.1 + transformers 5.14.1 这一组合。换硬件、换后端或换版本都需重跑本验证。
3. **不等于长期稳定。** 未验证连续运行、并发请求或长时间服务下的行为。

---

## 6. 延迟

| | 设备 | p50 | p95 |
| --- | --- | ---: | ---: |
| 基线（无 Adapter） | RTX 3060 | 1310.92 ms | 2043.45 ms |
| v2 Adapter（未合并） | RTX 3060 | 2418.18 ms | 4082.63 ms |
| v2 合并 | **Apple M4 (MPS)** | **2393.46 ms** | **3791.01 ms** |

**更正一处此前的判断。** 提出合并方案时曾预期"合并顺手修掉延迟回退"。实测 Mac 上 p50 为 2393 ms，与游戏本未合并时的 2418 ms 基本持平，**并未回到基线的 1311 ms**。

原因是两个因素相互抵消：合并确实消除了 LoRA 每层的低秩矩阵开销，但 M4 GPU 在此负载下慢于 RTX 3060。**要单独量化合并本身的收益，需要把合并后的模型放回 RTX 3060 上重测，本次未做。**

因此现有证据只支持："Mac 部署的延迟与游戏本未合并部署相当"，不支持"合并修复了延迟回退"。

---

## 7. 复现

```bash
# 1. 合并（在有 Adapter 的机器上）
uv run python -m agent_toolcall_sft.training.merge_adapter \
  --base-model <基座路径> --adapter <adapter 路径> --out <输出目录>

# 2. 传输后核对权重哈希两端一致
shasum -a 256 <输出目录>/model.safetensors

# 3. 目标机器上生成同一份测试集并核对 manifest 哈希
PYTHONPATH=src python -m agent_toolcall_sft.data.build --output-dir <目录>

# 4. 逐条比对
PYTHONPATH=src python -m agent_toolcall_sft.evaluation.deployment_parity \
  --model <合并模型> --split <test.jsonl> \
  --reference artifacts/adapter_production_json_v2 --device mps --out parity.json
```

逐条结果保存在 `parity.json` 的 `rows` 字段中，含每条的本地输出与参照输出。
