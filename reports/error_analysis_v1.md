# 错误分析 v1 —— 微调 Adapter 在冻结测试集上的 37 条失败

- 日期：2026-08-03
- 配对结果：`artifacts/paired_v1/paired_results.jsonl`（500 行，逐样本）
- 对照报告：`reports/eval_v1.md`

## 1. 配对迁移总览

| 迁移 | 条数 | 含义 |
| --- | ---: | --- |
| `fixed` | **296** | 基线错、微调对 |
| `both_correct` | 167 | 两边都对 |
| `both_wrong` | 23 | 两边都错 |
| `broken` | **14** | **基线对、微调错** |

净改善 296 − 14 = 282 条 = 56.4%，与 `behavior_accuracy` 配对差值 +0.5640 一致。

配对由 `record_id` 精确 join，两侧记录集合不一致时直接拒绝——用错位或缺行的两次运行也能拼出一张像模像样的表，而它报出的差值不是设计要测的那个。

## 2. 前提：所有测试模板在训练中均未出现

抽查 8 条失败样本的 `template_key`，**全部 `训练见过: False`**。这是切分设计的必然结果（`template_key` 不跨 split），意味着 500 条测试记录考的都是没见过的措辞。

因此 0.9260 是泛化表现，不是记忆复现。

## 3. 三类归因

| 归因 | 条数 | 占比 |
| --- | ---: | ---: |
| **序列化**（训练目标的 JSON 分隔符） | 19 | 51% |
| **model**（未见措辞上的泛化不足） | 10 | 27% |
| **data**（标签/策略本身有争议） | 8 | 22% |
| **parser** | **0** | — |

**parser 类为 0**：全部 37 条中，解析器的判定均正确——非法 JSON 确实非法，Schema 拒绝的确实不合契约，没有一条是解析器误判。

## 4. 序列化类（19 条，51%）—— 微调引入的回退

19 条 JSON 非法全部是同一缺陷：`":"` 写成 `:"`。**其中 11 条属于 `broken`——基线原本答对，微调把它弄错了。**

对照同一条记录的两次输出：

```
record  order_status_lookup_000013   期望 tool_call

base    {"action": "tool_call", "tool_call": {"name": "get_order_status",
         "arguments": {"order_id": "ORD-303436"}}}                        ← 正确

tuned   {"action":"tool_call","tool_call":{"arguments":{"order_id:"ORD-303436"},
         "name":"get_order_status"}}                                      ← JSON 非法
```

**关键观察：基座模型天然输出带空格的 JSON**（`", "` 与 `": "`），这种写法根本不产生那对易混 token。训练目标使用了紧凑分隔符 `(",", ":")`，把模型从一个它本来就安全的格式，教到了一个它无法稳定产出的格式上。

分词层面：`":"` 与 `:"` 在 Qwen3 词表中各是一个独立 token，两串输出 token 数相同（29），仅一个位置不同。改用 `(", ", ": ")` 后同一目标被切为 `'":'` + `' "'`，**完全不含这对 token**，代价是长度 +24%（29 → 36 token）。

分布：`order_status_lookup` 18/30（60%）、`refund_eligibility_check` 1/31。出错的键全部是 `order_id`。

## 5. model 类（10 条，27%）—— 未见措辞上的泛化不足

### 代表案例一：参数就在句子里，模型却去要参数

```
record  order_status_lookup_000010   期望 get_order_status{order_id}
用户    订单 ORD-696320 是不是异常了？
可用    ['get_order_status', 'create_refund_request']
输出    {"action":"clarify","question":"请提供需要处理的订单号。"}
```

订单号明确在句中，模型仍退回追问。同族另外 5 条同样失败。

**原因可查**：`order_status_lookup:订单 {order_id} 是不是异常了？` 这个 `template_key` 只在测试集出现（训练集含该措辞的模板数为 **0**）。训练集的 30 个该族模板全部是直接查询式——"到哪了""什么时候出库""走到哪一站了"。"是不是异常了"问的是**有没有问题**，模型未能把它归入状态查询。

这是防泄漏切分设计要测的东西：模型学到的是措辞模式，不是意图。

### 代表案例二（knowledge 域）：单点事实误判为对比问题

```
record  kb_lookup_000095   期望 retrieval_tool
用户    你好，预约配送可以选时间段吗？
输出    {"action":"tool_call","tool_call":{"arguments":{"question":"预约配送可以选时间段吗"},
         "name":"question_decompose_tool"}}
```

参数完全正确，只是选了拆解工具而非检索工具。`reports/data_audit_v2.md` 第 3.3 节已记录这条边界很细。

### 代表案例三：退回基座模型的旧缺陷

```
record  ticket_creation_000014   期望 create_support_ticket
输出    {"action":"create_support_ticket","tool_call":{"arguments":{...},
         "name":"create_support_ticket"}}
```

把工具名填进 `action` 字段——正是基线 65 条 Schema 错误里占 64 条的那个缺陷。微调后全测试集仅剩 **1 条**。

## 6. data 类（8 条，22%）—— 标签本身可争议

### 代表案例四（安全类）：转人工的门槛

```
record  strong_complaint_000132   期望 handoff
用户    这次的经历让我非常愤怒。
输出    {"action":"direct_answer","answer":"我非常抱歉，如果您有进一步的问题或需要帮助，
         请随时告诉我。"}
```

同族另一条（`strong_complaint_000018`）的输出是"理解您的情绪，如果需要我可以帮您记录并转交人工"——**已经提出转人工**，但因 action 不是 `handoff` 而计错。

`reports/data_audit_v2.md` 第 3.4 节在审计时就标记过：该族内升级强度不均，"这次的经历让我非常愤怒"只表达情绪，没有索赔、升级或诉讼信号，标 `handoff` 可辩护但不唯一。**审计的预判在测试集上被验证。**

### 代表案例五：direct_answer 与 clarify 的边界

```
record  greeting_000134   期望 direct_answer「您请讲，我在听。」
用户    嗨，想咨询个事。
输出    {"action":"clarify","question":"请说明具体问题是什么。"}
```

两个回答语义几乎等价。把"您请讲"判为 `direct_answer`、"请说明具体问题"判为 `clarify`，区分依据薄弱。

### 代表案例六：抱怨到 reason 的映射歧义

```
record  refund_confirmed_000149   期望 reason=quality_issue
用户    确认发起退款。订单号是 ORD-185870，拉链拉了两次就坏了。
输出    reason=damaged_item（其余参数全对）

record  refund_eligibility_check_000071   期望 reason=quality_issue
用户    订单号 ORD-929857，屏幕有一片坏点，退款政策上支持吗？
输出    reason=damaged_item（其余参数全对）
```

"拉链两次就坏"与"屏幕坏点"归入质量问题还是商品损坏，两种判断都能成立。`reports/data_audit_v2.md` 第 6.4 节记录过：测试集中仅 1 个（抱怨 → `reason`）映射为训练未见，该指标主要衡量查表记忆——**这两条正是那种边界**。

### 代表案例七：能力问答依赖未在提示词中的业务知识

```
record  capability_question_000052   期望 direct_answer「我不提供比价服务，价格以商品页为准。」
用户    打扰一下，你能帮我比价吗？辛苦。
可用    ['summary_tool', 'retrieval_tool', 'question_decompose_tool']
输出    {"action":"clarify","question":"请提供需要比价的具体商品或服务信息。"}
```

标准答案编码了"本系统不提供比价服务"这一业务事实，而该事实既不在系统提示词中，也无法从可用工具清单推出。模型无从知晓。同族 3 条全部失败（另两条分别输出 `clarify` 与 `handoff`）。

## 7. 唯一一次数据修订的建议

ROADMAP 3.2 规定只有一次基于错误分析的修订机会，且不得在查看测试答案后新增近似训练样本。

**建议将其用于序列化格式，把训练目标的 JSON `separators` 由 `(",", ":")` 改为 `(", ", ": ")`。**

理由：

1. **覆盖面最大。** 19/37 = 51% 的失败源于此，其中 11 条是微调引入的净回退。
2. **是唯一未达标 DoD 项的直接成因。** 合法率 96.2% / 96.0% 对 99% 的缺口，全部由这 19 条构成；修复后理论上限为 100%（19 条全部消除）。
3. **不是基于测试答案的样本增补。** 改的是标准答案的序列化写法，不新增、不删除、不改变任何一条数据的语义标签，测试集不动。
4. **有直接证据支持，不是猜测。** 基座模型本就输出带空格 JSON 并因此全部正确；分词实测确认新写法不含易混 token。
5. **其余两类不适合花这次机会。** model 类（10 条）需要更多模板族而非修订，属于扩数据；data 类（8 条）在审计阶段已判定为已知边界并明确记录"不修，写进报告"。

代价：输出长度 +24%（延迟进一步上升）、重训约 52 分钟、重评约 26 分钟。

**执行前提：** 修订后必须发布 v2 数据 manifest 与新的训练 provenance，**并同时保留本报告与 `reports/eval_v1.md`**（ROADMAP 3.2 要求）。v1 的数字不得重算、不得覆盖。

## 8. 不建议修的项

- **model 类的 10 条**：反映的是模板族数量不足，不是规则错误。真正的处置是扩充 `order_status_lookup` 等族的措辞多样性，属于数据扩展而非"修订"，且会使 v1 与 v2 的数据规模不可比。
- **data 类的 8 条**：`reports/data_audit_v2.md` 第 6 节已将其登记为已知边界并明确"不修，公开记录"。在看到测试集表现之后回头修改这些标签，正是 ROADMAP 反复禁止的行为。

## 9. 结论

37 条失败中，51% 由训练目标的序列化格式引起且属微调引入的回退，27% 是未见措辞上的泛化不足，22% 是数据审计阶段已登记的标签边界，解析器误判为 0。

序列化问题是唯一同时满足"覆盖面最大""直接阻塞 DoD""不涉及测试答案"三项的候选，建议将唯一一次修订机会用于此处。
