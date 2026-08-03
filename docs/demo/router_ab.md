# Router A/B：`llm` vs `finetuned`

同一组固定问题、同一个平台、同一条派发链路，只切换 `ROUTER_BACKEND`。

- 日期：2026-08-03
- 模型层：`agent-toolcall-sft` @ `6f4ce27`，合并模型 `qwen3-1.7b-toolcall-v2-merged`，adapter `8109961df2e1`
- 应用层：`rag-agent-platform`，LLM backend 为 `kimi-k2.6`
- 结果数据：12 条问题 × 2 个 backend，0 次调用失败

---

## 1. 接入方式：只加开关，不改编排

平台侧改动共 2 个文件、35 行新增、1 行删除：

| 文件 | 改动 |
| --- | --- |
| `rag/src/rag_app/config/config.py` | 新增 `router_backend`（默认 `llm`）与 `finetuned_router_url` |
| `agent/src/agent_app/orchestration/planner.py` | 新增 `_select_tool()` 按开关分派，原 `plan_tool` 逻辑不变 |
| `agent/src/agent_app/orchestration/finetuned_router.py` | 新增，HTTP 调用与决策翻译 |

**未触碰**：工具定义（`tools/registry.py`）、工具派发（`run_tool`）、demo、前端。两个 backend 返回同一个 `ToolSelection`，下游零改动。

新 backend 用标准库 `urllib` 而非 HTTP 客户端库——一次 POST 不值得给平台引入运行时依赖。

**平台既有测试：253 → 267 passed，全绿**（+14 为本次新增的开关与降级测试）。

启动模型服务：

```bash
PYTHONPATH=src python -m agent_toolcall_sft.serving.serve \
  --model ~/models/qwen3-1.7b-toolcall-v2-merged --device mps --port 8000
```

模型与平台同在 Mac 上，无需 SSH 隧道。

---

## 2. 决策对比（12 条固定问题）

| 类型 | 问题 | `llm` | `finetuned` | |
| --- | --- | --- | --- | :-: |
| 单点事实 | 什么是向量检索？ | `retrieval_tool` | `retrieval_tool` | = |
| 单点事实 | RAG 的召回率怎么衡量？ | `retrieval_tool` | `retrieval_tool` | = |
| 单点事实 | 重排序模型的作用是什么？ | `retrieval_tool` | `retrieval_tool` | = |
| 对比 | 稠密检索和稀疏检索有什么区别？ | `retrieval_tool` | **`question_decompose_tool`** | ≠ |
| 对比 | 对比一下 MMR 和相似度检索的取舍。 | `question_decompose_tool` | `question_decompose_tool` | = |
| 对比 | 预约维修和到店维修等待时间差多少？ | `question_decompose_tool` | `question_decompose_tool` | = |
| 长文压缩 | 帮我总结一下这段：客服系统支持工作日…… | `summary_tool` | `summary_tool` | = |
| 长文压缩 | 把下面这段提炼成要点：上门取件…… | `summary_tool` | `summary_tool` | = |
| 边界 | 混合检索的权重应该怎么调？ | `retrieval_tool` | **`question_decompose_tool`** | ≠ |
| 边界 | 分块大小和重叠对效果的影响是什么？ | `retrieval_tool` | **`question_decompose_tool`** | ≠ |
| 边界 | 比较一下 BM25 和 embedding 在中文上的表现。 | `question_decompose_tool` | `question_decompose_tool` | = |
| 边界 | 把这段话缩短：向量数据库用于存储和检索高维向量。 | `summary_tool` | `summary_tool` | = |

**一致 9/12。三条分歧全部同向：微调模型选了拆解，LLM 选了检索。**

### 三条分歧怎么看

**没有标准答案。** 这 12 条问题问的是 RAG / 检索概念，而微调模型的训练语料是电商客服——**完全在分布之外**。因此本节只描述行为差异，不判定对错。

在此前提下：

- **"稠密检索和稀疏检索有什么区别？"** 句中有两个具名对象、问的是差异。按本项目训练时的标注规则（点名两个具名对象即用拆解），**微调模型的选择与自己的训练规则一致**，LLM 的选择反而偏离了该规则。
- **"分块大小和重叠对效果的影响是什么？"** 同样涉及两个对象（分块大小、重叠），拆解可辩护。
- **"混合检索的权重应该怎么调？"** 单一主题、无对比意图。这条**看起来是微调模型过度触发了拆解**，是三条里最站不住的一条。

这与 `reports/data_audit_v2.md` 第 3.3 节记录的边界一致：对比与单点的区分依据很细，模型倾向于在含多个名词时选拆解。

---

## 3. 延迟

| backend | p50 | p95 | 均值 |
| --- | ---: | ---: | ---: |
| `llm`（kimi-k2.6，远程 API） | 2159.54 ms | 2674.92 ms | 1982.41 ms |
| `finetuned`（本地 M4，MPS） | **2677.16 ms** | **3363.44 ms** | 2714.39 ms |

**本地 1.7B 模型比远程 API 更慢。** p50 高约 24%，p95 高约 26%。

这是个反直觉但真实的结果，原因是两边的瓶颈不同：远程 API 有网络往返但跑在数据中心 GPU 上；本地模型省掉网络，却受限于 M4 的推理速度和未优化的 HuggingFace `generate` 循环。

**本次联动没有带来延迟收益。** 微调模型的价值在于契约合法率与危险写安全性（见 `reports/eval_v2.md`），不在速度。

---

## 4. 降级验证

停掉模型服务，用 `ROUTER_BACKEND=finetuned` 发起一次请求：

```
WARNING agent.router_backend degrade backend=finetuned error_type=HTTPError
降级后结果: retrieval_tool | reason: llm selected tool via native tool calling
耗时 2181 ms
```

**平台正常返回结果，没有报错。** 降级路径：`finetuned` → `llm` → 规则。三级中任意一级失败都会落到下一级。

降级原因写入日志（`backend=finetuned error_type=...`），运维可据此区分两个 backend 在生产中的表现。

以下情况均触发降级，由 `agent/tests/test_finetuned_router.py` 覆盖：

- 服务不可达或超时
- 返回非工具决策（`clarify` / `direct_answer` / `handoff`）——平台没有对应派发路径
- 返回清单外工具
- 响应体结构不符合预期

---

## 5. 复现

```bash
# 1. 启动模型服务（agent-toolcall-sft）
PYTHONPATH=src python -m agent_toolcall_sft.serving.serve \
  --model ~/models/qwen3-1.7b-toolcall-v2-merged --device mps --port 8000

# 2. 平台侧切换 backend（rag-agent-platform）
#    在 rag/.env 中设置，或运行时改 config.ROUTER_BACKEND
ROUTER_BACKEND=finetuned uv run python -c "
from agent_app.orchestration.planner import plan_tool
print(plan_tool(question_type='factual', question='什么是向量检索？'))
"

# 3. 平台既有测试必须全绿
uv run pytest -q
```

逐条结果保存在本次运行的 `/tmp/router_ab.json`（含每条的 backend、工具、reason、延迟）。

---

## 6. 限制

1. **问题集在训练分布之外。** 12 条问题是 RAG / 检索概念，微调模型训练于电商客服语料。本节的一致率不代表任何一方更准确。
2. **无标准答案。** 三条分歧未经独立标注判定对错。
3. **样本量小。** 12 条不足以给出有意义的置信区间；这是演示，不是评测。真正的评测在 `reports/eval_v2.md`（500 条冻结测试集）。
4. **仅覆盖三个知识工具。** 平台只派发这三个，微调模型的客服工具与安全确认能力在本次联动中未被使用。
5. **延迟受本机状态影响**，不可字节复现。
6. **服务需手动启停**，未做进程守护，占用约 3.4 GiB 内存。
