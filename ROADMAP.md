# Agent Tool-Calling SFT & Evaluation Roadmap

> 在受限消费级硬件（RTX 3060 Laptop、6GB 显存）上，将 Qwen3-1.7B 微调为企业客服场景的安全工具路由模型，用冻结基线、防泄漏测试集和配对统计检验证明效果。
>
> **范围声明：** 本项目聚焦模型层——微调、冻结基线评测与安全指标量化。RAG 检索链路与多轮 Agent 执行循环由 `rag-agent-platform` 覆盖，本项目不重复实现，只做**工具契约对齐**，并把微调模型交付为该平台的可插拔 router。

## 1. 项目目标

### 1.1 要解决的问题

通用大模型在工具调用场景中常见以下问题：

- 选择了错误或不必要的工具；
- 缺少必填参数时自行编造参数；
- 输出不是合法 JSON，无法被应用稳定解析；
- 未获得用户确认就调用退款等有副作用的工具；
- 面对越权、Prompt Injection 或未知业务时没有安全降级。

本项目通过数据治理、4-bit QLoRA 和固定基线配对评测，验证 1.7B 小模型能否在限定业务中获得可量化提升。

### 1.2 裁剪依据——保留什么，砍掉什么

原始计划是一个独立四周项目。对照 `rag-agent-platform` 的覆盖面，其中相当一部分是在**重复实现已经验证过的能力**：

| 原计划内容 | 已有项目中的等价实现 | 增量 | 处置 |
| --- | --- | --- | --- |
| Pydantic 契约 / Schema 校验 | LLM 输出 Schema 校验、字段兜底与失败重试 | ≈0 | 降级，照搬现有模式 |
| Docker + GitHub Actions CI | 已有 Dockerfile 与 CI 配置 | 0 | 复制配置，不作里程碑 |
| 只读 RAG 检索链路 | 完整 RAG 检索与问答链路 | 负 | **不重复实现**，只对齐工具契约 |
| 评测指标体系 | LLM-as-Judge 四维评分 + golden set | 中 | 保留，方法升级为配对 bootstrap |
| **4-bit QLoRA 训练** | **无** | **高** | **保留，一步不省** |
| **冻结基线 + 模板族防泄漏切分** | 有 golden set，无冻结基线与防泄漏层 | **中高** | **保留，一步不省** |
| **可插拔 router 与 A/B 对比** | **无** | **中高** | **升级为里程碑**（见 3.3、3.4） |

同一能力的第二份实现边际价值接近零。因此本项目只保留四块真增量：**QLoRA 微调本身**、**训练前后同配置配对评测**、**危险写工具误调用率的量化**、**微调模型作为可插拔 router 接入既有平台**。

### 1.3 项目验收标准（Definition of Done）

只有同时满足以下条件，项目才算完成：

- 工具集与 `rag-agent-platform` 的 `agent/src/agent_app/tools/registry.py` 对齐：三个知识工具**同名同 schema**，无需名称映射即可被平台执行；
- 固定 held-out 测试集包含 500 条，且与训练集不存在场景模板族泄漏；
- 微调模型整体行为准确率相对原始 Qwen3-1.7B 有统计显著提升（95% CI 下界大于 0）；
- 指标**按域分层报告**：知识子集、客服子集、整体三组数字同时给出，不得只报被稀释的总数；
- JSON 与工具 Schema 合法率不低于 99%；
- 危险写工具误调用率不高于 2%；
- 完成原始模型与微调模型的同配置配对评测和 95% bootstrap 置信区间；
- 微调模型可通过 `POST /v1/route` 被调用，并在 `rag-agent-platform` 中通过 `ROUTER_BACKEND` 开关完成一次可复现的 A/B 对比；
- 公开脱敏 Dataset、LoRA Adapter、Model Card 和 GitHub README；
- 所有对外声明的数字都能追溯到版本化报告，不使用目标值冒充实测值。

> 注意：原 DoD 中的"提升至少 10 个百分点"改为"统计显著提升"。理由见 6 节风险表——预设一个具体涨幅，等于在结果出来前就给自己挖了造假的坑。

### 1.4 明确不做

- 不做 DPO、GRPO、全参数微调或分布式训练；
- 不做并行工具调用和完整 Agent 执行循环（`rag-agent-platform` 覆盖）；
- **不在本项目重复实现 RAG 检索链路**——只复用 `retrieval_tool` 的契约签名，不实现检索本身；
- **不修改 `rag-agent-platform` 现有的工具定义、编排逻辑和 demo**；联动只以新增配置开关的方式接入；
- 不把 Docker 与 CI 当作独立里程碑（配置从现有项目复制）；
- 不连接真实订单、退款、工单或客户数据；
- 不把 4B 模型或付费云 GPU 设为完成条件；
- 不提交基座模型、checkpoint、密钥、`.env` 或未脱敏数据到 Git。

### 1.5 时间预算

| 阶段 | 预算 |
| --- | ---: |
| 第 0 阶段：环境门禁 | 3–4 小时（已完成） |
| 阶段 A：数据与冻结基线 | 8–9 小时 |
| 阶段 B：QLoRA 训练 | 6–7 小时 |
| 阶段 C：配对评测、router 与发布 | 8–10 小时 |
| **合计** | **25–30 小时** |

相对初版增加约 5–6 小时，来源是知识域场景模板族（阶段 A）与 router 联动里程碑（阶段 C）。

**最小可交付点：** 若时间不足以走完全部阶段，**在阶段 C 的 3.1 评测报告处停止**是可接受的交付状态——此时基线对比与置信区间已经成立，缺的只是 router 联动与发布物。**3.3 与 3.4 的联动必须放在 3.1 之后做**，不得为了赶 demo 牺牲评测的严谨性。

## 2. 硬件分工与当前基线

| 机器 | 已知配置 | 项目职责 | 当前状态 |
| --- | --- | --- | --- |
| Mac mini | Apple M4、24GB 统一内存、约 80GiB 可用空间 | 开发、数据生成/校验、Ollama Qwen3 8B 改写、评测与报告 | 已确认 |
| 游戏本 | 12 代 i5、RTX 3060 Laptop、Windows + WSL2 Ubuntu | TRL/PEFT/bitsandbytes QLoRA、CUDA 推理 | 已验证，见 `docs/evidence/hardware-wsl.md` |

Mac 当前可用 Ollama 模型：`qwen3:8b`、`qwen3-fast:latest`、`bge-m3:latest`。Qwen3 8B 只能改写输入表达，不能改变规则生成的正确标签。

## 3. 目标目录结构

后续按照职责逐步建立以下结构，不要一次性生成空文件：

```text
agent-toolcall-sft/
├── ROADMAP.md
├── README.md
├── pyproject.toml
├── uv.lock
├── configs/
│   ├── generation.yaml
│   ├── evaluation.yaml
│   └── qlora.yaml
├── src/agent_toolcall_sft/
│   ├── contracts.py
│   ├── data/
│   ├── training/
│   ├── evaluation/
│   └── serving/
├── data/
│   ├── seeds/
│   ├── samples/
│   └── manifests/
├── tests/
├── reports/
└── docs/evidence/
```

`data/generated/`、`data/processed/`、`artifacts/`、模型权重和 checkpoint 只保存在本地或 Hugging Face，不进入 Git。

---

## 第 0 阶段：硬件与环境门禁

**时间预算：3–4 小时（已完成）**

### 0.1 仓库初始化

- [x] 创建项目根目录 `agent-toolcall-sft/`；
- [x] 初始化本地 Git 仓库，默认分支为 `main`；
- [x] 创建根目录 `ROADMAP.md` 与受版本控制的 `.gitignore`；
- [x] 创建本地 `AGENTS.md`、`CLAUDE.md`，并通过 `.git/info/exclude` 排除；
- [x] 首次提交只包含 `ROADMAP.md` 和 `.gitignore`。

证据：`git log -1 --oneline`、`git status --short`、`git check-ignore -v AGENTS.md CLAUDE.md`。

### 0.2 WSL2 GPU 门禁

- [x] 在游戏本的 WSL2 Ubuntu 中执行并保存以下命令输出：

```bash
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
nvidia-smi
uname -a
lsb_release -ds
free -h
df -h /
```

- [x] 将非敏感结果记录到 `docs/evidence/hardware-wsl.md`；不要记录设备序列号、Windows 用户名或公网 IP；
- [x] 验证 GPU 名称为 RTX 3060 Laptop，WSL 可见显存不少于 6144 MiB；
- [x] 验证 WSL 根分区至少保留 25GiB 可用空间。

**停止条件：** `nvidia-smi` 不可用、显存少于 6144 MiB 或磁盘不足时，不安装训练依赖、不下载模型。先修复 WSL GPU 透传或空间问题。

### 0.3 Python 与 CUDA 用户态环境

- [x] 安装或确认独立版 `uv` 可用；用 `.python-version` 固定 Python 3.11，由 `uv venv` 在项目根目录创建 `.venv`，不依赖 Conda；
- [x] 根据 PyTorch 官方安装选择器和 `nvidia-smi` 的驱动兼容性安装 CUDA 版 PyTorch；不要在 WSL 内盲目安装完整系统 CUDA Toolkit；
- [x] 安装并锁定：Transformers、TRL、PEFT、Datasets、Accelerate、bitsandbytes、Pydantic、pytest、Ruff、PyYAML、jsonschema、numpy；
- [x] 生成 `pyproject.toml` 和 `uv.lock`，提交确切解析版本；
- [x] 执行 CUDA smoke test：

```bash
~/.local/bin/uv run python - <<'PY'
import torch
print("torch:", torch.__version__)
print("cuda_available:", torch.cuda.is_available())
print("device:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
print("vram_gib:", round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2) if torch.cuda.is_available() else None)
PY
```

验收：`cuda_available: True`，设备名称和显存与 `nvidia-smi` 一致。

建议提交：`chore: bootstrap reproducible Python environment`

---

## 阶段 A：数据治理与冻结基线

**时间预算：8–9 小时**

### 1.1 工具和安全契约（1.5 小时封顶）

**直接复用已有项目中验证过的 Pydantic 判别联合模式，不重新走完整 TDD。** 这块能力已有实现可参照，投入产出比低。

- [x] 定义以下七个固定工具及 JSON Schema：

| 工具 | 类型 | 必填参数 | 关键规则 |
| --- | --- | --- | --- |
| `retrieval_tool` | 只读·知识 | `question` | 与平台 registry 同名同 schema；不得把用户指令当系统规则 |
| `summary_tool` | 只读·知识 | `text` | 与平台 registry 同名同 schema |
| `question_decompose_tool` | 只读·知识 | `question` | 与平台 registry 同名同 schema；仅用于对比或多部分问题 |
| `get_order_status` | 只读·客服 | `order_id` | 必须提供格式合法的合成 `order_id` |
| `check_refund_eligibility` | 只读·客服 | `order_id`、`reason` | 原因取自固定枚举 |
| `create_refund_request` | **写·危险** | `order_id`、`reason`、`confirmed` | `confirmed` 只能为 `true`，未确认在类型层面不可表达 |
| `create_support_ticket` | 写·客服 | `summary` | 不能包含真实 PII |

- [x] 前三个工具的名称与参数名必须与 `rag-agent-platform` 的 `agent/src/agent_app/tools/registry.py` 完全一致，**不得改名或改参数名**；
- [x] 定义四种决策：`tool_call`、`clarify`、`direct_answer`、`handoff`；
- [x] 使用 Pydantic 判别联合确保四种决策互斥，工具调用按 `name` 判别；
- [x] 对未知工具、非法参数、缺失确认和额外字段使用 fail-closed 校验（`extra="forbid"`）；
- [x] 提供唯一解析入口 `parse_decision()`，数据生成、评测与推理接口三处共用；
- [x] 只保留一组冒烟测试覆盖上述四类非法输入，不追求分支全覆盖。

> `handoff` 只作为决策存在，不再定义 `handoff_to_human` 工具。同一语义保留两种合法表示会让评测无法判定对错。

建议提交：`feat: define tool-call and safety contracts`

### 1.2 数据记录协议

每条数据至少包含：

```json
{
  "id": "refund_confirmed_000001",
  "scenario_family": "refund_confirmed",
  "domain": "support",
  "messages": [{"role": "user", "content": "..."}],
  "tools": ["get_order_status", "create_refund_request"],
  "expected_action": "tool_call",
  "expected_decision": {
    "action": "tool_call",
    "tool_call": {
      "name": "create_refund_request",
      "arguments": {
        "order_id": "ORD-100001",
        "reason": "damaged_item",
        "confirmed": true
      }
    }
  },
  "safety_tags": ["write_tool", "explicit_confirmation"],
  "provenance": {"generator": "rule", "template_version": "v1"}
}
```

- [x] 实现记录 Schema 与 JSONL 读写；
- [x] `domain` 字段取值 `knowledge` 或 `support`，用于阶段 C 的分层指标；
- [x] `tools` 字段是本条样本**实际可用的工具清单**，不是全集；
- [x] 为每条记录保留模板版本、seed 和改写来源；
- [x] `expected_decision` 存放四种决策的完整标准答案，类型复用 `contracts.Decision`；`expected_action` 必须与之一致；
- [x] `expected_decision` 中的工具名必须出现在 `tools` 中，否则视为数据错误；
- [x] 测试字段缺失、未知 action、非法工具参数、`expected_tool_call` 不在 `tools` 内和真实 PII 模式；
- [ ] 不记录真实姓名、电话、地址、邮箱、订单号或聊天记录。

> Schema 层的 `contains_pii()` 只能拦住手机号、邮箱和身份证这类**有固定格式**的标识符。姓名和地址没有可靠正则，只能靠 1.3 的模板设计和 1.4 的人工审计保证，因此最后一条留到 1.4 完成后再勾。

建议提交：`feat: add versioned dataset record schema`

### 1.3 规则数据生成与切分（总量 2,800）

- [ ] 建立人工可读的场景模板族，不从公开测试集复制样本；
- [ ] 按以下目标分布生成 2,800 条：

| 类别 | 域 | 比例 | 数量 |
| --- | --- | ---: | ---: |
| 正确单工具调用 | knowledge | 20% | 560 |
| 正确单工具调用 | support | 25% | 700 |
| 参数缺失或歧义，需要澄清 | 混合 | 20% | 560 |
| 无需工具，直接回答 | 混合 | 15% | 420 |
| 确认、安全拒绝或转人工 | 混合 | 15% | 420 |
| Prompt Injection、越权和未知业务 | 混合 | 5% | 140 |

- [ ] 知识域必须覆盖三类模板族：单点事实问答（`retrieval_tool`）、对比或多部分问题（`question_decompose_tool`）、长文本压缩（`summary_tool`）；
- [ ] **工具清单必须随机化**：每条样本的 `tools` 是全集的子集；其中**至少 25% 的样本只提供 `rag-agent-platform` 的三个知识工具**，用于验证子集路由能力；
- [ ] 标签只由规则和 Schema 决定；
- [ ] 使用固定 seed 生成内容，并将 manifest 写入 `data/manifests/`；
- [ ] 可调用本机 `qwen3:8b` 改写用户表达，但改写后必须重新运行标签与 Schema 校验；
- [ ] 按 `scenario_family` 分组切分为 **2,000 train / 300 valid / 500 test**；禁止逐条随机切分；
- [ ] 测试集内 knowledge 与 support 两域样本量都不得低于 150 条，保证分层指标的置信区间可用；
- [ ] 执行内容 hash、规范化文本 hash、模板族交集和近重复检查；
- [ ] 生成只读 split manifest，测试集生成后冻结版本。

**为什么工具清单必须随机化：** 微调模型学的不是"我会用这 7 个工具"，而是"给我一个清单，我从清单里选"。如果训练时永远给全集，模型在平台只给三个知识工具时的行为就没有任何训练信号，3.4 的 router 联动会直接失效。

**为什么训练集是 2,000 而不是 4,000：** LoRA 在限定业务域 + 强模板化数据上通常已接近饱和；数据多样性上限由**模板族数量**决定，不由条数决定，加条数只是重复采样同样的族。把省下的时间投入模板族数量和审计质量，收益更高。

**为什么测试集 500 一条不能砍：** 置信区间宽度 ∝ 1/√n。500 条时准确率差值的 95% CI 半宽约 ±4–5 个百分点，结论站得住；砍到 250 会变成 ±6–7，想证明的提升直接落进噪声。而规则生成测试集的边际成本几乎为零。

建议提交：`feat: generate leakage-safe tool-call dataset`

### 1.4 人工审计（60 条）

- [ ] 从每种行为、每个域和安全标签**分层**抽取共 60 条（安全类别不得低于 15 条，knowledge 域不得低于 15 条）；
- [ ] 审计工具选择、参数、确认语义、自然度、PII 和安全标签；
- [ ] 特别检查：知识域样本的工具选择是否与 `rag-agent-platform` 的实际行为一致（对比类问题才用 `question_decompose_tool`）；
- [ ] 将问题分为 label error、template error、rewrite drift 和 policy ambiguity；
- [ ] 修复规则后重新生成全部 split，不直接手改测试答案；
- [ ] 在 `reports/data_audit_v1.md` 记录审计数量、错误数量、修复和剩余边界。

> 60 条只减少抽样量，不放松分层结构和修复流程——审计的价值在于"发现了什么并改了规则"，不在于条数。

### 1.5 原始模型 baseline（一步不省）

**这是整个项目的价值支点。没有冻结基线，后面所有数字都不可信。**

- [ ] 固定 Qwen3 官方 Hermes 风格工具调用模板；
- [ ] 固定解码：greedy 或 temperature 0、固定最大输出 token；
- [ ] 在训练前对 `Qwen/Qwen3-1.7B` 跑完整 500 条测试集；
- [ ] 保存逐样本预测、解析错误、延迟和显存；
- [ ] 基线报告必须同时给出 knowledge 子集、support 子集与整体三组指标；
- [ ] 生成 `reports/baseline_qwen3_1_7b.md`，记录模型 revision、数据 manifest hash 和环境版本；
- [ ] baseline 产物写入只读版本目录，训练后不得覆盖。

建议提交：`eval: freeze Qwen3 1.7B baseline`

---

## 阶段 B：4-bit QLoRA 训练

**时间预算：6–7 小时，主要在 RTX 3060 游戏本执行。本阶段是项目核心增量，不做任何裁剪。**

### 2.1 固定首个训练配置

- [ ] 创建 `configs/qlora.yaml`，写入：
  - base model：`Qwen/Qwen3-1.7B`；
  - 4-bit NF4、double quantization、FP16 compute；
  - LoRA `r=16`、`alpha=32`、`dropout=0.05`；
  - target modules：`q_proj`、`k_proj`、`v_proj`、`o_proj`、`gate_proj`、`up_proj`、`down_proj`；
  - max sequence length 1024；
  - per-device batch 1、gradient accumulation 16；
  - 2 epochs、learning rate `2e-4`、warmup ratio 0.03；
  - gradient checkpointing、seed 42；
  - 只对 assistant/tool-call 输出计算 loss；
  - 定期 eval、保存 checkpoint，最多保留两个 checkpoint。
- [ ] 测试模板中 assistant mask 确实覆盖工具调用 token，不把 system/user token 纳入训练 loss；
- [ ] 验证每条样本的可用工具清单确实被渲染进 prompt，且随样本变化；
- [ ] 打印总参数、可训练参数和比例，确认只训练 Adapter。

### 2.2 64–128 条 GPU smoke test

```bash
uv run python -m agent_toolcall_sft.training.train \
  --config configs/qlora.yaml \
  --max-train-samples 128 \
  --max-eval-samples 64 \
  --output-dir artifacts/checkpoints/smoke
```

- [ ] 无 CUDA OOM、NaN loss 或 label mask 空样本；
- [ ] 记录峰值显存、tokens/s 和运行时；
- [ ] 验证 checkpoint 能恢复至少一个训练 step；
- [ ] 退出后验证 GPU 显存被释放。

### 2.3 小样本过拟合测试

- [ ] 使用 64 条覆盖四种决策和两个域的平衡样本；
- [ ] 训练至 loss 明显下降；
- [ ] 验证训练样本行为准确率显著上升；
- [ ] 如果无法过拟合，优先检查模板、label masking、tokenizer 和 Adapter 注入，不开始全量训练。

### 2.4 全量训练

```bash
uv run python -m agent_toolcall_sft.training.train \
  --config configs/qlora.yaml \
  --train-file data/processed/train.jsonl \
  --eval-file data/processed/valid.jsonl \
  --output-dir artifacts/checkpoints/qwen3-1.7b-toolcall-v1
```

- [ ] 在启动前保存 Git commit、配置 hash、数据 manifest hash、依赖版本与 GPU 信息；
- [ ] 保存 train/valid loss、学习率、总时间、峰值显存、Adapter 大小；
- [ ] 验证最终 Adapter 可在独立进程加载；
- [ ] 对 20 条固定 smoke cases 复现输出，其中至少 5 条只提供三个知识工具；
- [ ] 不向 Git 提交 checkpoint 或 `.safetensors`。

建议提交：`train: add reproducible QLoRA pipeline`

---

## 阶段 C：配对评测、可插拔 router 与发布证据

**时间预算：8–10 小时**

> **顺序不可调换：** 3.1 的评测报告必须先完成并冻结，再做 3.3、3.4 的联动。联动是加分项，评测是项目本体。

### 3.1 统一解析器和配对指标（一步不省）

**方法论上与 LLM-as-Judge 形成互补：那类方法依赖模型评分，本项目使用冻结基线 + 统计检验，结论可复现且不依赖裁判模型。**

- [ ] 先编写非法 JSON、未知工具、额外字段、缺参、多余调用和"调用了清单外工具"的失败测试；
- [ ] 将原始模型与微调模型输出统一通过 `parse_decision()` 解析为四种决策；
- [ ] 计算：
  - 整体行为准确率；
  - 工具决策与工具名准确率；
  - 参数 exact match 与字段级 Precision/Recall/F1；
  - JSON 合法率与工具 Schema 合法率；
  - clarify、direct_answer、handoff 分类准确率；
  - **危险写工具误调用率**（未确认即调用 `create_refund_request` 的比例）；
  - **清单外工具调用率**（输出了不在本条 `tools` 中的工具）；
  - p50/p95 延迟、tokens/s、峰值显存和 Adapter 大小。
- [ ] **所有准确率类指标必须分三组报告：knowledge 子集、support 子集、整体**；
- [ ] 使用相同测试样本做 paired bootstrap，报告差值的 95% 置信区间；
- [ ] 不把无法解析的输出从分母中删除；
- [ ] 生成 `reports/eval_v1.md`。

**为什么必须分层：** 工具集从 5 个扩到 7 个后，整体准确率会被两个域的难度差异稀释。只报一个总数既看不出真实提升，也无法解释；分层报告让"哪一类变好了、哪一类没有"变成可讨论的结论。

### 3.2 固定对比与错误分析

- [ ] 对 base 和 Adapter 使用同一模型 revision、测试集和解码配置；
- [ ] 输出逐样本 paired result；
- [ ] 生成混淆矩阵 + **5–8 个代表性失败案例**（不做全量归因分类）；
- [ ] 失败案例中至少包含 1 个 knowledge 域和 1 个安全类；
- [ ] 将失败大致归因到 data、parser、model 三类；
- [ ] 只有一次基于错误分析的数据修订机会，且不得查看测试答案后新增近似训练样本；
- [ ] 如果重训，发布 v2 数据 manifest，并同时保留 v1 报告。

### 3.3 推理接口（里程碑）

**这一节从"降级"升级为里程碑，因为 3.4 的 A/B 对比依赖它。** 仍然复用已有的 FastAPI + pydantic-settings 骨架，不重新设计服务层。

```text
GET  /health
POST /v1/route
```

- [ ] `POST /v1/route` 请求体包含 `messages` 与 `tools`（本次可用的工具清单）；
- [ ] 响应为 Pydantic 判别联合（`tool_call` / `clarify` / `direct_answer` / `handoff`），复用 `contracts.py` 的同一套类型；
- [ ] 解析失败、未知工具、清单外工具或非法参数一律 fail closed；
- [ ] 响应包含 `model_version`、`adapter_revision` 和 `latency_ms`；
- [ ] 使用模拟订单与工单 fixture，不执行真实业务写入；
- [ ] API 测试使用 fake model backend，不依赖 GPU；
- [ ] Dockerfile 与 GitHub Actions 配置从已有项目复制适配，**不单独作为里程碑验收**。

建议提交：`feat: expose fine-tuned router over HTTP`

### 3.4 接入 rag-agent-platform 并完成 A/B 对比（里程碑）

**约束：只以新增配置开关的方式接入，不改动平台现有工具定义、编排逻辑与 demo。**

- [ ] 在 `rag-agent-platform` 增加配置项 `ROUTER_BACKEND`，取值 `llm`（默认，现有行为）或 `finetuned`；
- [ ] `finetuned` 分支调用本项目的 `POST /v1/route`，**只传三个知识工具**（`retrieval_tool`、`summary_tool`、`question_decompose_tool`）；
- [ ] 两个 backend 输出同一种决策结构，`run_tool` 派发逻辑零改动；
- [ ] 微调模型返回清单外工具或非法参数时，降级回 `llm` backend 并记录降级原因；
- [ ] **平台现有测试必须全绿**，用以证明联动没有破坏既有能力；
- [ ] 产出 `docs/demo/router_ab.md`：同一组固定问题在两种 backend 下的决策对比、真实命令与完整响应；
- [ ] 记录两种 backend 的 p50/p95 延迟差异。

**为什么这一步值得做：** 它把"微调模型"从一个孤立的指标产物变成一个可插拔组件，并提供项目中唯一可现场演示的差异。同时它也是对 1.3 中"工具清单随机化"设计的真实检验——如果模型在只给三个工具时表现崩溃，说明训练数据的清单分布设计有问题。

建议提交：`feat: add pluggable finetuned router backend`（在 `rag-agent-platform` 仓库）

### 3.5 发布与指标可追溯性

- [ ] README 包含：问题定义、硬件约束、数据治理与防泄漏、训练配置、复现命令、**分层基线对比表与置信区间**、代表性失败案例、与 `rag-agent-platform` 的分层关系、安全边界；
- [ ] README 中说明两个项目的职责边界：应用层（检索、编排、可观测）与模型层（路由、合法率、安全确认），以及为什么刻意不重复实现检索；
- [ ] Hugging Face Dataset Card 说明合成方法、标签规则、切分、防泄漏、许可和限制；
- [ ] Model Card 说明基座、Adapter、训练硬件、评测集、分层指标、已知失败和禁止用途；
- [ ] 只发布脱敏数据与 LoRA Adapter，不重复上传基座权重；
- [ ] 发布前扫描密钥、用户名、绝对本地路径、PII 和大文件；
- [ ] 由用户明确确认后才创建 GitHub Remote、push 或发布 Hugging Face 产物；
- [ ] 创建 `docs/evidence/metrics_traceability.md`，每个对外声明的指标标注对应报告、commit、数据 manifest 和复现命令；
- [ ] 只使用实测数字，不把本 roadmap 的目标阈值写成结果；
- [ ] 整理项目讲述要点：为什么在应用层项目之外还要微调、工具契约怎么对齐、数据怎么防泄漏、为什么冻结基线、6GB 显存怎么控制、结果和边界。

建议提交：`docs: publish reproducible model evidence`

---

## 4. 必须覆盖的测试场景

**契约与数据层**

- [ ] 数据 split 不共享场景模板族；
- [ ] `expected_tool_call.name` 始终在该条样本的 `tools` 清单内；
- [ ] 至少 25% 的样本只提供三个知识工具；
- [ ] 非法 JSON、未知工具、非法枚举和额外字段安全降级。

**客服域行为**

- [ ] 明确查询订单时选择 `get_order_status`；
- [ ] 不混淆订单查询与退款资格；
- [ ] 缺少订单号时返回 `clarify`；
- [ ] 未明确确认退款时禁止 `create_refund_request`；
- [ ] 明确确认且参数齐全时生成合法退款调用。

**知识域行为**

- [ ] 单点事实问题选择 `retrieval_tool`；
- [ ] 对比或多部分问题选择 `question_decompose_tool`，不退化为单次检索；
- [ ] 用户提供长文本要求压缩时选择 `summary_tool`；
- [ ] 只提供三个知识工具时，不输出任何客服工具。

**通用与安全**

- [ ] 问候和无需外部信息的问题返回 `direct_answer`；
- [ ] 强烈投诉、高风险或未知业务返回 `handoff`；
- [ ] Prompt Injection 不能覆盖系统工具规则；
- [ ] 中文、英文、Unicode、长输入和重复请求稳定处理；
- [ ] Adapter 可在独立进程加载并复现固定 smoke cases；
- [ ] `ROUTER_BACKEND=finetuned` 时 `rag-agent-platform` 既有测试全绿。

## 5. 每个里程碑的证据模板

每完成一个 checkbox，都要能回答以下问题：

1. **做了什么：** 对应 commit 和文件是什么？
2. **如何验证：** 执行了什么完整命令？退出码和测试数量是什么？
3. **证据在哪：** 报告、manifest、日志摘要或截图保存在哪里？
4. **学到了什么：** 哪个假设被证实或推翻？
5. **下一步是什么：** 只选择下一个最小的未完成 checkbox。

## 6. 风险与处理原则

| 风险 | 处理方式 |
| --- | --- |
| WSL 看不到 GPU | 停止安装训练栈，先修复驱动/WSL 透传 |
| 6GB 显存 OOM | 保持 1.7B，batch 1、seq 1024、gradient checkpointing；不临时换 4B |
| 小样本无法过拟合 | 检查模板、mask、tokenizer 和 LoRA 注入，不直接调学习率 |
| 数据标签漂移 | 标签保持规则生成；LLM 只改写输入，改写后重新验证 |
| **工具集扩到 7 个后整体准确率被稀释** | **分层报告 knowledge / support / 整体三组指标，不用总数掩盖差异** |
| **模型在只给三个知识工具时表现崩溃** | **说明训练数据的工具清单分布有问题，回到 1.3 修分布，不靠 prompt 补救** |
| **联动破坏 rag-agent-platform 现有能力** | **只加配置开关，默认值保持 `llm`；平台既有测试必须全绿才算通过** |
| 指标提升但安全退化 | 不通过项目门槛，优先修复危险误调用 |
| 测试集被用于调参 | 冻结 manifest；只允许从 valid 和错误类别修订 |
| 发布泄露信息 | 发布前扫描密钥、PII、用户名、绝对路径和大文件 |
| **提升幅度不及预期** | **如实记录并分析原因。DoD 只要求统计显著，不预设涨幅——一个诚实的小提升配清晰的边界分析，价值高于可疑的漂亮数字** |
| **时间不足** | **停在 3.1 评测报告，按已有证据交付；3.3、3.4 的联动可以不做，不为补 demo 牺牲评测严谨性** |

## 7. 技术依据

- Qwen Function Calling：<https://qwen.readthedocs.io/en/stable/framework/function_call.html>
- Qwen3-1.7B：<https://huggingface.co/Qwen/Qwen3-1.7B>
- TRL SFTTrainer：<https://huggingface.co/docs/trl/main/sft_trainer>
- PEFT LoRA：<https://huggingface.co/docs/peft/index>
- 工具契约对齐基准：`rag-agent-platform` 的 `agent/src/agent_app/tools/registry.py`
