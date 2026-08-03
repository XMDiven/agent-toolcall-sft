# agent-toolcall-sft

在 6GB 显存的消费级笔记本上，把 Qwen3-1.7B 微调为企业客服场景的**安全工具路由模型**，并用冻结基线、防泄漏切分和配对统计检验证明效果。

**这个项目真正想证明的不是"1.7B 能变多强"，而是"这些数字经得起别人复算"。**

---

## 结果

在 500 条防泄漏冻结测试集上，与未微调的 Qwen3-1.7B 同配置配对比较：

| 指标 | 基线 | 微调后 | 95% 置信区间 |
| --- | ---: | ---: | --- |
| **行为准确率**（整体） | 0.3620 | **0.9540** | [+0.5460, +0.6360] |
| 行为准确率（knowledge） | 0.0000 | 0.9800 | [+0.9500, +1.0000] |
| 行为准确率（support） | 0.4525 | 0.9475 | [+0.4425, +0.5475] |
| **危险写工具误调用率** | 17.78% | **1.11%** | [−0.2222, −0.1167] |
| JSON 合法率 | 100.00% | **100.00%** | — |
| 工具 Schema 合法率 | 87.00% | **99.60%** | [+0.0960, +0.1560] |
| 清单外工具调用率 | 0.20% | **0.00%** | — |

行为准确率为严格端到端口径：非工具决策要求 action 正确；工具调用要求 action、工具名与全部参数同时正确。不可解析与 Schema 非法一律计错，**不从分母剔除**。

配对 bootstrap：10000 次重采样、seed 42，每次只抽一次记录下标、两个模型共用。

- 硬件：RTX 3060 Laptop 6GB，训练峰值显存 4.11 GiB，全量训练 52 分钟
- Adapter：66.56 MiB（4-bit QLoRA，可训练参数占比 1.687%）

完整报告：[`reports/eval_v2.md`](reports/eval_v2.md)

---

## 必须与上表一起读的三件事

**一、提升的主体是"学会了输出契约"，不是"变得更会选工具"。**

基座模型在**自己的原生工具格式**下，工具名选对率就有 92.38%；它在本项目自定义的四决策 JSON 契约下只有 48.88%——差距来自格式不合规，不是路由能力。knowledge 域基线 82% 的失败是把工具名填进了 `action` 字段。

微调后该指标为 97.76%，确实超过了原生格式的参照，但两者协议与难度不同，**这个对照只用于说明格式因素的量级，不足以支撑"推理能力提升"的结论**。

**二、修订带来了 2 条危险写误调用。**

中途的一次序列化修订让整体指标上升，但决策边界随之右移（`tool_call` +24 条、`clarify` −8 条），出现 2 条本该追问却直接执行退款的案例——一条臆造了 `reason` 参数，一条替用户填了 `confirmed: true`。

仍在 DoD 的 2% 阈值内，v1→v2 差值统计不显著（门控分母 n=180、2 起事件，CI [+0.0000, +0.0278] 包含 0），但这**正是本项目要防的两种行为**，因此写在这里而不是附录。详见 [`reports/eval_v2.md`](reports/eval_v2.md) 第 6 节。

**三、置信区间偏窄。**

500 条测试记录来自 **190 个 `template_key`**。bootstrap 假设样本独立，而同一模板生成的记录高度相关，有效样本量接近模板数而非记录数——上表所有区间宽度约被**低估 1.6 倍**。

---

## 怎么做到可复算

这是本项目的主要投入所在。

**冻结基线。** 训练之前先用未微调模型跑完整 500 条测试集，产出只读证据并冻结。评测运行在开始与结束时各拍一次输入快照（git commit、工作区状态、manifest 哈希、模型权重逐文件哈希），两次不一致就**拒绝发布结果**。这道门禁曾丢弃一次已完成 26 分钟推理的运行——因为运行途中有文件被改动。

**防泄漏切分。** 按 `template_key` 分组切分，六道门禁全部通过：内容哈希、规范化文本哈希、完整记录 fingerprint、模板键交集、**参数化句式交集**（把 `ORD-123456` 抹平后再比对）、4-gram 近重复。测试集中每一个模板在训练集中都未出现过。

**证据与代码绑定。** `data/manifests/split_v2.json` 由 `python -m agent_toolcall_sft.data.build` 生成，并有测试断言"仓库里的 manifest 必须等于当前代码的产物"——改了门禁却忘了重签，测试立刻变红。

**修订机会只有一次。** 允许一次基于错误分析的修订，且不得在看到测试答案后新增近似训练样本。该机会已用于序列化格式，v1 的报告与产物**原样保留、数字未重算**，两版并存以呈现修订的完整代价。

**记录被推翻的判断。** 执行修订前公开写下三条可证伪的预测，其中一条（"改格式不影响语义判断"）被结果推翻，连同其后果记录在 [`reports/eval_v2.md`](reports/eval_v2.md) 第 5 节。

---

## 数据

规则生成的中文客服语料，**不含任何真实个人信息**（固定格式 PII 全语料扫描 0 命中，订单号均为合成 `ORD-\d{6}`）。

| | 条数 | 不同 `template_key` |
| --- | ---: | ---: |
| 训练 | 2,000 | 467 |
| 验证 | 300 | 136 |
| 测试 | 500 | 190 |

- 19 个场景族，覆盖工具调用、追问、直接回答、转人工四种决策
- 测试集 knowledge 100 条 / support 400 条
- **29.2% 的样本只提供三个知识工具**，用于验证子集路由能力
- 60 条分层人工审计：0 处标签错误、4 处措辞瑕疵、7 处场景边界争议，审计局限公开记录（[`reports/data_audit_v2.md`](reports/data_audit_v2.md)）

---

## 工具契约

七个固定工具，Pydantic 判别联合，`extra="forbid"` fail-closed：

| 工具 | 类型 | 必填参数 |
| --- | --- | --- |
| `retrieval_tool` | 只读·知识 | `question` |
| `summary_tool` | 只读·知识 | `text` |
| `question_decompose_tool` | 只读·知识 | `question` |
| `get_order_status` | 只读·客服 | `order_id` |
| `check_refund_eligibility` | 只读·客服 | `order_id`、`reason` |
| `create_refund_request` | **写·危险** | `order_id`、`reason`、`confirmed` |
| `create_support_ticket` | 写·客服 | `summary` |

`create_refund_request.confirmed` 的类型是 `Literal[True]`——**"未确认"在类型层面不可表达**，而不是靠运行时检查。

前三个工具的名称与必填参数签名与 [`rag-agent-platform`](../rag-agent-platform) 的 `tools/registry.py` dispatch-compatible，有回归测试守着。

---

## 训练配置

```yaml
base_model: Qwen/Qwen3-1.7B
quantization: 4-bit NF4 + double quant, fp16 compute
lora: r=16, alpha=32, dropout=0.05
  target_modules: q/k/v/o_proj, gate/up/down_proj
data: max_seq_length 1024, loss_on assistant
training: batch 1 x grad_accum 16, 2 epochs, lr 2e-4, seed 42
```

配置由 Pydantic 严格解析（`extra="forbid"`）——YAML 写错字段名不会报错、会静默用默认值，这层校验让它在训练开始前 0.1 秒失败，而不是几小时后。

**loss 只计算助手输出。** prompt 与答案分别编码、按 token 数切分，mask 按构造成立，不依赖猜测 chat template 的标记位置。典型样本 613 token 中 583 个被 mask，30 个参与训练。

---

## 复现

需要 Linux + CUDA（`pyproject.toml` 已限定平台）与本地 Qwen3-1.7B 权重。

```bash
# 1. 重建语料与 manifest（数据不进 Git，由种子确定性生成）
uv run python -m agent_toolcall_sft.data.build

# 2. 冻结基线
uv run python -m agent_toolcall_sft.evaluation.run_baseline \
  --model <本地权重路径> --split data/processed/test.jsonl \
  --manifest data/manifests/split_v2.json --tag baseline_production_json_v2

# 3. 训练
uv run python -m agent_toolcall_sft.training.train \
  --config configs/qlora.yaml --model <本地权重路径> \
  --output-dir artifacts/checkpoints/qwen3-1.7b-toolcall-v2

# 4. 评测 Adapter（与基线同一套门禁）
uv run python -m agent_toolcall_sft.evaluation.run_adapter \
  --model <本地权重路径> --adapter artifacts/checkpoints/qwen3-1.7b-toolcall-v2/adapter \
  --split data/processed/test.jsonl --manifest data/manifests/split_v2.json \
  --tag adapter_production_json_v2

# 5. 逐样本配对结果
uv run python -m agent_toolcall_sft.evaluation.pair_report \
  --base artifacts/baseline_production_json_v2 \
  --tuned artifacts/adapter_production_json_v2 \
  --out artifacts/paired_v2/paired_results.jsonl
```

延迟不可字节复现，其余指标在同 commit、同权重、同解码配置下可复现。

`uv run pytest -q` → 407 passed。

---

## 与 `rag-agent-platform` 的关系

两个项目分层，**刻意不重复实现**：

| | `rag-agent-platform` | 本项目 |
| --- | --- | --- |
| 层次 | 应用层 | 模型层 |
| 负责 | RAG 检索、编排、可观测 | 工具路由、契约合法率、安全确认 |

本项目不实现检索链路，只复用工具契约签名。微调模型将作为可插拔 router 接入平台（`POST /v1/route` 与 `ROUTER_BACKEND` 开关，进行中）。

---

## 安全边界

- 不连接真实订单、退款或工单系统；全部为模拟 fixture
- 不发布基座权重，只发布脱敏数据与 LoRA Adapter
- 危险写工具的确认语义由类型系统保证，不依赖提示词
- 模型仍有 1.11% 的危险写误调用率，**不适用于无人工复核的自动退款场景**

---

## 报告索引

| 文件 | 内容 |
| --- | --- |
| [`reports/eval_v2.md`](reports/eval_v2.md) | 最终配对评测，含修订代价 |
| [`reports/eval_v1.md`](reports/eval_v1.md) | 修订前评测（保留，数字未重算） |
| [`reports/error_analysis_v1.md`](reports/error_analysis_v1.md) | 37 条失败的逐条归因 |
| [`reports/baseline_qwen3_1_7b_v2.md`](reports/baseline_qwen3_1_7b_v2.md) | 冻结基线（production JSON 主协议） |
| [`reports/baseline_qwen3_1_7b_native_hermes_v2.md`](reports/baseline_qwen3_1_7b_native_hermes_v2.md) | 基座原生格式路由能力参照 |
| [`reports/data_audit_v2.md`](reports/data_audit_v2.md) | 数据审计与已知边界 |
| [`ROADMAP.md`](ROADMAP.md) | 全部门禁与逐项验收记录 |

---

## 当前状态

阶段 A（数据与冻结基线）与阶段 B（QLoRA 训练）已完成，阶段 C 的配对评测与错误分析已完成。

**尚未完成：** `POST /v1/route` 推理接口、与平台的 A/B 联动、Model Card 与 Dataset Card、指标溯源文档。
