# Qwen3-1.7B 基线 v1 更正说明

- 状态：v1 证据不可变，保留为历史记录；它已被 Phase A v2 证据流程取代，不再作为主 baseline 或训练前后配对结论的依据。v2 证据尚未重新完成，因此当前不能宣称 Phase A 通过。
- 适用范围：本说明只更正对 v1 结果的解释，不修改 `reports/baseline_qwen3_1_7b.md`、其汇总 JSON、v1 数据 manifest 或审计文件，也不重算 v1 指标。
- 冻结后改动记录：`reports/baseline_qwen3_1_7b.md` 在冻结（`a65c8f7`）之后被改动过一次（`f411b31`），内容是补充危险写误调用率的第二个分母口径。该次改动使用同一份 `predictions.jsonl`（sha256 未变），未重跑模型、未重算任何已有指标；文件内第 4.3 节已就地说明。除此之外，v1 证据未再改动。

## 自定义 envelope 限制与模型行为

v1 使用项目自定义的四决策 JSON envelope。64 个失败样本的首个 Schema 错误是外层 `action` 写成了工具名，而不是固定值 `tool_call`。这说明 v1 会把一部分“嵌套工具调用已有可用信号、但外层 envelope 不合约”的输出计为失败；它衡量的是该 production JSON 契约下的端到端结果，不能等同于 Qwen3 原生 Hermes 工具调用能力。

但这 64 个样本也不能全部解释为纯格式错误。对冻结预测只做一个反事实改动——把外层 `action` 改为 `tool_call`，其他输出保持不变——结果如下：

| 反事实检查 | 数量 |
| --- | ---: |
| outer-action failures | 64 |
| 仅更正 outer `action` 后通过完整 Schema | 52 / 64 |
| 相对 gold 工具名正确 | 50 / 64 |
| 相对 gold 参数 exact match | 27 / 64 |

因此，outer-action 是首个报告错误，不代表不存在工具选择或参数错误；该反事实仅用于区分 envelope 服从与模型行为，不替换 v1 冻结指标。

## 指标术语更正

v1 报告中的“整体行为准确率”实际对应 `action_accuracy`：只判断四类外层 action 是否匹配。后续报告将把它明确称为“四分类 action 准确率”，并另以 `behavior_accuracy` 表示端到端正确性：非工具决策要求 action 正确，工具调用还必须同时满足 action、工具名和完整参数正确；不可解析或 Schema 非法输出始终计错。

## 后续证据

Phase A v2 将分别报告：

1. 覆盖全部 500 条测试记录的 production JSON 主 baseline，用于后续 base 与 Adapter 的配对比较；
2. 只覆盖 gold `tool_call` 子集的 native Hermes 辅助 baseline，用于衡量基座模型原生工具路由能力。

两种协议的结果不会混合，也不会用辅助 Hermes 结果替代 production `behavior_accuracy` 主结论。
