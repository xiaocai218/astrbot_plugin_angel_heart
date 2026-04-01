# 读空气细粒度开关拆分（2026-04-01）

## 背景

读空气 V1 已经具备压制能力，但当前压制规则是整体式的。
如果用户希望保留“火药味压制”，同时关闭“群友互聊压制”或“被无视压制”，现有配置粒度不够。

## 本次调整

新增以下独立开关：

- `air_reading_suppress_human_to_human`
- `air_reading_suppress_ignored_recently`
- `air_reading_suppress_heated`
- `air_reading_suppress_smalltalk`

## 目标

- 允许按场景精细调节读空气压制策略
- 保持默认行为与原先 V1 一致
- 不改变现有状态机和秘书 JSON 链路
