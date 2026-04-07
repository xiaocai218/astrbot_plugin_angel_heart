"""
AngelHeart 插件 - 秘书角色 (Secretary)
负责定时分析缓存内容，决定是否回复。
"""

import asyncio
import json
from typing import Dict, List
from enum import Enum

# 导入公共工具函数
from ..core.utils import json_serialize_context

from ..core.llm_analyzer import LLMAnalyzer
from ..core.air_reading import AirReadingAnalyzer, AirReadingSignal
from ..core.thread_window import ThreadWindowBuilder
from ..core.decision_pipeline import DecisionPipeline
from ..models.analysis_result import SecretaryDecision
from ..core.angel_heart_status import StatusChecker, AngelHeartStatus
from astrbot.api.event import AstrMessageEvent

try:
    from astrbot.api import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class AwakenReason(Enum):
    """秘书唤醒原因枚举"""
    OK = "正常"
    COOLING_DOWN = "冷却中"
    PROCESSING = "处理中"


class Secretary:
    """
    秘书角色 - 专注的分析与决策员
    """

    def __init__(self, config_manager, context, angel_context):
        """
        初始化秘书角色。

        Args:
            config_manager: 配置管理器实例。
            context: 插件上下文对象。
            angel_context: AngelHeart全局上下文实例。
        """
        self._config_manager = config_manager
        self.context = context
        self.angel_context = angel_context
        self.status_checker = StatusChecker(config_manager, angel_context)

        # -- 常量定义 --
        self.DB_HISTORY_MERGE_LIMIT = 5  # 数据库历史记录合并限制

        # -- 核心组件 --
        # 初始化 LLMAnalyzer
        analyzer_model_name = self.config_manager.analyzer_model
        reply_strategy_guide = self.config_manager.reply_strategy_guide
        # 传递 context 对象，让 LLMAnalyzer 在需要时动态获取 provider
        self.llm_analyzer = LLMAnalyzer(
            analyzer_model_name, context, reply_strategy_guide, self.config_manager
        )
        self.air_reading_analyzer = AirReadingAnalyzer(config_manager)
        self.thread_window_builder = ThreadWindowBuilder(config_manager)
        self.decision_pipeline = DecisionPipeline(config_manager)

    async def handle_message_by_state(self, event: AstrMessageEvent) -> SecretaryDecision:
        """
        秘书职责：根据状态决定消息处理方式

        Args:
            event: 消息事件

        Returns:
            SecretaryDecision: 分析后得出的决策对象
        """
        chat_id = event.unified_msg_origin

        # 获取当前状态
        current_status = self.angel_context.get_chat_status(chat_id)
        logger.info(f"AngelHeart[{chat_id}]: 秘书处理消息 (状态: {current_status.value})")

        # 优先检查是否被呼唤（无论当前状态如何）
        if self.status_checker._is_summoned(chat_id):
            # 如果当前不是 SUMMONED 状态，需要转换
            if current_status != AngelHeartStatus.SUMMONED:
                logger.info(f"AngelHeart[{chat_id}]: 检测到被呼唤，从 {current_status.value} 转换到被呼唤状态")
                await self.angel_context.status_transition_manager.transition_to_status(
                    chat_id, AngelHeartStatus.SUMMONED, "检测到呼唤"
                )
            decision = await self._handle_summoned_reply(event, chat_id)
            self._log_analysis_result(chat_id, AngelHeartStatus.SUMMONED.value, decision)
            return decision

        # 根据当前状态选择处理方式
        if current_status == AngelHeartStatus.GETTING_FAMILIAR:
            decision = await self._handle_familiarity_reply(event, chat_id)
        elif current_status == AngelHeartStatus.SUMMONED:
            decision = await self._handle_summoned_reply(event, chat_id)
        elif current_status == AngelHeartStatus.OBSERVATION:
            decision = await self._handle_observation_reply(event, chat_id)
        else:
            # 不在场：检查触发条件
            decision = await self._handle_not_present_check(event, chat_id)

        self._log_analysis_result(chat_id, current_status.value, decision)
        return decision

    async def _handle_familiarity_reply(self, event: AstrMessageEvent, chat_id: str) -> SecretaryDecision:
        """处理混脸熟状态 - 快速回复"""
        try:
            historical_context, recent_dialogue, air_signal = self._prepare_air_analysis(
                chat_id,
                AngelHeartStatus.GETTING_FAMILIAR,
                allow_suppression=True,
            )
            envelope = self._build_decision_envelope(
                event,
                AngelHeartStatus.GETTING_FAMILIAR,
                historical_context,
                recent_dialogue,
                air_signal,
            )
            self._log_air_reading_signal(chat_id, air_signal)
            self._log_decision_envelope(chat_id, envelope)
            if envelope.snapshot.hard_suppress:
                return self._decision_from_envelope(envelope, "混脸熟压制")

            # 检测实际触发类型
            if self.status_checker._detect_echo_chamber(chat_id):
                trigger_type = "echo_chamber"
            else:
                trigger_type = "dense_conversation"

            logger.info(f"AngelHeart[{chat_id}]: 秘书处理混脸熟状态，触发类型: {trigger_type}")

            # 使用 fishing_reply 生成策略
            from ..core.fishing_direct_reply import FishingDirectReply

            fishing_reply = FishingDirectReply(self.config_manager, self.context)
            decision = await fishing_reply.generate_reply_strategy(
                chat_id, event, trigger_type
            )
            self._attach_air_signal(decision, air_signal)
            self._apply_envelope_to_decision(decision, envelope)

            return decision

        except Exception as e:
            logger.error(f"AngelHeart[{chat_id}]: 秘书混脸熟处理异常: {e}", exc_info=True)
            return SecretaryDecision(
                should_reply=False, reply_strategy="处理异常", topic="未知",
                entities=[], facts=[], keywords=[]
            )

    async def _handle_summoned_reply(self, event: AstrMessageEvent, chat_id: str) -> SecretaryDecision:
        """处理被呼唤状态 - 可配置为强制回复或尊重分析结果"""
        try:
            logger.info(f"AngelHeart[{chat_id}]: 秘书处理被呼唤状态")

            # 获取上下文
            historical_context, recent_dialogue, air_signal = self._prepare_air_analysis(
                chat_id,
                AngelHeartStatus.SUMMONED,
                allow_suppression=False,
            )
            envelope = self._build_decision_envelope(
                event,
                AngelHeartStatus.SUMMONED,
                historical_context,
                recent_dialogue,
                air_signal,
            )

            if not recent_dialogue:
                logger.info(f"AngelHeart[{chat_id}]: 无新消息需要分析。")
                return SecretaryDecision(
                    should_reply=False, reply_strategy="无新消息", topic="未知",
                    entities=[], facts=[], keywords=[]
                )

            # 执行分析
            self._log_air_reading_signal(chat_id, air_signal)
            self._log_decision_envelope(chat_id, envelope)
            if envelope.snapshot.hard_suppress:
                return self._decision_from_envelope(envelope, "被呼唤压制")
            if envelope.snapshot.hard_allow:
                decision = self._decision_from_envelope(envelope, "被呼唤直达")
                if self.config_manager.force_reply_when_summoned:
                    decision.should_reply = True
                    decision.reply_strategy = "被呼唤回复"
                    decision.final_reason = "summoned_force_reply"
                return decision
            decision = await self.perform_analysis(recent_dialogue, historical_context, chat_id, air_signal=air_signal)
            self._apply_envelope_to_decision(decision, envelope)

            # 根据配置决定是否强制回复
            if self.config_manager.force_reply_when_summoned:
                decision.should_reply = True
                decision.reply_strategy = "被呼唤回复"
                decision.final_reason = "summoned_force_reply"

            return decision

        except Exception as e:
            logger.error(f"AngelHeart[{chat_id}]: 秘书被呼唤处理异常: {e}", exc_info=True)
            return SecretaryDecision(
                should_reply=False, reply_strategy="处理异常", topic="未知",
                entities=[], facts=[], keywords=[]
            )

    async def _handle_observation_reply(self, event: AstrMessageEvent, chat_id: str) -> SecretaryDecision:
        """处理观测中状态 - 智能判断"""
        try:
            logger.info(f"AngelHeart[{chat_id}]: 秘书处理观测中状态")

            # 获取上下文
            historical_context, recent_dialogue, air_signal = self._prepare_air_analysis(
                chat_id,
                AngelHeartStatus.OBSERVATION,
                allow_suppression=True,
            )
            envelope = self._build_decision_envelope(
                event,
                AngelHeartStatus.OBSERVATION,
                historical_context,
                recent_dialogue,
                air_signal,
            )

            if not recent_dialogue:
                logger.info(f"AngelHeart[{chat_id}]: 无新消息需要分析。")
                return SecretaryDecision(
                    should_reply=False, reply_strategy="无新消息", topic="未知",
                    entities=[], facts=[], keywords=[]
                )

            user_message_count = self._count_recent_user_messages(recent_dialogue)
            min_messages = self.config_manager.observation_min_messages
            if user_message_count < min_messages:
                if envelope.snapshot.hard_allow or self._should_bypass_observation_threshold(historical_context, recent_dialogue, air_signal):
                    logger.info(
                        f"AngelHeart[{chat_id}]: 观测态直接续聊命中，绕过消息阈值 {user_message_count}/{min_messages}。"
                    )
                else:
                    logger.info(
                        f"AngelHeart[{chat_id}]: 观测中累计用户消息 {user_message_count}/{min_messages}，继续观察。"
                    )
                    return SecretaryDecision(
                        should_reply=False, reply_strategy="继续观察", topic="观测阈值未达",
                        entities=[], facts=[], keywords=[]
                    )

            # 执行分析
            self._log_air_reading_signal(chat_id, air_signal)
            self._log_decision_envelope(chat_id, envelope)
            if envelope.snapshot.hard_allow:
                return self._decision_from_envelope(envelope, "直接续聊")
            if envelope.snapshot.hard_suppress:
                return self._decision_from_envelope(envelope, "继续观察")
            decision = await self.perform_analysis(recent_dialogue, historical_context, chat_id, air_signal=air_signal)
            self._apply_envelope_to_decision(decision, envelope)

            return decision

        except Exception as e:
            logger.error(f"AngelHeart[{chat_id}]: 秘书观测中处理异常: {e}", exc_info=True)
            return SecretaryDecision(
                should_reply=False, reply_strategy="处理异常", topic="未知",
                entities=[], facts=[], keywords=[]
            )

    def _count_recent_user_messages(self, recent_dialogue: List[Dict]) -> int:
        """统计最近未处理消息中的用户消息数量。"""
        return sum(1 for msg in recent_dialogue if msg.get("role") == "user")

    def _should_bypass_observation_threshold(
        self,
        historical_context: List[Dict],
        recent_dialogue: List[Dict],
        air_signal: AirReadingSignal,
    ) -> bool:
        """观测态下，允许明显接 AI 的直接续聊绕过最小消息数阈值。"""
        if len(recent_dialogue) != 1:
            return False

        latest_message = recent_dialogue[-1]
        if latest_message.get("role") != "user":
            return False

        previous_messages = [msg for msg in historical_context if isinstance(msg, dict)]
        if not previous_messages:
            return False

        last_processed = previous_messages[-1]
        if last_processed.get("role") != "assistant":
            return False

        latest_text = self._extract_message_text(latest_message)
        assistant_text = self._extract_message_text(last_processed)
        if not latest_text or not assistant_text:
            return False

        latest_ts = float(latest_message.get("timestamp") or 0)
        assistant_ts = float(last_processed.get("timestamp") or 0)
        if latest_ts <= 0 or assistant_ts <= 0:
            return False

        if latest_ts - assistant_ts > 90:
            return False

        if air_signal.conversation_mode == "directed_to_ai":
            return True

        if len(latest_text) < 6:
            return False

        normalized_latest = set(self._tokenize_text(latest_text))
        normalized_assistant = set(self._tokenize_text(assistant_text))
        if not normalized_latest or not normalized_assistant:
            return False

        overlap = normalized_latest & normalized_assistant
        return bool(overlap)

    def _is_direct_followup_to_ai(
        self,
        historical_context: List[Dict],
        recent_dialogue: List[Dict],
        air_signal: AirReadingSignal,
    ) -> bool:
        """判断当前轮是否明显在继续接 AI 的上一轮话题。"""
        score = self._score_direct_followup_to_ai(
            historical_context,
            recent_dialogue,
            air_signal,
        )
        return score >= self.config_manager.observation_followup_score_threshold

    def _score_direct_followup_to_ai(
        self,
        historical_context: List[Dict],
        recent_dialogue: List[Dict],
        air_signal: AirReadingSignal,
    ) -> int:
        """为“是否明显在继续接 AI 聊天”打分。"""
        if not recent_dialogue:
            return 0

        latest_user_message = None
        user_messages = [message for message in recent_dialogue if message.get("role") == "user"]
        if user_messages:
            latest_user_message = user_messages[-1]

        if not latest_user_message:
            return 0

        previous_messages = [msg for msg in historical_context if isinstance(msg, dict)]
        if not previous_messages:
            return 0

        last_processed = previous_messages[-1]
        if last_processed.get("role") != "assistant":
            return 0

        latest_text = self._extract_message_text(latest_user_message)
        assistant_text = self._extract_message_text(last_processed)
        latest_ts = float(latest_user_message.get("timestamp") or 0)
        assistant_ts = float(last_processed.get("timestamp") or 0)
        time_gap = latest_ts - assistant_ts if latest_ts > 0 and assistant_ts > 0 else 999999

        score = 0
        reply_self = latest_user_message.get("summon_source") == "reply_self"
        directed = air_signal.conversation_mode == "directed_to_ai"
        same_sender_streak = False
        short_phrase = False
        question_phrase = False
        feedback_phrase = False
        carry_over = False
        text_overlap = False

        if reply_self:
            score += 5
        if directed:
            score += 4
        if time_gap <= self.config_manager.observation_followup_time_window:
            score += 2
        if len(user_messages) >= 2:
            sender_ids = [str(msg.get("sender_id") or "") for msg in user_messages[-3:]]
            if len(set(sender_ids)) == 1 and sender_ids[0]:
                same_sender_streak = True
                score += 2
        if latest_text:
            lowered = latest_text.lower()
            if self._contains_any_phrase(lowered, self.config_manager.observation_followup_short_phrases):
                short_phrase = True
                score += 2
            if self._contains_any_phrase(lowered, self.config_manager.observation_followup_question_phrases):
                question_phrase = True
                score += 3
            if self._contains_any_phrase(lowered, self.config_manager.observation_followup_feedback_phrases):
                feedback_phrase = True
                score += 3
            if len(latest_text) <= 6:
                score += 1
        if self._should_bypass_observation_threshold(historical_context, [latest_user_message], air_signal):
            carry_over = True
            score += 3
        if latest_text and assistant_text:
            normalized_latest = set(self._tokenize_text(latest_text))
            normalized_assistant = set(self._tokenize_text(assistant_text))
            if normalized_latest and normalized_assistant and (normalized_latest & normalized_assistant):
                text_overlap = True
                score += 2

        logger.info(
            f"观测态续聊评分 | score={score} | threshold={self.config_manager.observation_followup_score_threshold} "
            f"| time_gap={int(time_gap) if time_gap < 999999 else -1}s | directed={directed} | reply_self={reply_self} "
            f"| same_sender_streak={same_sender_streak} | short_phrase={short_phrase} "
            f"| question_phrase={question_phrase} | feedback_phrase={feedback_phrase} "
            f"| carry_over={carry_over} | text_overlap={text_overlap}"
        )

        return score

    def _apply_observation_followup_override(
        self,
        chat_id: str,
        decision: SecretaryDecision,
        historical_context: List[Dict],
        recent_dialogue: List[Dict],
        air_signal: AirReadingSignal,
    ) -> None:
        """观测态下，如果明显在接 AI 聊天，则对不回复结果做后置强放行。"""
        if not decision or decision.should_reply:
            return

        if air_signal.suppression_reason == "heated_conflict":
            return

        followup_score = self._score_direct_followup_to_ai(
            historical_context,
            recent_dialogue,
            air_signal,
        )
        threshold = self.config_manager.observation_followup_score_threshold
        if followup_score < threshold:
            return

        logger.info(
            f"AngelHeart[{chat_id}]: 命中明显续聊 AI，覆盖轻量模型的“不参与”结果，强制放行本轮回复。score={followup_score}/{threshold}"
        )
        decision.should_reply = True
        decision.is_directly_addressed = True
        decision.reply_strategy = "直接续聊放行"
        if not decision.reply_target:
            latest_user = next(
                (msg for msg in reversed(recent_dialogue) if msg.get("role") == "user"),
                None,
            )
            if latest_user:
                decision.reply_target = str(
                    latest_user.get("sender_name")
                    or latest_user.get("sender_id")
                    or ""
                )
        if not decision.topic or decision.topic == "未知":
            decision.topic = "延续上一轮对话"

    def _extract_message_text(self, message: Dict) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = str(item.get("text") or "").strip()
                    if text:
                        texts.append(text)
            return " ".join(texts).strip()
        return ""

    def _tokenize_text(self, text: str) -> List[str]:
        normalized = str(text or "").strip().lower()
        normalized = "".join(ch if (ch.isalnum() or "\u4e00" <= ch <= "\u9fff") else " " for ch in normalized)
        return [token for token in normalized.split() if len(token) >= 2]

    def _contains_any_phrase(self, lowered_text: str, phrases: List[str]) -> bool:
        """判断文本是否命中任一配置短语。"""
        if not lowered_text:
            return False
        return any(str(phrase).strip().lower() in lowered_text for phrase in phrases if str(phrase).strip())

    def _build_air_signal(
        self,
        chat_id: str,
        historical_context: List[Dict],
        recent_dialogue: List[Dict],
        current_status: AngelHeartStatus,
        allow_suppression: bool,
    ) -> AirReadingSignal:
        """构建当前轮的读空气信号。"""
        if not self.config_manager.air_reading_enabled:
            return AirReadingSignal()

        return self.air_reading_analyzer.analyze(
            chat_id=chat_id,
            historical_context=historical_context,
            recent_dialogue=recent_dialogue,
            current_status=current_status,
            allow_suppression=allow_suppression,
        )

    def _prepare_air_analysis(
        self,
        chat_id: str,
        current_status: AngelHeartStatus,
        allow_suppression: bool,
    ) -> tuple[List[Dict], List[Dict], AirReadingSignal]:
        """统一获取上下文快照和读空气信号。"""
        historical_context, recent_dialogue, _ = (
            self.angel_context.conversation_ledger.get_context_snapshot(chat_id)
        )
        air_signal = self._build_air_signal(
            chat_id,
            historical_context,
            recent_dialogue,
            current_status,
            allow_suppression=allow_suppression,
        )
        return historical_context, recent_dialogue, air_signal

    def _get_latest_user_message(self, recent_dialogue: List[Dict]) -> Dict | None:
        for message in reversed(recent_dialogue):
            if message.get("role") == "user":
                return message
        return None

    def _is_command_like_wake(self, event: AstrMessageEvent, latest_user_message: Dict | None) -> bool:
        if not getattr(event, "is_at_or_wake_command", False):
            return False
        if latest_user_message and latest_user_message.get("summon_source") in {"at_self", "reply_self"}:
            return False
        activated_handlers = event.get_extra("activated_handlers", []) or []
        return bool(activated_handlers)

    def _build_decision_envelope(
        self,
        event: AstrMessageEvent,
        current_status: AngelHeartStatus,
        historical_context: List[Dict],
        recent_dialogue: List[Dict],
        air_signal: AirReadingSignal,
    ):
        latest_user_message = self._get_latest_user_message(recent_dialogue)
        thread_window = self.thread_window_builder.build(historical_context, recent_dialogue)
        followup_score = self._score_direct_followup_to_ai(
            historical_context,
            recent_dialogue,
            air_signal,
        )
        thread_window.followup_score = followup_score
        thread_window.engagement_hint = air_signal.engagement_hint
        snapshot = self.decision_pipeline.build_snapshot(
            status=current_status,
            thread_window=thread_window,
            air_signal=air_signal,
            latest_user_message=latest_user_message,
            followup_score=followup_score,
            command_like_wake=self._is_command_like_wake(event, latest_user_message),
        )
        return self.decision_pipeline.start_envelope(snapshot, current_status)

    def _apply_envelope_to_decision(self, decision: SecretaryDecision, envelope) -> SecretaryDecision:
        llm_review = {
            "needs_reply_now": decision.should_reply,
            "addressing_mode": decision.addressing_mode or "unclear",
            "reply_value": decision.reply_value or ("high" if decision.is_interesting else "low"),
        }
        envelope = self.decision_pipeline.apply_llm_review(envelope, llm_review)
        snapshot = envelope.snapshot

        decision.hard_allow = snapshot.hard_allow
        decision.hard_suppress = snapshot.hard_suppress
        decision.followup_score = snapshot.followup_score
        decision.thread_topic = snapshot.thread_window.thread_topic_hint
        decision.final_reason = envelope.final_reason
        if decision.addressing_mode == "unclear":
            if snapshot.hard_allow:
                decision.addressing_mode = "to_ai"
            elif snapshot.hard_suppress and snapshot.hard_suppress_reason == "human_private_exchange":
                decision.addressing_mode = "to_human"

        decision.should_reply = envelope.final_should_reply
        if not decision.reply_strategy or decision.reply_strategy == "继续观察":
            decision.reply_strategy = envelope.final_reason or "继续观察"
        if not decision.topic or decision.topic == "未知":
            decision.topic = snapshot.thread_window.thread_topic_hint or "未知"
        if not decision.reply_target:
            decision.reply_target = snapshot.thread_window.thread_target_hint
        return decision

    def _decision_from_envelope(self, envelope, fallback_topic: str) -> SecretaryDecision:
        snapshot = envelope.snapshot
        return SecretaryDecision(
            should_reply=envelope.final_should_reply,
            reply_strategy=envelope.final_reason or "继续观察",
            topic=snapshot.thread_window.thread_topic_hint or fallback_topic,
            reply_target=snapshot.thread_window.thread_target_hint,
            air_score=snapshot.air_score,
            followup_score=snapshot.followup_score,
            should_suppress=snapshot.hard_suppress,
            suppression_reason=snapshot.hard_suppress_reason,
            conversation_mode="general_discussion",
            engagement_hint=snapshot.thread_window.engagement_hint,
            hard_allow=snapshot.hard_allow,
            hard_suppress=snapshot.hard_suppress,
            final_reason=envelope.final_reason,
            thread_topic=snapshot.thread_window.thread_topic_hint,
            entities=[],
            facts=[],
            keywords=[],
        )

    def _attach_air_signal(self, decision: SecretaryDecision, air_signal: AirReadingSignal) -> SecretaryDecision:
        """把读空气信号附着到决策对象。"""
        decision.air_score = air_signal.air_score
        decision.should_suppress = air_signal.should_suppress
        decision.suppression_reason = air_signal.suppression_reason
        decision.conversation_mode = air_signal.conversation_mode
        decision.engagement_hint = air_signal.engagement_hint
        return decision

    def _build_suppressed_decision(self, air_signal: AirReadingSignal, topic: str) -> SecretaryDecision:
        """构造一个被读空气压制的不参与决策。"""
        decision = SecretaryDecision(
            should_reply=False,
            reply_strategy=air_signal.suppression_reason or "继续观察",
            topic=topic,
            entities=[],
            facts=[],
            keywords=[],
        )
        return self._attach_air_signal(decision, air_signal)

    def _log_air_reading_signal(self, chat_id: str, air_signal: AirReadingSignal) -> None:
        """输出统一的读空气诊断日志。"""
        logger.info(
            f"AngelHeart[{chat_id}]: 读空气预判 | mode={air_signal.conversation_mode} "
            f"| score={air_signal.air_score} | suppress={air_signal.should_suppress} "
            f"| reason={air_signal.suppression_reason or 'none'} "
            f"| engagement={air_signal.engagement_hint}"
        )
        if air_signal.should_suppress:
            logger.info(
                f"AngelHeart[{chat_id}]: 读空气压制 | reason={air_signal.suppression_reason or 'continue_observing'} "
                f"| score={air_signal.air_score}"
            )
        else:
            logger.info(
                f"AngelHeart[{chat_id}]: 读空气放行 | mode={air_signal.conversation_mode} "
                f"| score={air_signal.air_score}"
            )

    def _log_decision_envelope(self, chat_id: str, envelope) -> None:
        snapshot = envelope.snapshot
        logger.info(
            f"DecisionGate[{chat_id}] | status={envelope.status_name} "
            f"| hard_allow={snapshot.hard_allow}:{snapshot.hard_allow_reason or 'none'} "
            f"| hard_suppress={snapshot.hard_suppress}:{snapshot.hard_suppress_reason or 'none'} "
            f"| air_score={snapshot.air_score} | followup_score={snapshot.followup_score} "
            f"| thread_confidence={snapshot.thread_window.thread_confidence}"
        )
        logger.info(
            f"ThreadWindow[{chat_id}] | topic={snapshot.thread_window.thread_topic_hint or '未知'} "
            f"| target={snapshot.thread_window.thread_target_hint or '未知'} "
            f"| messages={len(snapshot.thread_window.current_thread_messages)} "
            f"| burst={len(snapshot.thread_window.latest_user_burst)}"
        )

    def _log_analysis_result(self, chat_id: str, state_name: str, decision: SecretaryDecision) -> None:
        """统一记录秘书分析结果，便于直接观察参与/不参与结论。"""
        strategy = decision.reply_strategy or "未提供原因"
        topic = decision.topic or "未知"

        if decision.should_reply:
            logger.info(
                f"AngelHeart[{chat_id}]: 秘书分析完成，决定参与回复。状态: {state_name}，"
                f"策略: {strategy}，话题: {topic}"
            )
            return

        logger.info(
            f"AngelHeart[{chat_id}]: 秘书分析完成，决定不参与回复。状态: {state_name}，"
            f"原因: {strategy}，话题: {topic}"
        )

    async def _handle_not_present_check(self, event: AstrMessageEvent, chat_id: str) -> SecretaryDecision:
        """处理不在场状态 - 检查触发条件"""
        try:
            logger.debug(f"AngelHeart[{chat_id}]: 秘书处理不在场状态，检查触发条件")

            # 判断状态
            new_status = await self.status_checker.determine_status(chat_id)

            # 如果需要转换状态
            if new_status in [AngelHeartStatus.GETTING_FAMILIAR, AngelHeartStatus.SUMMONED]:
                logger.info(f"AngelHeart[{chat_id}]: 秘书检测到触发条件，状态: {new_status.value}")

                # 转换状态
                await self.angel_context.status_transition_manager.transition_to_status(
                    chat_id, new_status, f"触发条件：{new_status.value}"
                )

                # 根据新状态直接调用对应的处理方法
                if new_status == AngelHeartStatus.GETTING_FAMILIAR:
                    return await self._handle_familiarity_reply(event, chat_id)
                elif new_status == AngelHeartStatus.SUMMONED:
                    return await self._handle_summoned_reply(event, chat_id)
            else:
                logger.debug(f"AngelHeart[{chat_id}]: 秘书判断无触发条件，保持不在场")
                return SecretaryDecision(
                    should_reply=False, reply_strategy="不在场", topic="未知",
                    entities=[], facts=[], keywords=[]
                )

        except Exception as e:
            logger.error(f"AngelHeart[{chat_id}]: 秘书不在场状态处理异常: {e}", exc_info=True)
            return SecretaryDecision(
                should_reply=False, reply_strategy="处理异常", topic="未知",
                entities=[], facts=[], keywords=[]
            )

    async def perform_analysis(
        self,
        recent_dialogue: List[Dict],
        db_history: List[Dict],
        chat_id: str,
        air_signal: AirReadingSignal | None = None,
    ) -> SecretaryDecision:
        """
        秘书职责：分析缓存内容并做出决策。
        此函数只负责调用LLM分析器，不再关心缓存和历史记录的剪枝。

        Args:
            recent_dialogue (List[Dict]): 剪枝后的新消息列表。
            db_history (List[Dict]): 数据库中的历史记录。
            chat_id (str): 会话ID。

        Returns:
            SecretaryDecision: 分析后得出的决策对象。
        """
        logger.info(f"AngelHeart[{chat_id}]: 秘书开始调用LLM进行分析...")

        try:
            # 调用分析器进行决策，传递结构化的上下文
            decision = await self.llm_analyzer.analyze_and_decide(
                historical_context=db_history,
                recent_dialogue=recent_dialogue,
                chat_id=chat_id,
                air_signal=air_signal,
            )

            # 移除重复日志，已在 process_notification 中记录
            return decision

        except asyncio.TimeoutError as e:
            return self._handle_analysis_error(e, "秘书处理过程(超时)", chat_id)
        except Exception as e:
            return self._handle_analysis_error(e, "秘书处理过程", chat_id)

    def get_decision(self, chat_id: str) -> SecretaryDecision | None:
        """获取指定会话的决策"""
        return self.angel_context.get_decision(chat_id)

    async def update_last_event_time(self, chat_id: str):
        """在 LLM 成功响应后，更新最后一次事件（回复）的时间戳"""
        await self.angel_context.update_last_analysis_time(chat_id)

    async def clear_decision(self, chat_id: str):
        """清除指定会话的决策"""
        await self.angel_context.clear_decision(chat_id)


    def get_cached_decisions_for_display(self) -> list:
        """获取用于状态显示的缓存决策列表"""
        cached_items = list(self.angel_context.analysis_cache.items())
        display_list = []
        for chat_id, result in reversed(cached_items[-5:]): # 显示最近的5条
            if result:
                topic = result.topic
                display_list.append(f"- {chat_id}:")
                display_list.append(f"  - 话题: {topic}")
            else:
                display_list.append(f"- {chat_id}: (分析数据不完整)")
        return display_list




    @property
    def config_manager(self):
        return self._config_manager

    @config_manager.setter
    def config_manager(self, value):
        self._config_manager = value

    @property
    def waiting_time(self):
        return self.config_manager.waiting_time

    @property
    def cache_expiry(self):
        return self.config_manager.cache_expiry

    def _handle_analysis_error(self, error: Exception, context: str, chat_id: str) -> SecretaryDecision:
        """
        统一处理分析错误

        Args:
            error (Exception): 捕获到的异常
            context (str): 错误发生的上下文描述
            chat_id (str): 会话ID

        Returns:
            SecretaryDecision: 表示分析失败的决策对象
        """
        logger.error(
            f"AngelHeart[{chat_id}]: {context}出错: {error}", exc_info=True
        )
        # 返回一个默认的不参与决策
        return SecretaryDecision(
            should_reply=False, reply_strategy=f"{context}失败", topic="未知",
            entities=[], facts=[], keywords=[]
        )

    # ========== 4状态机制：状态感知分析 ==========

    async def process_notification(self, event: AstrMessageEvent):
        """
        处理前台通知
        秘书只负责处理消息，不做任何条件检查
        注意：调用此方法时，前台已经获取了门锁

        Args:
            event: 消息事件
        """
        chat_id = event.unified_msg_origin

        try:
            # 1. 获取上下文
            historical_context, recent_dialogue, boundary_ts = self.angel_context.conversation_ledger.get_context_snapshot(chat_id)

            if not recent_dialogue:
                logger.info(f"AngelHeart[{chat_id}]: 无新消息需要分析。")
                return

            # 2. 执行分析
            decision = await self.perform_analysis(recent_dialogue, historical_context, chat_id)

            # 3. 处理决策结果
            await self._handle_analysis_result(decision, recent_dialogue, historical_context, boundary_ts, event, chat_id)

        except Exception as e:
            logger.error(f"AngelHeart[{chat_id}]: 秘书处理异常: {e}", exc_info=True)



    async def _handle_analysis_result(self, decision, recent_dialogue, historical_context, boundary_ts, event, chat_id):
        """
        处理分析结果（复用原有逻辑）

        注意：此方法不返回任何值，锁的释放由调用者的 finally 块统一处理
        """
        if decision and decision.should_reply:
            logger.info(f"AngelHeart[{chat_id}]: 决策为'参与'。策略: {decision.reply_strategy}")

            # 图片转述处理
            try:
                cfg = self.context.get_config(umo=event.unified_msg_origin)["provider_settings"]
                caption_provider_id = cfg.get("default_image_caption_provider_id", "")
            except Exception as e:
                logger.warning(f"AngelHeart[{chat_id}]: 无法读取图片转述配置: {e}")
                caption_provider_id = ""

            caption_count = await self.angel_context.conversation_ledger.process_image_captions_if_needed(
                chat_id=chat_id,
                caption_provider_id=caption_provider_id,
                astr_context=self.context
            )
            if caption_count > 0:
                logger.info(f"AngelHeart[{chat_id}]: 已为 {caption_count} 张图片生成转述")

            # 存储决策
            await self.angel_context.update_analysis_cache(chat_id, decision, reason="分析完成")

            # 启动耐心计时器
            await self.angel_context.start_patience_timer(chat_id)

            # 标记对话为已处理
            self.angel_context.conversation_ledger.mark_as_processed(chat_id, boundary_ts)

            # 注入上下文
            full_snapshot = historical_context + recent_dialogue
            try:
                event.angelheart_context = json_serialize_context(full_snapshot, decision)
                logger.info(f"AngelHeart[{chat_id}]: 上下文已注入 event.angelheart_context")
            except Exception as e:
                logger.error(f"AngelHeart[{chat_id}]: 注入上下文失败: {e}")
                event.angelheart_context = json.dumps({
                    "chat_records": [],
                    "secretary_decision": {"should_reply": False, "error": "注入失败"},
                    "needs_search": False,
                    "error": "注入失败"
                }, ensure_ascii=False)

            # 唤醒主脑
            if not self.config_manager.debug_mode:
                event.is_at_or_wake_command = True
            else:
                logger.info(f"AngelHeart[{chat_id}]: 调试模式已启用，阻止了实际唤醒。")

        elif decision:
            logger.info(f"AngelHeart[{chat_id}]: 决策为'不参与'。原因: {decision.reply_strategy}")
            await self.angel_context.clear_decision(chat_id)
            self.angel_context.conversation_ledger.mark_as_processed(chat_id, boundary_ts)
        else:
            logger.warning(f"AngelHeart[{chat_id}]: 分析失败，无决策结果")
            await self.angel_context.clear_decision(chat_id)
            self.angel_context.conversation_ledger.mark_as_processed(chat_id, boundary_ts)
