"""AngelHeart 插件 - 统一决策管线"""

from __future__ import annotations

from typing import Dict, List

from ..models.decision_context import ConversationCueSnapshot, DecisionEnvelope
from ..core.angel_heart_status import AngelHeartStatus


class DecisionPipeline:
    """把硬放行、硬压制、续聊分和 LLM 语义判断收口到一处。"""

    def __init__(self, config_manager):
        self.config_manager = config_manager

    def _thread_confidence_guard_threshold(self) -> int:
        return int(getattr(self.config_manager, "thread_confidence_guard_threshold", 2))

    def _set_final_decision(
        self,
        envelope: DecisionEnvelope,
        should_reply: bool,
        reason: str,
        *,
        needs_llm_review: bool | None = None,
    ) -> DecisionEnvelope:
        envelope.final_should_reply = should_reply
        envelope.final_reason = reason
        if needs_llm_review is not None:
            envelope.needs_llm_review = needs_llm_review
        return envelope

    def build_snapshot(
        self,
        status: AngelHeartStatus,
        thread_window,
        air_signal,
        latest_user_message: Dict | None,
        followup_score: int,
        command_like_wake: bool = False,
    ) -> ConversationCueSnapshot:
        hard_allow = False
        hard_allow_reason = ""
        hard_suppress = False
        hard_suppress_reason = ""

        if latest_user_message:
            summon_source = latest_user_message.get("summon_source")
            if summon_source in {"at_self", "reply_self"}:
                hard_allow = True
                hard_allow_reason = summon_source
            elif (
                status == AngelHeartStatus.OBSERVATION
                and followup_score >= self.config_manager.observation_followup_score_threshold
                and air_signal.suppression_reason != "heated_conflict"
            ):
                hard_allow = True
                hard_allow_reason = "direct_followup"

        if air_signal.suppression_reason == "heated_conflict":
            hard_suppress = True
            hard_suppress_reason = "heated_conflict"
        elif command_like_wake and not hard_allow:
            hard_suppress = True
            hard_suppress_reason = "command_like_wake"
        elif (
            air_signal.suppression_reason == "human_private_exchange"
            and not hard_allow
        ):
            hard_suppress = True
            hard_suppress_reason = "human_private_exchange"

        return ConversationCueSnapshot(
            thread_window=thread_window,
            hard_allow=hard_allow,
            hard_allow_reason=hard_allow_reason,
            hard_suppress=hard_suppress,
            hard_suppress_reason=hard_suppress_reason,
            air_score=air_signal.air_score,
            followup_score=followup_score,
            command_like_wake=command_like_wake,
            has_recent_context=bool(thread_window.current_thread_messages),
        )

    def start_envelope(self, snapshot: ConversationCueSnapshot, status: AngelHeartStatus) -> DecisionEnvelope:
        envelope = DecisionEnvelope(
            snapshot=snapshot,
            status_name=status.value,
            needs_llm_review=not snapshot.hard_suppress,
        )
        if snapshot.hard_suppress:
            return self._set_final_decision(
                envelope,
                False,
                snapshot.hard_suppress_reason,
                needs_llm_review=False,
            )
        elif snapshot.hard_allow:
            return self._set_final_decision(envelope, True, snapshot.hard_allow_reason)
        return envelope

    def apply_llm_review(self, envelope: DecisionEnvelope, llm_review: Dict) -> DecisionEnvelope:
        envelope.llm_review = llm_review
        if envelope.snapshot.hard_suppress:
            return self._set_final_decision(
                envelope,
                False,
                envelope.snapshot.hard_suppress_reason,
            )

        if envelope.snapshot.hard_allow:
            return self._set_final_decision(
                envelope,
                True,
                envelope.snapshot.hard_allow_reason,
            )

        if not envelope.snapshot.has_recent_context:
            return self._set_final_decision(
                envelope,
                False,
                "missing_recent_context",
                needs_llm_review=False,
            )

        needs_reply_now = bool(llm_review.get("needs_reply_now"))
        addressing_mode = str(llm_review.get("addressing_mode") or "unclear")
        reply_value = str(llm_review.get("reply_value") or "low")

        if envelope.snapshot.followup_score >= self.config_manager.observation_followup_score_threshold:
            self._set_final_decision(envelope, True, "followup_score")
        elif needs_reply_now and addressing_mode == "to_ai":
            self._set_final_decision(envelope, True, "llm_to_ai")
        elif needs_reply_now and reply_value == "high":
            if envelope.snapshot.thread_window.thread_confidence <= self._thread_confidence_guard_threshold():
                self._set_final_decision(envelope, False, "thread_confidence_guard")
            else:
                self._set_final_decision(envelope, True, "llm_high_value")
        else:
            self._set_final_decision(envelope, False, "continue_observing")

        if (
            envelope.final_should_reply
            and envelope.snapshot.air_score <= self.config_manager.air_reading_suppress_threshold
            and addressing_mode != "to_ai"
        ):
            self._set_final_decision(envelope, False, "air_score_guard")

        return envelope
