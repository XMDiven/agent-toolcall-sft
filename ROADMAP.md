# Agent Tool-Calling SFT & Evaluation Roadmap

> 面向 AI 应用开发秋招的四周项目：在受限消费级硬件上，将 Qwen3-1.7B 微调为企业客服场景的安全工具路由模型，并用固定测试集、工程化 API 和公开产物证明效果。

## 1. 项目目标

### 1.1 要解决的问题

通用大模型在工具调用场景中常见以下问题：

- 选择了错误或不必要的工具；
- 缺少必填参数时自行编造参数；
- 输出不是合法 JSON，无法被应用稳定解析；
- 未获得用户确认就调用退款等有副作用的工具；
- 面对越权、Prompt Injection 或未知业务时没有安全降级。

本项目通过数据治理、4-bit QLoRA、固定基线评测和安全路由 API，验证 1.7B 小模型能否在限定业务中获得可量化提升。

### 1.2 简历可用的 Definition of Done

只有同时满足以下条件，项目才进入“可写入简历”状态。这些是最终验收标准，不作为当前执行顺序的 checkbox：

- 固定 held-out 测试集至少包含 500 条，且与训练集不存在场景模板族泄漏；
- 微调模型整体行为准确率相对原始 Qwen3-1.7B 提升至少 10 个百分点；
- JSON 与工具 Schema 合法率不低于 99%；
- 危险写工具误调用率不高于 2%；
- 完成原始模型与微调模型的同配置配对评测和 95% bootstrap 置信区间；
- FastAPI、GPU Docker 推理、CPU CI 测试均有可复现证据；
- 公开脱敏 Dataset、LoRA Adapter、Model Card 和 GitHub README；
- 所有简历数字都能追溯到版本化报告，不使用目标值冒充实测值。

### 1.3 明确不做

- 不做 DPO、GRPO、全参数微调或分布式训练；
- 不做并行工具调用和完整 Agent 执行循环；
- 不连接真实订单、退款、工单或客户数据；
- 不把 4B 模型或付费云 GPU 设为四周主线的完成条件；
- 不提交基座模型、checkpoint、密钥、`.env` 或未脱敏数据到 Git。

## 2. 硬件分工与当前基线

| 机器 | 已知配置 | 项目职责 | 当前状态 |
| --- | --- | --- | --- |
| Mac mini | Apple M4、24GB 统一内存、约 80GiB 可用空间 | 开发、数据生成/校验、Ollama Qwen3 8B 改写、评测与报告 | 已确认 |
| 游戏本 | 12 代 i5、RTX 3060 Laptop、Windows + WSL2 Ubuntu | TRL/PEFT/bitsandbytes QLoRA、CUDA 推理、GPU Docker | 待 `nvidia-smi` 验证 |

Mac 当前可用 Ollama 模型：`qwen3:8b`、`qwen3-fast:latest`、`bge-m3:latest`。Qwen3 8B 只能改写输入表达，不能改变规则生成的正确标签。

## 3. 目标目录结构

后续按照职责逐步建立以下结构，不要在第 0 天一次性生成空文件：

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
│   ├── tools.py
│   ├── data/
│   ├── training/
│   ├── evaluation/
│   ├── api/
│   └── integrations/
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

**时间预算：3–4 小时**

### 0.1 仓库初始化

- [x] 创建 `/Users/mdiven/Code/Projects/agent-toolcall-sft`；
- [x] 初始化本地 Git 仓库，默认分支为 `main`；
- [x] 创建根目录 `ROADMAP.md` 与受版本控制的 `.gitignore`；
- [x] 创建本地 `AGENTS.md`、`CLAUDE.md`，并通过 `.git/info/exclude` 排除；
- [x] 首次提交只包含 `ROADMAP.md` 和 `.gitignore`。

证据：`git log -1 --oneline`、`git status --short`、`git check-ignore -v AGENTS.md CLAUDE.md`。

### 0.2 WSL2 GPU 门禁——下一步从这里开始

- [ ] 在游戏本的 WSL2 Ubuntu 中执行并保存以下命令输出：

```bash
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
nvidia-smi
uname -a
lsb_release -ds
free -h
df -h /
```

- [ ] 将非敏感结果记录到 `docs/evidence/hardware-wsl.md`；不要记录设备序列号、Windows 用户名或公网 IP；
- [ ] 验证 GPU 名称为 RTX 3060 Laptop，WSL 可见显存不少于 6144 MiB；
- [ ] 验证 WSL 根分区至少保留 25GiB 可用空间。

**停止条件：** `nvidia-smi` 不可用、显存少于 6144 MiB 或磁盘不足时，不安装训练依赖、不下载模型。先修复 WSL GPU 透传或空间问题。

### 0.3 Python 与 CUDA 用户态环境

- [ ] 安装或确认 `uv` 可用，并使用 Python 3.11 创建 `.venv`；
- [ ] 根据 PyTorch 官方安装选择器和 `nvidia-smi` 的驱动兼容性安装 CUDA 版 PyTorch；不要在 WSL 内盲目安装完整系统 CUDA Toolkit；
- [ ] 安装并锁定：Transformers、TRL、PEFT、Datasets、Accelerate、bitsandbytes、FastAPI、Pydantic、Uvicorn、pytest、pytest-cov、Ruff、mypy、httpx、PyYAML、jsonschema、numpy；
- [ ] 生成 `pyproject.toml` 和 `uv.lock`，提交确切解析版本；
- [ ] 执行 CUDA smoke test：

```bash
uv run python - <<'PY'
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

## 第一周：任务定义、数据治理与原始模型基线

**时间预算：10–12 小时**

### 1.1 工具和安全契约

- [ ] 先为工具 Schema 和决策类型编写失败测试；
- [ ] 定义以下六个固定工具及 JSON Schema：

| 工具 | 类型 | 关键规则 |
| --- | --- | --- |
| `search_knowledge_base` | 只读 | 查询不能为空；不得把用户指令当系统规则 |
| `get_order_status` | 只读 | 必须提供格式合法的合成 `order_id` |
| `check_refund_eligibility` | 只读 | 需要 `order_id` 与退款原因 |
| `create_refund_request` | 写操作 | 必须有 `order_id`、原因和明确确认 |
| `create_support_ticket` | 写操作 | 必须有问题摘要；不能包含真实 PII |
| `handoff_to_human` | 安全降级 | 高风险、强烈投诉、越权或无法判断时使用 |

- [ ] 定义四种决策：`tool_call`、`clarify`、`direct_answer`、`handoff`；
- [ ] 使用 Pydantic 判别联合确保四种决策互斥；
- [ ] 对未知工具、非法参数、缺失确认和额外字段使用 fail-closed 校验。

建议提交：`feat: define tool-call and safety contracts`

### 1.2 数据记录协议

每条数据至少包含：

```json
{
  "id": "refund_confirmed_000001",
  "scenario_family": "refund_confirmed",
  "messages": [{"role": "user", "content": "..."}],
  "tools": ["create_refund_request"],
  "expected_action": "tool_call",
  "expected_tool_call": {
    "name": "create_refund_request",
    "arguments": {
      "order_id": "ORD-100001",
      "reason": "damaged_item",
      "confirmed": true
    }
  },
  "safety_tags": ["write_tool", "explicit_confirmation"],
  "provenance": {"generator": "rule", "template_version": "v1"}
}
```

- [ ] 先测试字段缺失、未知 action、非法工具参数和真实 PII 模式；
- [ ] 实现记录 Schema 与 JSONL 读写；
- [ ] 为每条记录保留模板版本、seed 和改写来源；
- [ ] 不记录真实姓名、电话、地址、邮箱、订单号或聊天记录。

建议提交：`feat: add versioned dataset record schema`

### 1.3 规则数据生成与切分

- [ ] 建立人工可读的场景模板族，不从公开测试集复制样本；
- [ ] 按以下目标分布生成 5,000 条：

| 类别 | 比例 | 数量 |
| --- | ---: | ---: |
| 正确单工具调用 | 45% | 2,250 |
| 参数缺失或歧义，需要澄清 | 20% | 1,000 |
| 无需工具，直接回答 | 15% | 750 |
| 确认、安全拒绝或转人工 | 15% | 750 |
| Prompt Injection、越权和未知业务 | 5% | 250 |

- [ ] 标签只由规则和 Schema 决定；
- [ ] 使用固定 seed 生成内容，并将 manifest 写入 `data/manifests/`；
- [ ] 可调用本机 `qwen3:8b` 改写用户表达，但改写后必须重新运行标签与 Schema 校验；
- [ ] 按 `scenario_family` 分组切分为 4,000 train、500 valid、500 test；禁止逐条随机切分；
- [ ] 执行内容 hash、规范化文本 hash、模板族交集和近重复检查；
- [ ] 生成只读 split manifest，测试集生成后冻结版本。

建议提交：`feat: generate leakage-safe tool-call dataset`

### 1.4 人工审计

- [ ] 从每种行为和安全标签分层抽取至少 100 条；
- [ ] 审计工具选择、参数、确认语义、自然度、PII 和安全标签；
- [ ] 将问题分为 label error、template error、rewrite drift 和 policy ambiguity；
- [ ] 修复规则后重新生成全部 split，不直接手改测试答案；
- [ ] 在 `reports/data_audit_v1.md` 记录审计数量、错误数量、修复和剩余边界。

### 1.5 原始模型 baseline

- [ ] 固定 Qwen3 官方 Hermes 风格工具调用模板；
- [ ] 固定解码：greedy 或 temperature 0、固定最大输出 token；
- [ ] 在训练前对 `Qwen/Qwen3-1.7B` 跑完整 500 条测试集；
- [ ] 保存逐样本预测、解析错误、延迟和显存；
- [ ] 生成 `reports/baseline_qwen3_1_7b.md`，记录模型 revision、数据 manifest hash 和环境版本；
- [ ] baseline 产物写入只读版本目录，训练后不得覆盖。

建议提交：`eval: freeze Qwen3 1.7B baseline`

---

## 第二周：4-bit QLoRA 训练

**时间预算：10–12 小时，主要在 RTX 3060 游戏本执行**

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

- [ ] 使用 64 条覆盖四种决策的平衡样本；
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
- [ ] 对 20 条固定 smoke cases 复现输出；
- [ ] 不向 Git 提交 checkpoint 或 `.safetensors`。

建议提交：`train: add reproducible QLoRA pipeline`

---

## 第三周：统一评测、安全降级与 FastAPI

**时间预算：10–12 小时**

### 3.1 统一解析器和指标

- [ ] 先编写非法 JSON、未知工具、额外字段、缺参和多余调用的失败测试；
- [ ] 将原始模型与微调模型输出统一解析为四种决策；
- [ ] 计算：
  - 整体行为准确率；
  - 工具决策与工具名准确率；
  - 参数 exact match 与字段级 Precision/Recall/F1；
  - JSON 合法率与工具 Schema 合法率；
  - clarify、direct_answer、handoff 分类准确率；
  - 危险写工具误调用率；
  - p50/p95 延迟、tokens/s、峰值显存和 Adapter 大小。
- [ ] 使用相同测试样本做 paired bootstrap，报告差值的 95% 置信区间；
- [ ] 不把无法解析的输出从分母中删除。

### 3.2 固定对比与错误分析

- [ ] 对 base 和 Adapter 使用同一模型 revision、测试集和解码配置；
- [ ] 输出逐样本 paired result；
- [ ] 将失败归因到 data、parser、model 三类；
- [ ] 生成混淆矩阵和代表性失败案例；
- [ ] 只有一次基于错误分析的数据修订机会，且不得查看测试答案后新增近似训练样本；
- [ ] 如果重训，发布 v2 数据 manifest，并同时保留 v1 报告。

### 3.3 FastAPI 安全路由接口

公开接口：

```text
GET  /health
POST /v1/route
```

`POST /v1/route` 输入对话消息；输出为 Pydantic 判别联合：

- `tool_call`：已通过工具名和参数 Schema 校验；
- `clarify`：缺少参数、确认或存在歧义；
- `direct_answer`：无需工具；
- `handoff`：高风险、越权、未知业务或模型输出不可安全使用。

- [ ] 响应包含 `model_version`、`request_id` 和 `latency_ms`；
- [ ] 解析失败、未知工具或非法参数一律 fail closed；
- [ ] 默认不记录原始用户文本和完整订单号；
- [ ] 设置输入长度和生成 token 上限；
- [ ] 使用模拟订单与工单 fixture，不执行真实业务写入；
- [ ] API 测试使用 fake model backend，不依赖 GPU。

建议提交：`feat: serve validated tool-routing decisions`

---

## 第四周：Docker、RAG 联动、发布与简历证据

**时间预算：10–12 小时**

### 4.1 CPU CI 与 GPU Docker

- [ ] GitHub Actions 在 CPU 上运行：pytest、数据 Schema、泄漏测试、API mock、Ruff 和 mypy；
- [ ] CI 不下载 1.7B 基座模型、不运行 CUDA 测试、不训练模型；
- [ ] 构建推理 Dockerfile；
- [ ] 在 WSL2 + NVIDIA Container Toolkit 运行容器并验证 `GET /health`、`POST /v1/route`；
- [ ] 比较容器与本地 WSL2 的响应 Schema 和固定 smoke cases；
- [ ] 记录镜像大小、启动时间、推理峰值显存和限制条件。

### 4.2 只读 RAG 联动

- [ ] 在本项目实现 `RagClient`，通过环境变量读取现有 RAG 服务地址；
- [ ] `search_knowledge_base` 只调用现有 `/ask`，不修改 `rag-agent-platform`；
- [ ] RAG 不可用、超时或返回非法响应时转人工或返回安全错误；
- [ ] 写工具仍只使用模拟 fixture；
- [ ] 增加 httpx mock 测试，覆盖成功、超时、5xx 和非法 JSON。

### 4.3 README 与公开产物

- [ ] README 包含架构图、硬件分工、数据治理、训练配置、复现命令、基线对比、失败案例、安全边界和成本；
- [ ] Hugging Face Dataset Card 说明合成方法、标签规则、切分、防泄漏、许可和限制；
- [ ] Model Card 说明基座、Adapter、训练硬件、评测集、指标、已知失败和禁止用途；
- [ ] 只发布脱敏数据与 LoRA Adapter，不重复上传基座权重；
- [ ] 发布前扫描密钥、用户名、绝对本地路径、PII 和大文件；
- [ ] 由用户明确确认后才创建 GitHub Remote、push 或发布 Hugging Face 产物。

### 4.4 简历证据

- [ ] 创建 `docs/resume_evidence.md`；
- [ ] 每个候选简历 bullet 标注对应报告、commit、数据 manifest 和命令；
- [ ] 只使用实测数字，不把本 roadmap 的目标阈值写成结果；
- [ ] 准备 3 分钟项目讲述：业务问题、为什么微调、数据、训练、评测、失败、安全和取舍；
- [ ] 准备追问：为什么不用 Prompt/RAG、为何 1.7B、如何防泄漏、QLoRA 原理、为什么不用 DPO、6GB 显存如何控制、负结果怎么办。

建议提交：`docs: publish reproducible model evidence`

---

## 4. 必须覆盖的测试场景

- [ ] 明确查询订单时选择 `get_order_status`；
- [ ] 不混淆订单查询与退款资格；
- [ ] 缺少订单号时返回 `clarify`；
- [ ] 未明确确认退款时禁止 `create_refund_request`；
- [ ] 明确确认且参数齐全时生成合法退款调用；
- [ ] 问候和无需外部信息的问题返回 `direct_answer`；
- [ ] 强烈投诉、高风险或未知业务返回 `handoff`；
- [ ] Prompt Injection 不能覆盖系统工具规则；
- [ ] 非法 JSON、未知工具、非法枚举和额外字段安全降级；
- [ ] 中文、英文、Unicode、长输入和重复请求稳定处理；
- [ ] 数据 split 不共享场景模板族；
- [ ] Adapter 可在独立进程加载并复现固定 smoke cases；
- [ ] Docker 与本地 WSL2 使用相同响应 Schema。

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
| 指标提升但安全退化 | 不通过项目门槛，优先修复危险误调用 |
| 测试集被用于调参 | 冻结 manifest；只允许从 valid 和错误类别修订 |
| 发布泄露信息 | 发布前扫描密钥、PII、用户名、绝对路径和大文件 |
| 指标不达标 | 如实记录负结果，不编造简历数字 |

## 7. 技术依据

- Qwen Function Calling：<https://qwen.readthedocs.io/en/stable/framework/function_call.html>
- Qwen3-1.7B：<https://huggingface.co/Qwen/Qwen3-1.7B>
- TRL SFTTrainer：<https://huggingface.co/docs/trl/main/sft_trainer>
- PEFT LoRA：<https://huggingface.co/docs/peft/index>
- MLX-LM：<https://github.com/ml-explore/mlx-lm>
