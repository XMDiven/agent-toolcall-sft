# 发布前扫描

ROADMAP 3.5 要求发布前扫描密钥、用户名、绝对本地路径、PII 和大文件。本文件记录扫描范围、发现与处置。

- 日期：2026-08-03
- 扫描范围：Git 跟踪的全部文件，**93 个、713.1 KB**
- 结论：**未发现密钥、第三方 PII 或大文件**；发现 12 处本机绝对路径，其中 1 处已修复、11 处经判断保留

> **时机说明：** 本扫描在仓库已推送至 GitHub 之后执行，晚于它应有的时点。正确顺序是首次 push 之前扫一遍。记录于此以免下次重蹈。

---

## 1. 扫描项与结果

| 项 | 命令 | 结果 |
| --- | --- | --- |
| API key / token / password | `git grep -Ei "(api[_-]?key\|secret\|token\|password\|bearer)[\"' ]*[:=][\"' ]*[A-Za-z0-9_-]{16,}"` | **0 命中** |
| `sk-` / `hf_` / `ghp_` 前缀 | `git grep -E "\b(sk-\|hf_\|ghp_)[A-Za-z0-9]{20,}"` | **0 命中** |
| 被跟踪的 `.env` / `.pem` / `.key` | `git ls-files \| grep -iE "\.env\|\.pem\|\.key\|credentials"` | **0 个** |
| 大文件 | `git ls-files -z \| xargs -0 ls -l` | **无 > 200 KB**；最大为 `uv.lock` 76.5 KB |
| 固定格式 PII | 手机号 / 邮箱 / 身份证正则 | 仅测试固件，见 2.1 |
| 本机绝对路径 | `git grep -E "/Users/mdiven\|/home/mdiven"` | **12 处、7 个文件**，见 2.2 |

模型权重、checkpoint、Adapter、生成数据均由 `.gitignore` 排除，`artifacts/` 下 1.3 GiB 产物无一进入版本控制（逐个 `git check-ignore` 确认）。

---

## 2. 发现与处置

### 2.1 PII 正则命中：全部为测试固件，保留

```
tests/test_contracts.py:86   "请联系 13800138000"
tests/test_contracts.py:88   "身份证是 11010119900307561X"
```

这些是**用来验证 PII 拦截器确实会拒绝**的样本，均为公开的示例号码，不对应任何真实个人。移除它们会使 `test_support_ticket_summary_rejects_real_pii` 失去意义。

`ROADMAP.md` 中另有一处命中，是训练 loss 数值 `3.9216105937957764` 被身份证正则误匹配，非 PII。

**处置：保留。**

### 2.2 本机绝对路径：1 处修复，11 处保留

12 处路径均为 `/home/mdiven/models/Qwen3-1.7B` 形式，暴露的是本机用户名 `mdiven`。

**已修复（1 处）—— 测试代码中的硬编码路径：**

```python
# 修改前
REAL_MODEL = Path("/home/mdiven/models/Qwen3-1.7B")

# 修改后
REAL_MODEL = Path(os.environ.get("QWEN3_MODEL_PATH", "/home/mdiven/models/Qwen3-1.7B"))
```

原写法使两条依赖真实权重的测试在任何其他机器上永久跳过。改为可覆盖后实测有效：默认情况下 `419 passed, 2 skipped`；设置 `QWEN3_MODEL_PATH` 指向本地权重后 `tests/test_formatting.py` 由 7 passed + 2 skipped 变为 **9 passed**。

**保留（11 处）—— 冻结证据中的溯源记录：**

| 文件 | 处数 |
| --- | ---: |
| `reports/baseline_qwen3_1_7b_v2.md` | 2 |
| `reports/baseline_qwen3_1_7b_native_hermes_v2.md` | 2 |
| `reports/baseline_qwen3_1_7b_summary.json` | 1 |
| `reports/eval_v1.md` | 2 |
| `docs/evidence/deployment_parity.md` | 2 |
| `docs/superpowers/plans/2026-08-02-phase-a-v2-evidence-repair.md` | 2 |

**不清洗的三条理由：**

1. **它们属于冻结证据。** 本项目自 Phase A 起的规则是 v1 指标不得重算、冻结报告不得改动。为观感修改冻结文件，会削弱这条规则本身的可信度——今天能为路径改，明天就能为数字改。
2. **路径是溯源的一部分。** 它记录了评测实际使用的权重文件位置，与 `metadata.json` 中的逐文件哈希共同构成"这次跑的是什么"的完整记录。替换成占位符会降低可追溯性。
3. **暴露面极小。** 泄露的仅是本机用户名 `mdiven`，而仓库所有者的 GitHub 用户名为 `XMDiven`，本就公开。不涉及主机名、内网 IP、序列号或凭据。

**处置：记录而不清洗。** 若后续决定公开发布 Hugging Face 产物且认为该暴露不可接受，正确做法是在**新的**发布物中使用占位路径，而不是回头改冻结报告。

---

## 3. 本次扫描未覆盖的内容

1. **Git 历史。** 只扫描了当前工作树的跟踪文件。历史提交中若曾短暂包含敏感内容，本扫描不会发现。
2. **姓名与地址。** 无可靠正则，依赖 `reports/data_audit_v2.md` 第 8 节记录的 60 条逐条审计，且该审计独立性有限。
3. **`artifacts/` 下的本地产物。** 它们不进版本控制，因此不在扫描范围；若将来手动上传其中任何文件，需单独扫描。
4. **另一仓库。** `rag-agent-platform` 的联动改动不在本次范围内。

---

## 4. 后续发布前必须重跑

若决定发布 Hugging Face Dataset 或 Adapter，发布前须重跑本文件第 1 节的全部命令，并额外检查：

- 待上传的数据文件中不含真实订单号、姓名、地址（本项目语料为规则生成，订单号均为合成 `ORD-\d{6}`）
- Adapter 目录中的 `training_args.bin` 是否包含本机路径（该文件由 Transformers 序列化训练参数，可能嵌入 `output_dir` 等路径）
- 不上传基座权重

**创建 GitHub Remote、push 或发布 Hugging Face 产物，均需项目所有者明确确认后执行。**
