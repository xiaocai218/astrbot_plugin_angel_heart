# 观测状态回复阈值设计记录

## 背景

当前会话进入 `OBSERVATION` 后，只要来了新消息，秘书就会重新分析一次。

这会带来两个问题：

- 观测期内介入频率偏高
- 看起来像“进了观测状态后几乎每条都要回”

## 目标

为 `OBSERVATION` 状态增加一个独立阈值：

- 未达到阈值时，仅继续观察，不触发正式分析
- 达到阈值后，再进入秘书分析链路

这样可以让群聊介入节奏更稳，不会因为观测态而显得过于活跃。

## 新增配置

- `observation_min_messages`

含义：

- 观测状态下，至少累计多少条未处理用户消息后，秘书才开始重新分析

建议值：

- `2`：更克制，避免“每条都回”
- `3`：更保守，适合高活跃群

## 设计原则

### 1. 只影响 `OBSERVATION`

以下状态不受影响：

- `SUMMONED`
- `GETTING_FAMILIAR`
- `NOT_PRESENT`

尤其是被点名/被呼唤，仍然优先处理。

### 2. 未达阈值时不标记已处理

这样消息会继续累积。
等累计达到阈值时，秘书拿到的是完整的最近一段未处理上下文，而不是被提前吞掉。

### 3. 只统计用户消息

阈值统计排除：

- assistant
- tool
- system

避免机器人自己的消息把阈值顶满。

## 回归关注点

- 观测状态下只有 1 条用户消息时，不应触发分析
- 观测状态下累计达到阈值时，应恢复正常分析
- 被呼唤消息不应被阈值阻塞

## 已执行检查

- `python -m compileall .`
- 观测阈值定向回归 3/3 通过

### 回归结果

- `observation_single_message_keeps_observing`：通过
- `observation_threshold_allows_analysis`：通过
- `summoned_bypasses_observation_threshold`：通过
