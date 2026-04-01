# 主秘书 / 副秘书自动切换设计记录

## 目标

当主秘书分析模型出现以下问题时，自动切换到副秘书模型继续完成“是否回复”的判断：

- 限速
- 超时
- 提供商未配置或不可用
- 网络不可达或服务临时不可用

该机制只覆盖分析模型，不影响主脑回复模型。

## 设计原则

### 1. 只在基础设施故障时切换

以下情况会触发副秘书回退：

- provider 不存在
- 调用超时
- 429 / rate limit / too many requests
- timeout / timed out
- unavailable / overload / overloaded
- connection error / network error / refused / reset

普通业务误判、返回了合法但不理想的 JSON，不触发副秘书切换。

### 2. 副秘书配置独立

新增配置：

- `deputy_analyzer_model`
- `deputy_is_reasoning_model`

这样主副秘书可以使用不同的 provider，也可以使用不同的提示词输出模式。

### 3. 不改变现有安全回退

若主秘书失败、副秘书也失败，则仍回退为：

- 不回复
- 写日志

保证行为可预测。

## 实现要点

### 1. 候选模型列表

分析前按顺序组装：

1. 主秘书模型
2. 副秘书模型（如果配置了，且与主模型不同）

### 2. 按模型构建对应提示词模板

主副秘书可能一个是思维模型、一个不是，因此按模型分别选择：

- `reasoning_prompts.md`
- `instruction_prompts.md`

### 3. 单模型内部保留原有重试

每个模型仍保留：

- 失败后 3 秒重试 1 次

只有模型自身重试仍失败后，才考虑切到副秘书。

## 回归验证

需要覆盖的关键场景：

- 主秘书 provider 缺失时，副秘书接管
- 主秘书遇到限速错误时，副秘书接管
- 主秘书普通返回合法 JSON 时，不切换副秘书
- 主副秘书都失败时，整体安全回退为不回复

## 已执行检查

- `python -m compileall .`
- 主秘书 / 副秘书切换定向回归 4/4 通过

### 回归结果

- `fallback_on_rate_limit`：通过
- `fallback_when_primary_missing`：通过
- `no_fallback_when_primary_succeeds`：通过
- `safe_fallback_when_both_fail`：通过
