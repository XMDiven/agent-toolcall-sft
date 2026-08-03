# 指标溯源

**本文件是对外声明任何数字前的唯一检查清单。** 简历、README、面试口述中出现的每一个数值，都必须能在下表中找到一行。

- 生成日期：2026-08-03
- 交付模型：`artifacts/checkpoints/qwen3-1.7b-toolcall-v2/adapter`
- 交付评测：`artifacts/adapter_production_json_v2/`

---

## 0. 最需要先记住的一件事：存在两套数字

本项目有**两版微调模型**，两版的报告都保留、都未作废：

| | v1 | v2（交付版本） |
| --- | ---: | ---: |
| 行为准确率 | 0.9260 | **0.9540** |
| JSON 合法率 | 96.20% | **100.00%** |
| Schema 合法率 | 96.00% | **99.60%** |
| 危险写误调用率 | **0.00%** | 1.11% |

**危险写那一项 v1 更好，其余 v2 更好。**

**对外只使用 v2 这一列。** 混用两列会描述出一个不存在的模型——这是本文件要防的头号错误，见第 4 节。

---

## 1. 可对外声明的指标

除非另有说明，所有数值均出自 `reports/eval_v2.md`，证据目录 `artifacts/adapter_production_json_v2/`（评测 commit `ac6dd1b5`），与基线 `artifacts/baseline_production_json_v2/`（评测 commit `3fbee664`）配对比较。

| # | 声明 | 数值 | 来源 | 报告所在 commit |
| ---: | --- | --- | --- | --- |
| 1 | 行为准确率（整体） | 0.3620 → 0.9540，95% CI [+0.5460, +0.6360] | `eval_v2.md` §3 | `2f3e95f` |
| 2 | 行为准确率（knowledge） | 0.0000 → 0.9800，CI [+0.9500, +1.0000] | `eval_v2.md` §3 | `2f3e95f` |
| 3 | 行为准确率（support） | 0.4525 → 0.9475，CI [+0.4425, +0.5475] | `eval_v2.md` §3 | `2f3e95f` |
| 4 | 危险写工具误调用率 | 17.78%(32/180) → 1.11%(2/180)，CI [−0.2222, −0.1167] | `eval_v2.md` §3、§6 | `2f3e95f` |
| 5 | JSON 合法率 | 100.00% → 100.00% | `eval_v2.md` §3 | `2f3e95f` |
| 6 | 工具 Schema 合法率 | 87.00% → 99.60%，CI [+0.0960, +0.1560] | `eval_v2.md` §3 | `2f3e95f` |
| 7 | 清单外工具调用率 | 0.20% → 0.00% | `eval_v2.md` §3 | `2f3e95f` |
| 8 | 工具名准确率 | 0.4888 → 0.9776 | `eval_v2.md` §3 | `2f3e95f` |
| 9 | 参数完全一致率 | 0.3094 → 0.9641 | `eval_v2.md` §3 | `2f3e95f` |
| 10 | 基座原生格式路由能力 | 0.9238（223 条 gold tool_call） | `baseline_qwen3_1_7b_native_hermes_v2.md` §3 | `e0df1ca` |
| 11 | 训练资源 | 6GB 显存、峰值 4.11 GiB、52 分钟、Adapter 66.56 MiB | `eval_v2.md` §7、训练报告 | `df3cc8f` |
| 12 | 可训练参数占比 | 1.687%（17,432,576 / 1,033,364,480） | ROADMAP 2.1 | `2ae5541` |
| 13 | 推理延迟 | p50 2418.18 ms、p95 4082.63 ms | `eval_v2.md` §7 | `2f3e95f` |
| 14 | 数据规模 | 2,000 / 300 / 500，793 个 `template_key` | `data_audit_v2.md` §5 | `3fbee66` |
| 15 | 测试集防泄漏 | 6 项门禁全过，`leakage_clean: true` | `data_audit_v2.md` §4 | `3fbee66` |
| 16 | 数据审计 | 60 条分层审计，0 label / 4 template / 7 policy | `data_audit_v2.md` §2 | `3fbee66` |
| 17 | PII | 全语料 2,800 条固定格式 PII 扫描 0 命中 | `data_audit_v2.md` §4 | `3fbee66` |
| 18 | 测试覆盖 | 407 passed | `uv run pytest -q` | `2f3e95f` |

---

## 2. 证据坐标

所有评测均使用同一份数据 manifest：`data/manifests/split_v2.json`，sha256 `d87bc227f632af113a1def63…`

| 运行 | 评测 commit | `predictions.jsonl` | `summary.json` |
| --- | --- | --- | --- |
| 基线（production JSON，500 条） | `3fbee664` | `c0f0a87f3ebff002…` | `f46a0fae96699a8b…` |
| 基线（native Hermes，223 条） | `3fbee664` | `cc254c6eca61d65d…` | `c3121765e80fd144…` |
| Adapter v1（500 条） | `1ccbe747` | `9c216e036de4f0dd…` | `41de9c5e1122fef7…` |
| **Adapter v2（500 条，交付）** | `ac6dd1b5` | `7df0138ecda19a3f…` | `49bb44e850e42eb1…` |

训练：

| | 训练 commit | 工作区 | 配置 sha256 | Adapter sha256 |
| --- | --- | --- | --- | --- |
| v1 | `5174e62f` | clean | `699e5ee4d0166e90…` | `12e3a9b5cefe1afe…` |
| **v2（交付）** | `ac6dd1b5` | clean | `699e5ee4d0166e90…` | `8109961df2e167f0…` |

两版训练**使用完全相同的配置文件**（哈希一致），差异仅在于 `training/formatting.py` 的序列化写法。

---

## 3. 复现命令

```bash
# 数据（确定性生成，manifest 应得到 d87bc227…）
uv run python -m agent_toolcall_sft.data.build

# 基线
uv run python -m agent_toolcall_sft.evaluation.run_baseline \
  --model <权重路径> --split data/processed/test.jsonl \
  --manifest data/manifests/split_v2.json --tag baseline_production_json_v2

# 训练（需 checkout 到 ac6dd1b5）
uv run python -m agent_toolcall_sft.training.train \
  --config configs/qlora.yaml --model <权重路径> \
  --output-dir artifacts/checkpoints/qwen3-1.7b-toolcall-v2

# 交付评测
uv run python -m agent_toolcall_sft.evaluation.run_adapter \
  --model <权重路径> --adapter artifacts/checkpoints/qwen3-1.7b-toolcall-v2/adapter \
  --split data/processed/test.jsonl --manifest data/manifests/split_v2.json \
  --tag adapter_production_json_v2
```

延迟不可字节复现；其余指标在同 commit、同权重、同解码配置下可复现。冻结评测要求工作区干净，否则拒绝发布结果。

---

## 4. 不能这样说

以下表述**均由本项目的真实数字拼装而成，但都是错的**。

### ✗ "准确率提升 59 个百分点，危险写误调用归零"

危险写归零是 **v1**，准确率 0.9540 是 **v2**。两者来自不同模型，拼在一起描述的模型不存在。

**正确说法：** 交付版本准确率 0.3620 → 0.9540，危险写误调用 17.78% → 1.11%。

### ✗ "微调让 1.7B 模型的工具路由能力提升了一倍"

提升的主体是**输出契约的遵循**，不是路由能力。基座模型在自己的原生格式下工具名准确率已有 0.9238（指标 #10）；它在本项目自定义契约下只有 0.4888，差距来自格式不合规。

**正确说法：** 微调让模型学会了本项目的四决策 JSON 契约，在此前提下工具名准确率由 0.4888 升至 0.9776；作为参照，基座模型在其原生工具格式下为 0.9238。

### ✗ "95% 置信区间 [+0.5460, +0.6360]"（不加任何限定）

500 条测试记录来自 190 个 `template_key`，bootstrap 的独立性假设不成立，**区间宽度约低估 1.6 倍**。

**正确说法：** 在上述区间后补一句"有效样本量接近 190 个模板而非 500 条记录，区间偏窄"。

### ✗ "危险写工具误调用率降到 1.11%，安全性大幅提升"

相对基线确实是显著改善，但**相对 v1 是回退**（0% → 1.11%），且那 2 条分别是臆造缺失参数、未确认即执行退款——正是本项目要防的两种行为。

**正确说法：** 相对基线由 17.78% 降至 1.11%（显著）；但相对上一版微调模型为回退，2 起案例已逐条记录在 `eval_v2.md` §6，模型不适用于无人工复核的自动退款场景。

### ✗ "参数准确率 0.9641，说明模型能准确理解用户诉求并映射到枚举值"

测试集中**只有 1 个**（抱怨 → `reason`）映射是训练未见过的（`data_audit_v2.md` §6.4），该指标主要衡量查表记忆，不是映射泛化。

### ✗ "60 条人工审计全部通过，数据质量可靠"

审计由与模板编写方**同一方**执行，仅 11 条被标记项经项目所有者复核，其余 49 条未经第二人查看（`data_audit_v2.md` §8）。

**正确说法：** 60 条分层审计发现 0 处标签错误、4 处措辞瑕疵、7 处场景边界争议；审计独立性有限，局限已公开记录。

### ✗ "模型达到生产可用标准"

尚无推理服务、无平台联动、延迟相对基线上升 84%、交付 Adapter 并非验证集最优点（`eval_v2.md` §8）。

---

## 5. 每次对外引用前的检查

1. 这个数字在第 1 节表中吗？不在就不要说。
2. 它来自 **v2** 吗？（危险写那一项尤其容易拿错。）
3. 它是否属于第 4 节列出的错误表述之一？
4. 涉及置信区间时，是否附了有效样本量的限定？
5. 涉及提升幅度时，是否说明了提升的主体是契约遵循？

---

## 6. 本文件的维护

新增任何对外声明前，先在第 1 节添加一行并填齐来源与 commit。**没有溯源行的数字不得对外使用**，包括写进简历。

若后续重新训练或重新评测，必须新增行而非修改既有行——历史数字与其证据一并保留，这是本项目从 Phase A 起就遵循的规则。
