"""AngelHeart 插件 - 当前线程窗口提取器"""

from __future__ import annotations

import re

from typing import Dict, List

from ..models.decision_context import ThreadWindow
from .utils.content_utils import convert_content_to_string


class ThreadWindowBuilder:
    """从历史消息和未处理消息中提取“当前线程”窗口。"""

    BURST_WINDOW_SECONDS = 20
    MAX_THREAD_MESSAGES = 8
    MAX_TOPIC_HINT_LENGTH = 80

    def __init__(self, config_manager):
        self.config_manager = config_manager

    def build(self, historical_context: List[Dict], recent_dialogue: List[Dict]) -> ThreadWindow:
        last_assistant_turn = self._find_last_assistant_turn(historical_context)
        latest_user_burst = self._build_latest_user_burst(recent_dialogue)
        current_thread_messages = self._build_current_thread_messages(
            historical_context,
            recent_dialogue,
            last_assistant_turn,
            latest_user_burst,
        )
        topic_hint = self._derive_topic_hint(latest_user_burst, last_assistant_turn)
        target_hint = self._derive_target_hint(latest_user_burst)
        was_truncated = self._was_recent_window_truncated(recent_dialogue, current_thread_messages)
        thread_confidence = self._derive_thread_confidence(
            latest_user_burst,
            last_assistant_turn,
            current_thread_messages,
            was_truncated,
        )

        return ThreadWindow(
            current_thread_messages=current_thread_messages,
            last_assistant_turn=last_assistant_turn,
            latest_user_burst=latest_user_burst,
            thread_topic_hint=topic_hint,
            thread_target_hint=target_hint,
            thread_confidence=thread_confidence,
        )

    def _find_last_assistant_turn(self, historical_context: List[Dict]) -> Dict | None:
        for message in reversed(historical_context):
            if message.get("role") == "assistant":
                return message
        return None

    def _build_latest_user_burst(self, recent_dialogue: List[Dict]) -> List[Dict]:
        user_messages = [message for message in recent_dialogue if message.get("role") == "user"]
        if not user_messages:
            return []

        burst = [user_messages[-1]]
        latest = user_messages[-1]
        latest_sender = str(latest.get("sender_id") or "")
        latest_ts = float(latest.get("timestamp") or 0)

        for previous in reversed(user_messages[:-1]):
            prev_sender = str(previous.get("sender_id") or "")
            prev_ts = float(previous.get("timestamp") or 0)
            if (
                latest_sender
                and prev_sender == latest_sender
                and 0 <= latest_ts - prev_ts <= self.BURST_WINDOW_SECONDS
            ):
                burst.insert(0, previous)
                latest_ts = prev_ts
                continue
            break

        return burst

    def _build_current_thread_messages(
        self,
        historical_context: List[Dict],
        recent_dialogue: List[Dict],
        last_assistant_turn: Dict | None,
        latest_user_burst: List[Dict],
    ) -> List[Dict]:
        if not latest_user_burst:
            return []

        anchor_ts = 0.0
        if last_assistant_turn:
            anchor_ts = float(last_assistant_turn.get("timestamp") or 0)

        messages: List[Dict] = []
        if last_assistant_turn:
            messages.append(last_assistant_turn)

        for message in recent_dialogue:
            ts = float(message.get("timestamp") or 0)
            if anchor_ts and ts < anchor_ts:
                continue
            messages.append(message)

        return messages[-self.MAX_THREAD_MESSAGES:]

    def _derive_topic_hint(self, latest_user_burst: List[Dict], last_assistant_turn: Dict | None) -> str:
        if latest_user_burst:
            user_text = self._clean_topic_hint(
                " ".join(self._message_text(message) for message in latest_user_burst)
            )
            if user_text:
                return user_text[:self.MAX_TOPIC_HINT_LENGTH]
        if last_assistant_turn:
            return self._clean_topic_hint(self._message_text(last_assistant_turn))[:self.MAX_TOPIC_HINT_LENGTH]
        return ""

    def _derive_target_hint(self, latest_user_burst: List[Dict]) -> str:
        if not latest_user_burst:
            return ""
        latest = latest_user_burst[-1]
        return str(latest.get("sender_name") or latest.get("sender_id") or "")

    def _derive_thread_confidence(
        self,
        latest_user_burst: List[Dict],
        last_assistant_turn: Dict | None,
        current_thread_messages: List[Dict],
        was_truncated: bool,
    ) -> int:
        score = 0
        if latest_user_burst:
            score += 3
        if len(latest_user_burst) >= 2:
            score += 2
        if len(current_thread_messages) >= 2:
            score += 2

        # 有最近助手锚点时，线程归属更可信；没有锚点时主动降权。
        if last_assistant_turn:
            score += 3
        else:
            score -= 2

        # recent 被 8 条窗口截断时，说明当前线程只拿到了尾部片段。
        if was_truncated:
            score -= 2

        return max(0, min(score, 10))

    def _message_text(self, message: Dict) -> str:
        return convert_content_to_string(message.get("content", ""))

    def _clean_topic_hint(self, text: str) -> str:
        cleaned = str(text or "")
        cleaned = re.sub(r"\[引用消息\([^\]]*\)\]", " ", cleaned)
        cleaned = re.sub(r"\[At:[^\]]*\]", " ", cleaned)
        cleaned = re.sub(r"\[表情:[^\]]*\]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def _was_recent_window_truncated(self, recent_dialogue: List[Dict], current_thread_messages: List[Dict]) -> bool:
        if not recent_dialogue or not current_thread_messages:
            return False
        return (
            len(recent_dialogue) > len(current_thread_messages)
            and len(current_thread_messages) >= self.MAX_THREAD_MESSAGES
        )
