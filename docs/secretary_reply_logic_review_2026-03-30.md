# 秘书回复判断代码梳理与修复记录

## 背景

本次梳理围绕 `Secretary` 的“是否回复”决策链路展开，检查路径包括：

- `main.py`
- `roles/front_desk.py`
- `roles/secretary.py`
- `core/angel_heart_status.py`
- `core/llm_analyzer.py`
- `models/analysis_result.py`

目标是确认“秘书判断是否回复”是否存在实际漏洞，并同步完成高优先级修复。

## 原始问题

### 1. 呼唤识别来源不一致

主入口 `_should_process()` 能正确识别 `@自己`、引用自己消息等显式唤醒信号，但状态机里的 `_is_summoned()` 只依赖最新文本是否包含别名。

风险：

- 某些平台的 `message_outline` 不包含真实 `@` 语义
- 前台允许进入处理链，秘书却可能判断成“未被呼唤”
- 造成应答漏判

### 2. 分析器后置校验与提示词语义冲突

Prompt 规则要求：

- 直接点名并提出问题，必须回复
- 被追问，必须回复

但代码中的后置校验要求 `should_reply=true` 时，必须同时满足：

- `is_questioned == true` 或
- `is_interesting == true`

这会把“直接点名但不是追问”的必回场景打回成不回复。

### 3. 密集发言统计混入机器人消息

`_detect_dense_conversation()` 统计窗口消息量时没有过滤 `assistant/tool/system`，会把机器人自身消息也算入热度。

风险：

- 机器人越活跃，越容易再次触发主动介入
- 主动插话阈值被污染

### 4. 成功回复后旧决策未清理

回复成功后会释放锁、切换状态，但不会清掉 `analysis_cache` 中的一次性秘书决策。

风险：

- 后续 LLM 请求可能读到上一轮的旧决策
- 注入错误的策略和目标

## 修复方案

### 1. 前台缓存显式记录“是否直接对机器人说话”

在 `FrontDesk.cache_message()` 写入消息时同步记录：

- `is_directed_to_bot`
- `summon_source`

状态机优先读取该结构化标记，再回退到文本别名检测。

### 2. 增加 `is_directly_addressed`

在 `SecretaryDecision` 中增加结构化字段：

- `is_directly_addressed`

并同步更新提示词输出字段说明、解析逻辑和后置校验逻辑，使“直接点名”和“被追问/主动介入”成为并列的合法触发原因。

### 3. 仅统计用户消息的密集发言

在 `_detect_dense_conversation()` 中仅对 `role == "user"` 的消息计数并统计参与人。

### 4. 发送后清理一次性决策

在 `after_message_sent` 收口阶段统一清理该会话的秘书决策缓存，避免旧决策串到后续轮次。

## 本次修改影响

### 行为变化

- `@机器人` 或引用机器人消息时，更稳定地进入被呼唤链路
- “直接点名提问”不会再被分析器后置校验误伤
- 主动介入触发更保守，减少机器人自己把自己聊热的情况
- 决策注入更干净，降低跨轮次污染

### 风险说明

- 该修复未改变核心状态机结构
- 主要是补充结构化信号和收口逻辑
- 兼容旧模型输出：即使模型暂时不返回 `is_directly_addressed`，系统仍可安全回退

## 已执行检查

- `python -m compileall .`

结果：通过。

## 回归测试记录

使用环境：

- AstrBot 本机运行时：`D:\PycharmProjects\AstrBot\backend\python\python.exe`

本次回归覆盖的关键场景：

- 显式 `@机器人` 但纯文本 `outline` 不包含别名时，仍能进入 `SUMMONED`
- `is_directly_addressed=true` 时，`should_reply=true` 不会被后置校验打回
- 密集发言判断不会把 `assistant` 消息算入热度
- `after_message_sent` 后会清理一次性秘书决策缓存

结果：

- 4/4 通过

### 环境备注

在本机 AstrBot Python 环境中，导入插件时发现缺失以下依赖：

- `markdown_it`
- `mdit_plain`

它们仅影响 Markdown 纯文本清洗相关导入，不影响本次“秘书是否回复”定向回归场景。因此本次回归测试采用最小 stub 绕过，未直接修改 AstrBot 运行环境。
