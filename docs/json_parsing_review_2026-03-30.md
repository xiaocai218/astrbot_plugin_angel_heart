# 大模型 JSON 解析链路梳理与修复记录

## 背景

本次梳理聚焦于轻量模型返回结构化 JSON 后的消费链路：

- `core/utils/json_parser.py`
- `core/llm_analyzer.py`
- `core/utils/context_utils.py`

目标是确认 JSON 提取、字段解析和后续注入是否存在漏洞、污染面或误判风险，并完成高优先级修复。

## 原始问题

### 1. 决策字段直接拼接到 XML，存在注入面

`topic`、`reply_target`、`reply_strategy` 在进入主脑前会被直接拼接进 `<系统决策>` XML。

风险：

- 轻量模型若输出带有 XML 结束标签或伪指令的文本
- 会打穿原有结构
- 污染主脑注入内容

### 2. 列表字段没有做硬规范化

`entities`、`facts`、`keywords` 只要求字段存在，没有限制：

- 必须为 `list[str]`
- 最大条数
- 单项最大长度

风险：

- 超长数组导致上下文膨胀
- 嵌套对象或异常类型触发校验失败
- 脏结构被带入后续序列化和日志

### 3. JSON 候选选择策略过于宽松

旧逻辑会扫描文本中所有平衡大括号对象，并按“可选字段命中数最多、同分取最后一个”选择。

风险：

- 命中示例 JSON 而非最终 JSON
- 命中解释文本中的伪 JSON
- 在多候选情况下取错对象

### 4. 布尔解析过宽

旧逻辑接受 `int/float -> bool(...)` 的形式。

风险：

- `2`、`-1`、`0.3` 都会被当成 `True`
- 模型若输出类似置信度数字，会被误提升为确定性判断

## 修复方案

### 1. XML 注入前统一转义

在 `format_decision_xml()` 中对：

- `topic`
- `reply_target`
- `reply_strategy`

统一做 XML 转义。

### 2. 增加字段级规范化

在 `LLMAnalyzer` 中新增规范化逻辑：

- 布尔字段只接受明确的布尔字面量和白名单字符串
- 文本字段去除控制字符并限制长度
- 列表字段仅保留字符串项，并限制条数和单项长度

### 3. 收紧 JSON 候选选择

在 `JsonParser` 中调整顺序：

1. 优先解析围栏代码块中的 JSON
2. 否则扫描平衡大括号对象
3. 候选排序优先级改为：
   - 命中可选字段越多越优先
   - 覆盖 required fields 的候选优先
   - 原文位置越靠后越优先

### 4. 失败时保持安全回退

当字段不规范时，优先做安全裁剪与降级；
若仍无法构建决策对象，则回退为“不回复”。

## 回归测试

本次回归重点覆盖：

- 带有伪 XML 的 `reply_strategy/topic` 不会打穿 `<系统决策>` 结构
- `entities/facts/keywords` 中的异常类型和超长值会被裁剪
- 布尔数字不会再被当成有效 `True`
- 多 JSON 候选时优先选择更像最终决策对象的候选

## 已执行检查

- `python -m compileall .`
- 定向恶意 JSON / 脏 JSON 回归测试

结果：

- 编译检查通过
- 恶意 JSON / 脏 JSON 定向回归 4/4 通过
- AstrBot 真环境导入后的组合回归 8/8 通过

### 回归覆盖项

- 带有伪 XML 标签的 `topic/reply_strategy/reply_target` 注入时会被转义
- `entities/facts/keywords` 中的异常类型、单字符串输入和超长值会被规范化
- 数字型布尔字段不会再被提升为 `True`
- 多 JSON 候选时会优先选中更像最终决策对象的候选

### 环境备注

最初使用本机 AstrBot 运行时的 Python 做回归时，环境中缺少：

- `markdown-it-py`
- `mdit-plain`

随后已补装到：

- `D:\PycharmProjects\AstrBot\backend\python\python.exe`

补装后重新执行了真环境导入回归，已确认当前修复不依赖 stub。
