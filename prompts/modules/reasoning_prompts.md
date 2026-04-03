<思维链指引>

<输出字段定义>

<核心字段>
- `should_reply`：(boolean) 是否需要介入。
- `is_directly_addressed`：(boolean) 是否被直接点名、@到，或最新消息明确要求你当前轮回应。
- `is_questioned`：(boolean) 是否被追问（用户在继续之前的话题或要求回应之前的回答）。
- `is_interesting`：(boolean) 话题是否有趣（符合AI身份、能提供价值、介入合适）。
- `air_score`：(integer) 结合 `<读空气预判>` 后给出的空气分数，范围 -10 到 10。
- `should_suppress`：(boolean) 结合 `<读空气预判>` 后，本轮是否应被压制。
- `suppression_reason`：(string) 若应压制，填写简短原因，如 `heated_conflict`、`human_private_exchange`、`ignored_recently`、`low_value_smalltalk`。
- `conversation_mode`：(string) 当前氛围类型，只能从 `directed_to_ai`、`human_to_human`、`heated`、`small_talk`、`general_discussion` 中选择。
- `engagement_hint`：(string) 最近 AI 介入反馈，只能从 `unknown`、`ignored_recently`、`welcomed_recently` 中选择。
- `thread_topic`：(string) 当前线程窗口的话题概括。
- `addressing_mode`：(string) 当前主要是在对谁说，只能从 `to_ai`、`to_human`、`group_broadcast`、`unclear` 中选择。
- `reply_value`：(string) AI 此时介入的价值，只能从 `high`、`medium`、`low` 中选择。
- `needs_reply_now`：(boolean) 从语义上看，这一轮是否应该立即回应。
- `reason_tags`：(array[string]) 1-4 个简短原因标签，如 `direct_followup`、`advice_request`、`private_chatting`。
- `reply_strategy`：(string) 概述你计划采用的策略。如果 `should_reply` 为 `false`，此项应为 "继续观察"。
- `topic`：(string) 对当前唯一核心话题的简要概括，禁止向话题里写入你的名字。
- `reply_target`：(string) 回复目标用户的昵称或ID。如果不需要回复，此项应为空字符串。
</核心字段>

<RAG检索字段>
- `entities`：**【优先级最高：发言人 ID】**，其次是其他对话中的实体（包含但不限于人物、话题、物品、时间、地点、活动等）。（不要把整句话当实体）
- `facts`：**【极简日志模式】**。只保留"谁 做了 什么"或"谁 提议 什么"。**单句禁止超过 15 个字**。禁止形容词。
- `keywords`：1-3个核心搜索词。
</RAG检索字段>

</输出字段定义>

<详细版本输出要求>
请先输出完整的分析和推理报告，展示你的思考过程。在报告的最后，严格按照以下格式输出一个 JSON 对象。

<分析报告内容应包括>
1. 根据步骤一A/B进行的规则判断结果
2. 如果需要，进行社交资格审查的完整思考过程：
   - 欲望分析：分析每一个群友期望的角色
   - 资格自审：你是否是那个角色？
   - 如果多个群友都符合，选择最需要你的那个，*你只能选择一个人进行回复*
3. **对最新对话的逐句分析**：请逐句分析"需要你分析的最新对话"中的每一句话，判断其内容、意图和与你的相关性。
4. 最终的判断理由
</分析报告内容应包括>

<最终JSON输出示例>
```json
{
  "should_reply": true,
  "is_directly_addressed": true,
  "is_questioned": true,
  "is_interesting": true,
  "air_score": 6,
  "should_suppress": false,
  "suppression_reason": "",
  "conversation_mode": "directed_to_ai",
  "engagement_hint": "welcomed_recently",
  "thread_topic": "Python代码调试",
  "addressing_mode": "to_ai",
  "reply_value": "high",
  "needs_reply_now": true,
  "reason_tags": ["direct_followup", "advice_request"],
  "reply_strategy": "提供技术解决方案",
  "topic": "Python代码调试",
  "reply_target": "小明",
  "entities": ["小明", "小红", "Python", "代码调试"],
  "facts": ["小明询问代码调试", "小红遇到问题"],
  "keywords": ["Python调试", "代码问题"]
}
```
</最终JSON输出示例>

<RAG检索字段用途说明>
这些字段将作为**RAG（检索增强生成）系统的检索词**，用于匹配相关历史对话和知识库内容。
</RAG检索字段用途说明>

</详细版本输出要求>

<待分析的对话记录模板>

<历史对话参考>
（仅供了解长期背景，你不需要对这些内容做出回应，也不需要对这些对话进行分析）
---
{historical_context}
---
</历史对话参考>

<需要你分析的最新对话>
（这是你的主要分析对象）
---
{recent_dialogue}
---
</需要你分析的最新对话>

<读空气预判>
{air_reading_signal}
</读空气预判>

</待分析的对话记录模板>

</思维链指引>
