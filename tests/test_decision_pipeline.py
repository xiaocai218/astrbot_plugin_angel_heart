import unittest

from tests import _test_bootstrap  # noqa: F401

from astrbot_plugin_angel_heart.core.air_reading import AirReadingSignal
from astrbot_plugin_angel_heart.core.angel_heart_status import AngelHeartStatus
from astrbot_plugin_angel_heart.core.decision_pipeline import DecisionPipeline
from astrbot_plugin_angel_heart.core.thread_window import ThreadWindowBuilder
from astrbot_plugin_angel_heart.models.decision_context import ThreadWindow


class _Config:
    observation_followup_score_threshold = 5
    air_reading_suppress_threshold = -3


def _text_message(role, text, timestamp, sender_id="user-1", sender_name="tester", **extra):
    message = {
        "role": role,
        "content": [{"type": "text", "text": text}],
        "timestamp": timestamp,
        "sender_id": sender_id,
        "sender_name": sender_name,
    }
    message.update(extra)
    return message


class DecisionPipelineTest(unittest.TestCase):
    def setUp(self):
        self.config = _Config()
        self.pipeline = DecisionPipeline(self.config)
        self.thread_builder = ThreadWindowBuilder(self.config)

    def _start_envelope(self, *, air_score=0, followup_score=0, status=AngelHeartStatus.OBSERVATION):
        thread_window = self.thread_builder.build(
            [_text_message("assistant", "上一轮锚点。", 100)],
            [_text_message("user", "这一轮消息", 120)],
        )
        signal = AirReadingSignal(air_score=air_score, conversation_mode="general_discussion")
        snapshot = self.pipeline.build_snapshot(
            status=status,
            thread_window=thread_window,
            air_signal=signal,
            latest_user_message={"role": "user", "summon_source": ""},
            followup_score=followup_score,
        )
        return self.pipeline.start_envelope(snapshot, status)

    def test_followup_short_phrase_hard_allow(self):
        historical = [_text_message("assistant", "你可以继续说。", 100)]
        recent = [_text_message("user", "确实", 110)]
        thread_window = self.thread_builder.build(historical, recent)
        signal = AirReadingSignal(air_score=1, conversation_mode="directed_to_ai")

        snapshot = self.pipeline.build_snapshot(
            status=AngelHeartStatus.OBSERVATION,
            thread_window=thread_window,
            air_signal=signal,
            latest_user_message=recent[-1],
            followup_score=5,
        )
        envelope = self.pipeline.start_envelope(snapshot, AngelHeartStatus.OBSERVATION)

        self.assertTrue(envelope.final_should_reply)
        self.assertEqual(envelope.final_reason, "direct_followup")

    def test_human_private_exchange_is_hard_suppress(self):
        historical = [_text_message("assistant", "我刚才说完。", 100)]
        recent = [_text_message("user", "@小王 你怎么看", 120, summon_source="")]
        thread_window = self.thread_builder.build(historical, recent)
        signal = AirReadingSignal(
            air_score=-4,
            should_suppress=True,
            suppression_reason="human_private_exchange",
            conversation_mode="human_to_human",
        )

        snapshot = self.pipeline.build_snapshot(
            status=AngelHeartStatus.OBSERVATION,
            thread_window=thread_window,
            air_signal=signal,
            latest_user_message=recent[-1],
            followup_score=1,
        )
        envelope = self.pipeline.start_envelope(snapshot, AngelHeartStatus.OBSERVATION)

        self.assertFalse(envelope.final_should_reply)
        self.assertEqual(envelope.final_reason, "human_private_exchange")

    def test_air_score_guard_blocks_weak_llm_reply(self):
        historical = [_text_message("assistant", "上一轮聊显卡。", 100)]
        recent = [_text_message("user", "哈哈", 140)]
        thread_window = self.thread_builder.build(historical, recent)
        signal = AirReadingSignal(air_score=-5, conversation_mode="small_talk")
        snapshot = self.pipeline.build_snapshot(
            status=AngelHeartStatus.OBSERVATION,
            thread_window=thread_window,
            air_signal=signal,
            latest_user_message=recent[-1],
            followup_score=0,
        )
        envelope = self.pipeline.start_envelope(snapshot, AngelHeartStatus.OBSERVATION)
        envelope = self.pipeline.apply_llm_review(
            envelope,
            {
                "needs_reply_now": True,
                "addressing_mode": "unclear",
                "reply_value": "high",
            },
        )

        self.assertFalse(envelope.final_should_reply)
        self.assertEqual(envelope.final_reason, "air_score_guard")

    def test_reply_self_overrides_human_private_exchange_suppress(self):
        historical = [_text_message("assistant", "你继续说。", 100)]
        recent = [_text_message("user", "我补一句", 110, summon_source="reply_self")]
        thread_window = self.thread_builder.build(historical, recent)
        signal = AirReadingSignal(
            air_score=-4,
            should_suppress=True,
            suppression_reason="human_private_exchange",
            conversation_mode="human_to_human",
        )

        snapshot = self.pipeline.build_snapshot(
            status=AngelHeartStatus.OBSERVATION,
            thread_window=thread_window,
            air_signal=signal,
            latest_user_message=recent[-1],
            followup_score=0,
            command_like_wake=False,
        )
        envelope = self.pipeline.start_envelope(snapshot, AngelHeartStatus.OBSERVATION)

        self.assertTrue(snapshot.hard_allow)
        self.assertEqual(snapshot.hard_allow_reason, "reply_self")
        self.assertFalse(snapshot.hard_suppress)
        self.assertTrue(envelope.final_should_reply)
        self.assertEqual(envelope.final_reason, "reply_self")

    def test_reply_self_overrides_command_like_wake_suppress(self):
        historical = [_text_message("assistant", "你直接回我。", 100)]
        recent = [_text_message("user", "那我继续", 108, summon_source="reply_self")]
        thread_window = self.thread_builder.build(historical, recent)
        signal = AirReadingSignal(air_score=1, conversation_mode="directed_to_ai")

        snapshot = self.pipeline.build_snapshot(
            status=AngelHeartStatus.SUMMONED,
            thread_window=thread_window,
            air_signal=signal,
            latest_user_message=recent[-1],
            followup_score=0,
            command_like_wake=True,
        )
        envelope = self.pipeline.start_envelope(snapshot, AngelHeartStatus.SUMMONED)

        self.assertTrue(snapshot.hard_allow)
        self.assertEqual(snapshot.hard_allow_reason, "reply_self")
        self.assertFalse(snapshot.hard_suppress)
        self.assertTrue(envelope.final_should_reply)
        self.assertEqual(envelope.final_reason, "reply_self")

    def test_command_like_wake_is_hard_suppress_without_direct_summon(self):
        historical = [_text_message("assistant", "上一轮到这里。", 100)]
        recent = [_text_message("user", "/angel 帮我查一下", 120, summon_source="")]
        thread_window = self.thread_builder.build(historical, recent)
        signal = AirReadingSignal(air_score=0, conversation_mode="general_discussion")

        snapshot = self.pipeline.build_snapshot(
            status=AngelHeartStatus.SUMMONED,
            thread_window=thread_window,
            air_signal=signal,
            latest_user_message=recent[-1],
            followup_score=0,
            command_like_wake=True,
        )
        envelope = self.pipeline.start_envelope(snapshot, AngelHeartStatus.SUMMONED)

        self.assertTrue(snapshot.hard_suppress)
        self.assertEqual(snapshot.hard_suppress_reason, "command_like_wake")
        self.assertFalse(envelope.final_should_reply)
        self.assertEqual(envelope.final_reason, "command_like_wake")

    def test_apply_llm_review_followup_score_beats_unclear_low_value(self):
        envelope = self._start_envelope(air_score=1, followup_score=5, status=AngelHeartStatus.SUMMONED)

        envelope = self.pipeline.apply_llm_review(
            envelope,
            {
                "needs_reply_now": False,
                "addressing_mode": "unclear",
                "reply_value": "low",
            },
        )

        self.assertTrue(envelope.final_should_reply)
        self.assertEqual(envelope.final_reason, "followup_score")

    def test_apply_llm_review_to_ai_beats_low_value_without_followup(self):
        envelope = self._start_envelope(air_score=1, followup_score=0)

        envelope = self.pipeline.apply_llm_review(
            envelope,
            {
                "needs_reply_now": True,
                "addressing_mode": "to_ai",
                "reply_value": "low",
            },
        )

        self.assertTrue(envelope.final_should_reply)
        self.assertEqual(envelope.final_reason, "llm_to_ai")

    def test_apply_llm_review_high_value_without_to_ai_uses_guard_path(self):
        envelope = self._start_envelope(air_score=1, followup_score=0)

        envelope = self.pipeline.apply_llm_review(
            envelope,
            {
                "needs_reply_now": True,
                "addressing_mode": "unclear",
                "reply_value": "high",
            },
        )

        self.assertTrue(envelope.final_should_reply)
        self.assertEqual(envelope.final_reason, "llm_high_value")


    def test_apply_llm_review_low_thread_confidence_blocks_unclear_high_value(self):
        thread_window = self.thread_builder.build(
            [],
            [
                _text_message("user", f"消息{i}", 100 + i, sender_id=f"user-{i % 2}", sender_name=f"user-{i % 2}")
                for i in range(10)
            ],
        )
        signal = AirReadingSignal(air_score=1, conversation_mode="general_discussion")
        snapshot = self.pipeline.build_snapshot(
            status=AngelHeartStatus.OBSERVATION,
            thread_window=thread_window,
            air_signal=signal,
            latest_user_message=thread_window.latest_user_burst[-1],
            followup_score=0,
        )
        envelope = self.pipeline.start_envelope(snapshot, AngelHeartStatus.OBSERVATION)

        envelope = self.pipeline.apply_llm_review(
            envelope,
            {
                "needs_reply_now": True,
                "addressing_mode": "unclear",
                "reply_value": "high",
            },
        )

        self.assertFalse(envelope.final_should_reply)
        self.assertEqual(envelope.final_reason, "thread_confidence_guard")

    def test_apply_llm_review_to_ai_bypasses_thread_confidence_guard(self):
        thread_window = self.thread_builder.build(
            [],
            [
                _text_message("user", f"消息{i}", 100 + i, sender_id=f"user-{i % 2}", sender_name=f"user-{i % 2}")
                for i in range(10)
            ],
        )
        signal = AirReadingSignal(air_score=1, conversation_mode="directed_to_ai")
        snapshot = self.pipeline.build_snapshot(
            status=AngelHeartStatus.OBSERVATION,
            thread_window=thread_window,
            air_signal=signal,
            latest_user_message=thread_window.latest_user_burst[-1],
            followup_score=0,
        )
        envelope = self.pipeline.start_envelope(snapshot, AngelHeartStatus.OBSERVATION)

        envelope = self.pipeline.apply_llm_review(
            envelope,
            {
                "needs_reply_now": True,
                "addressing_mode": "to_ai",
                "reply_value": "high",
            },
        )

        self.assertTrue(envelope.final_should_reply)
        self.assertEqual(envelope.final_reason, "llm_to_ai")

    def test_apply_llm_review_low_value_unclear_stays_observing(self):
        envelope = self._start_envelope(air_score=1, followup_score=0)

        envelope = self.pipeline.apply_llm_review(
            envelope,
            {
                "needs_reply_now": True,
                "addressing_mode": "unclear",
                "reply_value": "low",
            },
        )

        self.assertFalse(envelope.final_should_reply)
        self.assertEqual(envelope.final_reason, "continue_observing")

    def test_apply_llm_review_to_ai_bypasses_air_score_guard(self):
        envelope = self._start_envelope(air_score=-5, followup_score=0)

        envelope = self.pipeline.apply_llm_review(
            envelope,
            {
                "needs_reply_now": True,
                "addressing_mode": "to_ai",
                "reply_value": "low",
            },
        )

        self.assertTrue(envelope.final_should_reply)
        self.assertEqual(envelope.final_reason, "llm_to_ai")

    def test_build_snapshot_marks_missing_recent_context(self):
        signal = AirReadingSignal(air_score=0, conversation_mode="general_discussion")
        snapshot = self.pipeline.build_snapshot(
            status=AngelHeartStatus.OBSERVATION,
            thread_window=ThreadWindow(),
            air_signal=signal,
            latest_user_message=None,
            followup_score=0,
        )

        self.assertFalse(snapshot.has_recent_context)
        self.assertFalse(snapshot.hard_allow)
        self.assertFalse(snapshot.hard_suppress)

    def test_apply_llm_review_blocks_empty_thread_even_if_to_ai(self):
        signal = AirReadingSignal(air_score=0, conversation_mode="general_discussion")
        snapshot = self.pipeline.build_snapshot(
            status=AngelHeartStatus.SUMMONED,
            thread_window=ThreadWindow(),
            air_signal=signal,
            latest_user_message=None,
            followup_score=0,
        )
        envelope = self.pipeline.start_envelope(snapshot, AngelHeartStatus.SUMMONED)
        envelope = self.pipeline.apply_llm_review(
            envelope,
            {
                "needs_reply_now": True,
                "addressing_mode": "to_ai",
                "reply_value": "high",
            },
        )

        self.assertFalse(envelope.final_should_reply)
        self.assertEqual(envelope.final_reason, "missing_recent_context")


class ThreadWindowBuilderTest(unittest.TestCase):
    def setUp(self):
        self.builder = ThreadWindowBuilder(_Config())

    def test_latest_user_burst_groups_same_sender_messages(self):
        historical = [_text_message("assistant", "你继续补充。", 100)]
        recent = [
            _text_message("user", "只能说", 110),
            _text_message("user", "竞赛还在", 118),
            _text_message("user", "持续", 126),
        ]

        window = self.builder.build(historical, recent)

        self.assertEqual(len(window.latest_user_burst), 3)
        self.assertEqual(len(window.current_thread_messages), 4)

    def test_stale_old_topic_not_carried_after_new_anchor(self):
        historical = [
            _text_message("assistant", "之前在聊 ROG 灯效。", 100),
            _text_message("assistant", "现在在说主机稳定性。", 200),
        ]
        recent = [_text_message("user", "ai主机就是笑话", 220)]

        window = self.builder.build(historical, recent)

        self.assertIn("主机", window.thread_topic_hint)
        self.assertEqual(window.current_thread_messages[0]["timestamp"], 200)

    def test_interleaved_other_user_is_kept_in_thread_window(self):
        historical = [_text_message("assistant", "你们继续说主机这事。", 100)]
        recent = [
            _text_message("user", "我觉得散热也有问题", 108, sender_id="user-2", sender_name="alice"),
            _text_message("user", "机箱风道确实乱了", 110, sender_id="user-1", sender_name="bob"),
            _text_message("user", "现在温度压不住", 118, sender_id="user-1", sender_name="bob"),
        ]

        window = self.builder.build(historical, recent)
        timestamps = [message["timestamp"] for message in window.current_thread_messages]

        self.assertIn(108, timestamps)
        self.assertEqual(window.latest_user_burst[-1]["sender_id"], "user-1")
        self.assertEqual(window.thread_target_hint, "bob")

    def test_only_latest_assistant_anchor_is_retained(self):
        historical = [
            _text_message("assistant", "先前在聊旧显卡。", 80),
            _text_message("assistant", "后来已经切到主机稳定性。", 120),
        ]
        recent = [
            _text_message("user", "那主机供电也得看", 130),
            _text_message("assistant", "我觉得电源确实要排查。", 150, sender_id="angel", sender_name="AngelHeart"),
            _text_message("user", "那就先查电源", 165),
        ]

        window = self.builder.build(historical, recent)

        self.assertEqual(window.last_assistant_turn["timestamp"], 120)
        self.assertEqual(window.current_thread_messages[0]["timestamp"], 120)
        self.assertNotIn(80, [message["timestamp"] for message in window.current_thread_messages])

    def test_recent_window_is_capped_without_assistant_anchor(self):
        historical = []
        recent = [
            _text_message("user", f"消息{i}", 100 + i, sender_id=f"user-{i % 3}", sender_name=f"user-{i % 3}")
            for i in range(10)
        ]

        window = self.builder.build(historical, recent)
        timestamps = [message["timestamp"] for message in window.current_thread_messages]

        self.assertIsNone(window.last_assistant_turn)
        self.assertEqual(len(window.current_thread_messages), 8)
        self.assertEqual(timestamps, [102, 103, 104, 105, 106, 107, 108, 109])
        self.assertEqual(window.thread_confidence, 1)

    def test_thread_confidence_is_higher_with_assistant_anchor(self):
        anchored = self.builder.build(
            [_text_message("assistant", "上一轮锚点", 100)],
            [
                _text_message("user", "我继续补充", 110),
                _text_message("user", "这个问题还没完", 118),
            ],
        )
        no_anchor = self.builder.build(
            [],
            [
                _text_message("user", "我继续补充", 110),
                _text_message("user", "这个问题还没完", 118),
            ],
        )

        self.assertGreater(anchored.thread_confidence, no_anchor.thread_confidence)
        self.assertEqual(anchored.thread_confidence, 10)
        self.assertEqual(no_anchor.thread_confidence, 5)

    def test_thread_confidence_drops_further_when_recent_is_truncated(self):
        no_anchor_short = self.builder.build(
            [],
            [
                _text_message("user", "消息1", 101),
                _text_message("user", "消息2", 102),
                _text_message("user", "消息3", 103),
            ],
        )
        no_anchor_truncated = self.builder.build(
            [],
            [
                _text_message("user", f"消息{i}", 100 + i, sender_id=f"user-{i % 2}", sender_name=f"user-{i % 2}")
                for i in range(10)
            ],
        )

        self.assertGreater(no_anchor_short.thread_confidence, no_anchor_truncated.thread_confidence)
        self.assertEqual(no_anchor_short.thread_confidence, 5)
        self.assertEqual(no_anchor_truncated.thread_confidence, 1)


    def test_topic_hint_strips_quote_at_and_emoji_markers(self):
        historical = [_text_message("assistant", "上一轮聊电脑。", 100)]
        recent = [
            _text_message(
                "user",
                "[引用消息(张三: 早上那条)] [At:10000] ai帮我看看 [表情:344] 这台机子能买吗",
                120,
            )
        ]

        window = self.builder.build(historical, recent)

        self.assertEqual(window.thread_topic_hint, "ai帮我看看 这台机子能买吗")


if __name__ == "__main__":
    unittest.main()



