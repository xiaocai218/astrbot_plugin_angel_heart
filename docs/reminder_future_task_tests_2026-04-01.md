# 提醒桥接测试说明

## 目标

把提醒桥接能力从“临时回归脚本可跑”提升到“仓库内正式测试可重复执行”。

## 当前测试层次

### 1. 单元测试

文件：

- `tests/test_reminder_task_bridge.py`

覆盖内容：

- 时间解析
- future task 创建参数
- 失败时显式反馈
- 开关关闭时不接管

特点：

- 不依赖真实 NAS
- 不依赖真实 AstrBot 容器
- 使用最小 fake context 验证桥接器行为

### 2. 回归脚本

文件：

- `reminder_bridge_regression.py`

用途：

- 在 AstrBot 本机 Python 环境里跑一轮真实导入级别的定向回归
- 用于快速确认依赖、导入链和关键场景没有被改坏

## 建议执行方式

### 本地快速单测

```powershell
python -m unittest tests.test_reminder_task_bridge
```

### AstrBot 运行时回归

```powershell
D:\PycharmProjects\AstrBot\backend\python\python.exe reminder_bridge_regression.py
```

## 当前状态

提醒桥接相关规则已经覆盖：

- 单次提醒
- 每周提醒
- 每天/工作日提醒
- 每月固定日期提醒
- 每月最后一天提醒
- 下个月/月底/月初/季度末
- 中文数字时间
- 口语日期与时段

## 边界说明

- `每隔两天` 当前按 cron `*/2` 映射，不是严格 48 小时间隔
- `隔周一` 当前按“下一次隔开的周一”解释为单次任务
- `季度末`、`月初第一个工作日` 当前按“下一次单次任务”处理

### 验证结果

- `python -m unittest tests.test_reminder_task_bridge` 当前通过，结果 `12/12`
- `D:\PycharmProjects\AstrBot\backend\python\python.exe reminder_bridge_regression.py` 当前通过，结果 `34/34`
