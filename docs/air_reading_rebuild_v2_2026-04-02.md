# 读空气重构 V2 实施记录（2026-04-02）

## 目标

把当前“状态判断 + 读空气 + 续聊补丁 + LLM 二分类 + 后置修正”这一团逻辑拆成稳定的决策管线，减少：

- 该接话不接
- 不该接话乱接
- 旧话题串到新话题
- 日志不可解释

## 实施原则

1. 不推翻现有入口，仍由 `Secretary` 对外提供统一处理入口。
2. 新增内部结构和管线，但保留 `SecretaryDecision` 兼容字段。
3. LLM 只负责语义判断，本地规则负责最终是否回复。
4. 日志必须能解释每一步为什么放行或压制。

## 本次落地范围

- 新增线程窗口提取器
- 新增统一决策管线
- 扩展 `SecretaryDecision` 承载线程/语义/门控字段
- 调整 `LLMAnalyzer` 为语义判断优先
- 给主链路补“无上下文保护”

## 当前落地状态

### 已接入

- `core/thread_window.py` 已提供 `ThreadWindowBuilder`，负责提取最近用户 burst、上一轮助手锚点和当前线程窗口。
- `core/decision_pipeline.py` 已提供 `DecisionPipeline`，把硬放行、硬压制、LLM 复核和最终原因收口。
- `roles/secretary.py` 已接入线程窗口与决策信封，并把 `final_reason`、`thread_topic`、`followup_score` 等字段回写到 `SecretaryDecision`。
- `core/llm_analyzer.py` 已把 `addressing_mode`、`reply_value`、`needs_reply_now` 等语义字段纳入解析。
- `SUMMONED` 分支已补齐“命中本地硬压制时直接短路，不再继续调用 LLM”的收口逻辑。
- 线程窗口已改为保留“最近助手锚点之后”的多人插话消息，不再被 `latest_user_burst` 起点误裁掉。
- 决策管线已补齐“直接 summon / reply_self 优先于 command-like wake 压制”的防御性优先级。
- `DecisionPipeline.apply_llm_review()` 已补齐空线程窗口保护：当 `has_recent_context=False` 时，不再因为 `to_ai` 或高价值信号误放行，而是直接返回 `missing_recent_context`。
- `FrontDesk.rewrite_prompt_for_llm()` 已补齐“ledger 为空时回退到当前 event 构造最小上下文”的兜底，不再因为线程窗口暂缺而把自然唤醒主链整轮拦死。
- `AngelHeartContext` 的扣押超时清理已改成按 ticket / timer / event 精确匹配，不再因旧计时器取消而误删新等候牌。
- `OBSERVATION` 分支已补齐 `hard_allow` 本地短路，命中 `direct_followup` 等强放行信号时不再白跑一次 LLM。
- `FrontDesk.resume_deferred_if_any()` 已在重放前校验 ledger 中是否仍有该延后事件的未处理消息，避免“重新入队后立即无新消息”的空转。
- `ThreadWindowBuilder` 已增加 topic hint 清洗，去掉引用、@ 标记和表情占位，减少主链提示词污染。
- `ThreadWindowBuilder.thread_confidence` 已把“无 assistant 锚点”和“recent 被截断”纳入降权，线程窗口现在不再只会单向加分。
- `DecisionPipeline.apply_llm_review()` 已把低 `thread_confidence` 接入 `llm_high_value` 路径的弱保护，只压制“非 to_ai、非 hard_allow”的模糊高价值回复。

### 已完成验证

1. `tests/test_decision_pipeline.py` 覆盖硬放行、硬压制、空气分守门。
2. `tests/test_secretary_observation.py` 覆盖观测态直接续聊绕过阈值。
3. `tests/test_secretary_state_flows.py` 覆盖 `NOT_PRESENT` / `SUMMONED` / `GETTING_FAMILIAR` 三条状态支路的一致性行为。
4. `tests/test_decision_pipeline.py` 中的 `ThreadWindowBuilderTest` 已覆盖多人插话保留、旧助手锚点截断、同一发送者 burst 聚合。
5. `tests/test_decision_pipeline.py` 已覆盖 `reply_self`、`human_private_exchange`、`command_like_wake` 的组合门控优先级。
6. `tests/test_decision_pipeline.py` 已覆盖 `apply_llm_review()` 中 `followup_score`、`addressing_mode`、`reply_value`、`air_score_guard` 的交叉分支。
7. `tests/test_decision_pipeline.py` 已覆盖空线程窗口 / 无 recent context 时的本地保护分支。
8. `tests/test_front_desk_min_context.py` 已覆盖“群聊无秘书决策且 ledger 为空时，仍使用当前事件构造最小上下文”的回退链路。
9. `tests/test_decision_pipeline.py` 已覆盖“无 assistant 锚点但 recent 很长”时线程窗口只保留最后 8 条消息的截断行为。
10. `tests/test_secretary_state_flows.py` 已覆盖“旧扣押计时器取消时，不会误清理新等候牌”的竞态回归用例。
11. `tests/test_secretary_state_flows.py` 已覆盖 `OBSERVATION` 命中 `hard_allow=direct_followup` 时直接短路，不再继续调用 LLM。
12. `tests/test_front_desk_min_context.py` 已覆盖“延后消息对应的未处理上下文已消失时，前台跳过重放”的保护分支。
13. `tests/test_decision_pipeline.py` 已覆盖 topic hint 对引用、@ 标记、表情占位的清洗行为。
14. `tests/test_decision_pipeline.py` 已覆盖 `thread_confidence` 在“有锚点 / 无锚点 / 无锚点且 recent 截断”三档下的降权关系。
15. `tests/test_decision_pipeline.py` 已覆盖低 `thread_confidence` 对 `unclear + high reply_value` 的弱保护，以及 `to_ai` 对该保护的绕过。

### 故障记录

1. 2026-04-02 群聊自然唤醒故障：日志出现“无法构建最小线程上下文，阻止主链在空上下文下自由回复”。
   - 现象：用户在群里直接发起自然唤醒请求时，主链被拦截，最终空回复。
   - 根因：`rewrite_prompt_for_llm()` 只依赖 ledger 切分出的线程窗口；当 `partition_dialogue_raw()` 暂时拿不到 current event 对应的 recent 时，会把最小上下文误判为空。
   - 修复：当 ledger 线程窗口为空时，回退到当前 `event` 自身构造一条最小 recent 消息，再生成 prompt/context。
   - 回归测试：`tests/test_front_desk_min_context.py`。

2. 2026-04-03 扣押超时竞态故障：日志出现“刚发放等候牌，下一毫秒就报告等候超过15秒”的异常序列。
   - 现象：新消息刚进入等候室，就被旧计时器的取消清理误伤，表现为立即超时、延后或空转。
   - 根因：旧扣押计时器在 `CancelledError` 分支里执行全量 `_cleanup_detention_resources()`，会把已经替换成新对象的 `pending_futures` / `detention_timeout_timers` / `pending_events` 一起删掉。
   - 修复：`_cleanup_detention_resources()` 改成按 `ticket` / `timer` / `event` 精确匹配，只清理当前计时器自己持有的那一份资源。
   - 回归测试：`tests/test_secretary_state_flows.py`。

3. 2026-04-03 观测态白跑 LLM：日志显示 `DecisionGate ... hard_allow=True:direct_followup` 后仍继续调用秘书分析。
   - 现象：直追问命中本地硬放行后，仍多跑一次 LLM，增加群聊响应时延。
   - 根因：`_handle_observation_reply()` 只有 `hard_suppress` 短路，没有对 `hard_allow` 直接放行。
   - 修复：命中 `hard_allow` 时直接 `_decision_from_envelope()` 返回，不再进入 `perform_analysis()`。
   - 回归测试：`tests/test_secretary_state_flows.py`。

4. 2026-04-03 延后重放空转：日志显示延后消息重新入队后，随即落到“无新消息需要分析”。
   - 现象：同一条消息被重放回事件队列，但 ledger 中对应未处理消息已不存在，导致空转一轮并增加日志噪音。
   - 根因：`resume_deferred_if_any()` 只要取到 deferred event 就直接重放，没有先核对该事件对应的 `source_event_id` 是否仍在未处理窗口里。
   - 修复：重放前先检查 `partition_dialogue_raw()` 的 `recent_dialogue`；若已不存在对应未处理消息，则直接跳过重放。
   - 回归测试：`tests/test_front_desk_min_context.py`。

5. 2026-04-03 topic hint 污染：线程话题提示混入 `[引用消息(...)]`、`[At:...]`、`[表情:...]`。
   - 现象：线程窗口话题可读性下降，主链提示词容易被引用和占位符噪音污染。
   - 根因：`ThreadWindowBuilder` 直接拿原始文本片段作为 `thread_topic_hint`，未做消息占位清洗。
   - 修复：在 topic hint 派生阶段剥离引用、@ 标记、表情占位，并压缩空白。
   - 回归测试：`tests/test_decision_pipeline.py`。

6. 2026-04-03 线程置信度偏乐观：无助手锚点或 recent 已被截断时，`thread_confidence` 仍然可能维持偏高。
   - 现象：线程窗口明明只拿到尾部片段，日志中的 `thread_confidence` 却主要由消息数量堆高，不利于后续把它接入门控。
   - 根因：旧实现只有累加项，没有把“缺少 assistant 锚点”和“窗口被截断”当成负信号。
   - 修复：新增降权项，命中无锚点时主动减分，命中 recent 截断时继续减分。
   - 回归测试：`tests/test_decision_pipeline.py`。

7. 2026-04-03 模糊高价值误放行风险：线程置信度很低时，`unclear + high reply_value` 仍会直接走 `llm_high_value` 放行。
   - 现象：线程窗口只拿到尾部片段、又没有明确指向 AI 时，LLM 的高价值判断仍可能推动误接话。
   - 根因：`DecisionPipeline` 之前没有消费 `thread_confidence`，导致低质量线程和高质量线程在 `llm_high_value` 分支里权重一致。
   - 修复：仅在 `llm_high_value` 分支增加 `thread_confidence_guard`，低置信度时回退到继续观察；`to_ai`、`hard_allow` 不受影响。
   - 回归测试：`tests/test_decision_pipeline.py`。

### 当前收口项

1. 测试基线已统一到包路径导入，并补了最小依赖桩，后续新增测试应复用同一入口。
2. 状态支路的本地短路顺序已基本统一，后续重点应放在线程窗口截断和门控细节，而不是再回到旧的后置补丁模式。
3. 文档需要持续记录“已实现 / 未实现 / 阻塞项”，否则后续开发容易误判完成度。
4. 当前这一轮已对 `DecisionPipeline` / `ThreadWindowBuilder` 做代码收口，主要统一 helper 与常量，未新增额外门控语义。

### 下一步建议

1. 继续观察线上日志里 `thread_confidence_guard` 的命中频率，确认它没有把真正有价值的模糊追问压掉。
2. 如果命中质量稳定，再考虑是否让低 `thread_confidence` 轻微影响 `reply_value=medium` 一类边界场景。
3. 暂时不建议把 `thread_confidence` 升级成新的硬压制来源。

## 暂不处理

- 外部记忆插件的检索策略
- AstrBot 主链路本体的唤醒逻辑
- 历史记忆数据库结构迁移
