import asyncio
import types
import unittest
from unittest.mock import AsyncMock

from tests import _test_bootstrap  # noqa: F401

from astrbot_plugin_angel_heart.core.air_reading import AirReadingSignal
from astrbot_plugin_angel_heart.core.angel_heart_context import AngelHeartContext
from astrbot_plugin_angel_heart.core.angel_heart_status import AngelHeartStatus
from astrbot_plugin_angel_heart.core.decision_pipeline import DecisionPipeline
from astrbot_plugin_angel_heart.models.analysis_result import SecretaryDecision
from astrbot_plugin_angel_heart.models.decision_context import ConversationCueSnapshot, DecisionEnvelope, ThreadWindow
from astrbot_plugin_angel_heart.roles.secretary import Secretary


class _Config:
    force_reply_when_summoned = False
    observation_min_messages = 2
    observation_followup_score_threshold = 5
    air_reading_suppress_threshold = -3


class SecretaryStateFlowTests(unittest.IsolatedAsyncioTestCase):
    def _build_secretary(self):
        secretary = Secretary.__new__(Secretary)
        secretary._config_manager = _Config()
        secretary.context = object()
        secretary.angel_context = types.SimpleNamespace(
            status_transition_manager=types.SimpleNamespace(transition_to_status=AsyncMock())
        )
        secretary.decision_pipeline = DecisionPipeline(secretary._config_manager)
        secretary.status_checker = types.SimpleNamespace(
            _detect_echo_chamber=lambda chat_id: False,
            determine_status=AsyncMock(return_value=AngelHeartStatus.NOT_PRESENT),
        )
        return secretary

    def _build_envelope(self, *, hard_allow=False, hard_allow_reason="", hard_suppress=False, hard_suppress_reason="", final_should_reply=False, final_reason="", followup_score=0):
        snapshot = ConversationCueSnapshot(
            thread_window=ThreadWindow(thread_topic_hint="线程话题", thread_target_hint="tester", followup_score=followup_score),
            hard_allow=hard_allow,
            hard_allow_reason=hard_allow_reason,
            hard_suppress=hard_suppress,
            hard_suppress_reason=hard_suppress_reason,
            followup_score=followup_score,
        )
        return DecisionEnvelope(
            snapshot=snapshot,
            status_name=AngelHeartStatus.SUMMONED.value,
            final_should_reply=final_should_reply,
            final_reason=final_reason,
        )

    async def test_summoned_hard_suppress_short_circuits_llm(self):
        secretary = self._build_secretary()
        event = types.SimpleNamespace(unified_msg_origin="chat-1")
        air_signal = AirReadingSignal(air_score=-4, should_suppress=True, suppression_reason="command_like_wake")
        envelope = self._build_envelope(
            hard_suppress=True,
            hard_suppress_reason="command_like_wake",
            final_should_reply=False,
            final_reason="command_like_wake",
        )

        secretary._prepare_air_analysis = lambda *args, **kwargs: ([], [{"role": "user", "content": "wake"}], air_signal)
        secretary._build_decision_envelope = lambda *args, **kwargs: envelope
        secretary._log_air_reading_signal = lambda *args, **kwargs: None
        secretary._log_decision_envelope = lambda *args, **kwargs: None
        secretary.perform_analysis = AsyncMock(side_effect=AssertionError("LLM should not run"))

        decision = await secretary._handle_summoned_reply(event, "chat-1")

        self.assertFalse(decision.should_reply)
        self.assertEqual(decision.final_reason, "command_like_wake")
        self.assertEqual(decision.reply_strategy, "command_like_wake")
        self.assertTrue(decision.hard_suppress)

    async def test_summoned_hard_allow_short_circuits_llm(self):
        secretary = self._build_secretary()
        event = types.SimpleNamespace(unified_msg_origin="chat-1")
        air_signal = AirReadingSignal(air_score=6, conversation_mode="directed_to_ai")
        envelope = self._build_envelope(
            hard_allow=True,
            hard_allow_reason="at_self",
            final_should_reply=True,
            final_reason="at_self",
        )

        secretary._prepare_air_analysis = lambda *args, **kwargs: ([], [{"role": "user", "content": "@bot 先扣分"}], air_signal)
        secretary._build_decision_envelope = lambda *args, **kwargs: envelope
        secretary._log_air_reading_signal = lambda *args, **kwargs: None
        secretary._log_decision_envelope = lambda *args, **kwargs: None
        secretary.perform_analysis = AsyncMock(side_effect=AssertionError("LLM should not run"))

        decision = await secretary._handle_summoned_reply(event, "chat-1")

        self.assertTrue(decision.should_reply)
        self.assertEqual(decision.final_reason, "at_self")
        self.assertEqual(decision.reply_strategy, "at_self")
        self.assertTrue(decision.hard_allow)

    async def test_summoned_force_reply_overrides_llm_rejection(self):
        secretary = self._build_secretary()
        secretary._config_manager.force_reply_when_summoned = True
        event = types.SimpleNamespace(unified_msg_origin="chat-1")
        air_signal = AirReadingSignal(conversation_mode="directed_to_ai")
        envelope = self._build_envelope(hard_allow=True, hard_allow_reason="at_self", final_should_reply=True, final_reason="at_self")

        secretary._prepare_air_analysis = lambda *args, **kwargs: ([{"role": "assistant", "content": "hi"}], [{"role": "user", "content": "@bot"}], air_signal)
        secretary._build_decision_envelope = lambda *args, **kwargs: envelope
        secretary._log_air_reading_signal = lambda *args, **kwargs: None
        secretary._log_decision_envelope = lambda *args, **kwargs: None
        secretary.perform_analysis = AsyncMock(
            return_value=SecretaryDecision(
                should_reply=False,
                reply_strategy="继续观察",
                topic="未知",
                entities=[],
                facts=[],
                keywords=[],
            )
        )

        decision = await secretary._handle_summoned_reply(event, "chat-1")

        self.assertTrue(decision.should_reply)
        self.assertEqual(decision.reply_strategy, "被呼唤回复")
        self.assertEqual(decision.final_reason, "summoned_force_reply")

    async def test_familiarity_hard_suppress_skips_fishing_reply(self):
        secretary = self._build_secretary()
        event = types.SimpleNamespace(unified_msg_origin="chat-1")
        air_signal = AirReadingSignal(air_score=-5, should_suppress=True, suppression_reason="heated_conflict")
        envelope = self._build_envelope(
            hard_suppress=True,
            hard_suppress_reason="heated_conflict",
            final_should_reply=False,
            final_reason="heated_conflict",
        )

        secretary._prepare_air_analysis = lambda *args, **kwargs: ([], [{"role": "user", "content": "吵起来了"}], air_signal)
        secretary._build_decision_envelope = lambda *args, **kwargs: envelope
        secretary._log_air_reading_signal = lambda *args, **kwargs: None
        secretary._log_decision_envelope = lambda *args, **kwargs: None

        decision = await secretary._handle_familiarity_reply(event, "chat-1")

        self.assertFalse(decision.should_reply)
        self.assertEqual(decision.final_reason, "heated_conflict")
        self.assertTrue(decision.hard_suppress)

    async def test_observation_hard_allow_short_circuits_llm(self):
        secretary = self._build_secretary()
        event = types.SimpleNamespace(unified_msg_origin="chat-1")
        air_signal = AirReadingSignal(air_score=2, conversation_mode="directed_to_ai")
        envelope = self._build_envelope(
            hard_allow=True,
            hard_allow_reason="direct_followup",
            final_should_reply=True,
            final_reason="direct_followup",
            followup_score=4,
        )

        secretary._prepare_air_analysis = lambda *args, **kwargs: ([{"role": "assistant", "content": "上轮回复"}], [{"role": "user", "content": "继续说"}], air_signal)
        secretary._build_decision_envelope = lambda *args, **kwargs: envelope
        secretary._log_air_reading_signal = lambda *args, **kwargs: None
        secretary._log_decision_envelope = lambda *args, **kwargs: None
        secretary.perform_analysis = AsyncMock(side_effect=AssertionError("LLM should not run"))

        decision = await secretary._handle_observation_reply(event, "chat-1")

        self.assertTrue(decision.should_reply)
        self.assertEqual(decision.final_reason, "direct_followup")
        self.assertEqual(decision.reply_strategy, "direct_followup")
        self.assertTrue(decision.hard_allow)

    async def test_not_present_routes_to_new_status_handler(self):
        secretary = self._build_secretary()
        event = types.SimpleNamespace(unified_msg_origin="chat-1")
        expected = SecretaryDecision(
            should_reply=True,
            reply_strategy="跟紧复读队形",
            topic="复读互动",
            entities=[],
            facts=[],
            keywords=[],
        )
        secretary.status_checker.determine_status = AsyncMock(return_value=AngelHeartStatus.GETTING_FAMILIAR)
        secretary._handle_familiarity_reply = AsyncMock(return_value=expected)

        decision = await secretary._handle_not_present_check(event, "chat-1")

        self.assertTrue(decision.should_reply)
        self.assertEqual(decision.reply_strategy, "跟紧复读队形")
        secretary.angel_context.status_transition_manager.transition_to_status.assert_awaited_once()
        secretary._handle_familiarity_reply.assert_awaited_once_with(event, "chat-1")


class DetentionQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_does_not_remove_new_ticket_when_old_timer_is_cancelled(self):
        ctx = AngelHeartContext.__new__(AngelHeartContext)
        ctx.config_manager = types.SimpleNamespace(waiting_time=15, llm_timeout=30)
        ctx.pending_futures = {}
        ctx.pending_events = {}
        ctx.detention_timeout_timers = {}
        ctx.dispatch_lock = asyncio.Lock()
        ctx.deferred_events = {}
        ctx.lock_cooldown_until = {}
        ctx.processing_chats = {}
        ctx.processing_lock = asyncio.Lock()
        ctx.is_chat_processing = AsyncMock(return_value=True)

        chat_id = "chat-1"
        old_ticket = asyncio.Future()
        old_event = object()
        old_timer = asyncio.create_task(asyncio.sleep(3600))
        ctx.pending_futures[chat_id] = old_ticket
        ctx.pending_events[chat_id] = old_event
        ctx.detention_timeout_timers[chat_id] = old_timer

        new_event = object()
        new_ticket = await ctx.hold_and_start_observation(chat_id, new_event)
        new_timer = ctx.detention_timeout_timers[chat_id]

        ctx._cleanup_detention_resources(chat_id, ticket=old_ticket, timer=old_timer, event=old_event)

        self.assertIs(ctx.pending_futures.get(chat_id), new_ticket)
        self.assertIs(ctx.pending_events.get(chat_id), new_event)
        self.assertIs(ctx.detention_timeout_timers.get(chat_id), new_timer)

        new_timer.cancel()
        old_timer.cancel()
        await asyncio.gather(new_timer, old_timer, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
