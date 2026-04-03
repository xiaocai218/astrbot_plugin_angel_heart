# 观测态续聊分数诊断日志（2026-04-02）

## 背景

续聊强放行已经改成了评分模型，但如果日志里只看到“放行/不放行”，仍然很难定位具体卡在哪一项：

- 时间窗没命中
- 词表没命中
- 同用户连续接话没命中
- 词面承接没命中

## 本次调整

新增固定格式的 `info` 日志：

- `观测态续聊评分`

日志内容包含：

- `score`
- `threshold`
- `time_gap`
- `directed`
- `reply_self`
- `same_sender_streak`
- `short_phrase`
- `question_phrase`
- `feedback_phrase`
- `carry_over`
- `text_overlap`

## 预期效果

后续在 NAS 日志里看到“明明在跟 AI 说话却没回”的场景时，可以直接判断：

- 是不是时间隔太久
- 是不是词表太保守
- 是不是总分阈值太高

这样后续调参基本可以只改配置，不需要反复读代码。
