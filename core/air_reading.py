"""AngelHeart 插件 - 读空气预筛模块"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Pattern
import re

from .angel_heart_status import AngelHeartStatus
from .utils.content_utils import convert_content_to_string

try:
    from astrbot.api import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


@dataclass
class AirReadingSignal:
    """本地规则生成的读空气信号。"""

    air_score: int = 0
    should_suppress: bool = False
    suppression_reason: str = ""
    conversation_mode: str = "general_discussion"
    engagement_hint: str = "unknown"

    def to_prompt_block(self) -> str:
        """转成可注入提示词的文本块。"""
        return (
            f"- air_score: {self.air_score}\n"
            f"- should_suppress: {'true' if self.should_suppress else 'false'}\n"
            f"- suppression_reason: {self.suppression_reason or 'none'}\n"
            f"- conversation_mode: {self.conversation_mode}\n"
            f"- engagement_hint: {self.engagement_hint}\n"
        )


class AirReadingAnalyzer:
    """本地可解释的读空气评分器。"""

    QUESTION_MARKERS = (
        "?",
        "？",
        "怎么",
        "咋",
        "如何",
        "为什么",
        "能不能",
        "可以吗",
        "行吗",
        "帮我",
        "求",
        "问下",
        "请问",
        "有没有",
    )
    MIN_SCORE = -10
    MAX_SCORE = 10
    MODE_DIRECTED = "directed_to_ai"
    MODE_HUMAN = "human_to_human"
    MODE_HEATED = "heated"
    MODE_SMALLTALK = "small_talk"
    MODE_GENERAL = "general_discussion"
    ENGAGEMENT_UNKNOWN = "unknown"
    ENGAGEMENT_IGNORED = "ignored_recently"
    ENGAGEMENT_WELCOMED = "welcomed_recently"

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self._alias_cache_key = ""
        self._alias_cache: List[str] = []
        self._heated_keywords_cache_key = ""
        self._heated_keywords_regex: Pattern[str] | None = None
        self._smalltalk_patterns_cache_key = ""
        self._smalltalk_regex: Pattern[str] | None = None

    def analyze(
        self,
        chat_id: str,
        historical_context: List[Dict],
        recent_dialogue: List[Dict],
        current_status: AngelHeartStatus,
        allow_suppression: bool = True,
    ) -> AirReadingSignal:
        """基于短时窗口生成读空气信号。"""
        combined_messages = (historical_context + recent_dialogue)[-20:]
        recent_user_messages = [msg for msg in recent_dialogue if msg.get("role") == "user"]
        latest_user_message = recent_user_messages[-1] if recent_user_messages else None

        if not latest_user_message:
            return AirReadingSignal()

        latest_text = self._message_text(latest_user_message)
        directed_to_ai = self._is_directed_to_ai(latest_user_message)
        questioned = self._looks_like_question_or_request(latest_text)
        heated = self._is_heated(combined_messages)
        non_ai_addressed = self._mentions_non_ai_target(latest_text, directed_to_ai)
        human_to_human = self._is_human_to_human_exchange(recent_user_messages, directed_to_ai)
        small_talk = self._is_smalltalk(recent_user_messages)
        engagement_hint = self._infer_engagement_hint(combined_messages)

        score = 0
        if directed_to_ai:
            score += 6
        if latest_user_message.get("summon_source") == "reply_self":
            score += 5
        if questioned:
            score += 2
        if non_ai_addressed and self.config_manager.air_reading_suppress_human_to_human:
            score -= 4
        if human_to_human and self.config_manager.air_reading_suppress_human_to_human:
            score -= 3
        if small_talk and self.config_manager.air_reading_suppress_smalltalk:
            score -= 2
        if heated and self.config_manager.air_reading_suppress_heated:
            score -= 6
        if (
            engagement_hint == self.ENGAGEMENT_IGNORED
            and self.config_manager.air_reading_suppress_ignored_recently
        ):
            score -= 4
        elif engagement_hint == "welcomed_recently":
            score += 2

        score = max(self.MIN_SCORE, min(self.MAX_SCORE, score))

        if directed_to_ai:
            conversation_mode = self.MODE_DIRECTED
        elif heated:
            conversation_mode = self.MODE_HEATED
        elif human_to_human:
            conversation_mode = self.MODE_HUMAN
        elif small_talk:
            conversation_mode = self.MODE_SMALLTALK
        else:
            conversation_mode = self.MODE_GENERAL

        suppression_reason = ""
        should_suppress = False
        threshold = self.config_manager.air_reading_suppress_threshold

        if allow_suppression and not directed_to_ai and latest_user_message.get("summon_source") != "reply_self":
            if heated and self.config_manager.air_reading_suppress_heated:
                should_suppress = True
                suppression_reason = "heated_conflict"
            elif (
                non_ai_addressed
                and human_to_human
                and self.config_manager.air_reading_suppress_human_to_human
            ):
                should_suppress = True
                suppression_reason = "human_private_exchange"
            elif (
                engagement_hint == self.ENGAGEMENT_IGNORED
                and self.config_manager.air_reading_suppress_ignored_recently
            ):
                should_suppress = True
                suppression_reason = self.ENGAGEMENT_IGNORED
            elif (
                current_status == AngelHeartStatus.GETTING_FAMILIAR
                and self.config_manager.air_reading_suppress_smalltalk
                and (small_talk or human_to_human)
            ):
                should_suppress = True
                suppression_reason = "low_value_smalltalk"
            elif score <= threshold and self.config_manager.air_reading_suppress_smalltalk:
                should_suppress = True
                suppression_reason = (
                    "human_private_exchange" if human_to_human else "low_value_smalltalk"
                )

        signal = AirReadingSignal(
            air_score=score,
            should_suppress=should_suppress,
            suppression_reason=suppression_reason,
            conversation_mode=conversation_mode,
            engagement_hint=engagement_hint,
        )

        logger.debug(
            f"AngelHeart[{chat_id}]: 读空气内部信号 score={signal.air_score} "
            f"mode={signal.conversation_mode} suppress={signal.should_suppress} "
            f"reason={signal.suppression_reason or 'none'} engagement={signal.engagement_hint}"
        )
        return signal

    def _message_text(self, message: Dict) -> str:
        return convert_content_to_string(message.get("content", ""))

    def _is_directed_to_ai(self, message: Dict) -> bool:
        if message.get("is_directed_to_bot"):
            return True

        text = self._message_text(message)
        aliases = self._get_aliases()
        normalized = text.lower()
        return any(alias in normalized for alias in aliases)

    def _looks_like_question_or_request(self, text: str) -> bool:
        if not text:
            return False
        return any(marker in text.lower() for marker in self.QUESTION_MARKERS)

    def _mentions_non_ai_target(self, text: str, directed_to_ai: bool) -> bool:
        if directed_to_ai or not text:
            return False
        if "[引用消息(" in text:
            return True
        if "@" in text:
            return True
        return False

    def _is_human_to_human_exchange(self, recent_user_messages: List[Dict], directed_to_ai: bool) -> bool:
        if directed_to_ai:
            return False

        window = recent_user_messages[-4:]
        if len(window) < 3:
            return False

        sender_ids = [str(msg.get("sender_id", "")) for msg in window if msg.get("sender_id")]
        unique_senders = set(sender_ids)
        if len(unique_senders) < 2:
            return False

        alternating_turns = 0
        for prev, curr in zip(sender_ids, sender_ids[1:]):
            if prev != curr:
                alternating_turns += 1

        return alternating_turns >= 2

    def _is_smalltalk(self, recent_user_messages: List[Dict]) -> bool:
        regex = self._get_smalltalk_regex()
        if not regex:
            return False
        short_messages = recent_user_messages[-3:]
        if len(short_messages) < 2:
            return False

        matched = 0
        for msg in short_messages:
            text = self._message_text(msg)
            if len(text) <= 12 and regex.search(text):
                matched += 1

        return matched >= 2

    def _is_heated(self, messages: List[Dict]) -> bool:
        regex = self._get_heated_keywords_regex()
        if not regex:
            return False
        for msg in messages[-6:]:
            if msg.get("role") != "user":
                continue
            text = self._message_text(msg)
            if text and regex.search(text):
                return True
        return False

    def _infer_engagement_hint(self, messages: List[Dict]) -> str:
        last_assistant_index = -1
        for idx in range(len(messages) - 1, -1, -1):
            if messages[idx].get("role") == "assistant":
                last_assistant_index = idx
                break

        if last_assistant_index < 0:
            return self.ENGAGEMENT_UNKNOWN

        followup_users = [
            msg for msg in messages[last_assistant_index + 1 :] if msg.get("role") == "user"
        ]
        if not followup_users:
            return self.ENGAGEMENT_UNKNOWN

        if any(self._is_directed_to_ai(msg) for msg in followup_users):
            return self.ENGAGEMENT_WELCOMED

        if len(followup_users) >= self.config_manager.air_reading_ignore_window_messages:
            return self.ENGAGEMENT_IGNORED

        return self.ENGAGEMENT_UNKNOWN

    def _get_aliases(self) -> List[str]:
        """缓存解析后的别名列表，避免每轮重复 split。"""
        alias_str = str(self.config_manager.alias or "")
        if alias_str != self._alias_cache_key:
            self._alias_cache_key = alias_str
            self._alias_cache = [name.strip().lower() for name in alias_str.split("|") if name.strip()]
        return self._alias_cache

    def _get_heated_keywords_regex(self) -> Pattern[str] | None:
        """按配置缓存火药味关键词正则。"""
        keywords = self.config_manager.air_reading_heated_keywords
        cache_key = "|".join(keywords)
        if cache_key != self._heated_keywords_cache_key:
            self._heated_keywords_cache_key = cache_key
            self._heated_keywords_regex = self._compile_keywords_regex(keywords)
        return self._heated_keywords_regex

    def _get_smalltalk_regex(self) -> Pattern[str] | None:
        """按配置缓存寒暄关键词正则。"""
        patterns = self.config_manager.air_reading_smalltalk_patterns
        cache_key = "|".join(patterns)
        if cache_key != self._smalltalk_patterns_cache_key:
            self._smalltalk_patterns_cache_key = cache_key
            self._smalltalk_regex = self._compile_keywords_regex(patterns)
        return self._smalltalk_regex

    def _compile_keywords_regex(self, items: List[str]) -> Pattern[str] | None:
        """编译关键词正则；空列表时返回 None。"""
        if not items:
            return None
        return re.compile("|".join(re.escape(item) for item in items), re.IGNORECASE)
