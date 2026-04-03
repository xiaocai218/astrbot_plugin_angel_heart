from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ThreadWindow:
    """当前轮用于判断是否该接话的线程窗口。"""

    current_thread_messages: List[Dict] = field(default_factory=list)
    last_assistant_turn: Optional[Dict] = None
    latest_user_burst: List[Dict] = field(default_factory=list)
    thread_topic_hint: str = ""
    thread_target_hint: str = ""
    thread_confidence: int = 0
    followup_score: int = 0
    engagement_hint: str = "unknown"


@dataclass
class ConversationCueSnapshot:
    """本地规则提取出的结构化线索。"""

    thread_window: ThreadWindow
    hard_allow: bool = False
    hard_allow_reason: str = ""
    hard_suppress: bool = False
    hard_suppress_reason: str = ""
    air_score: int = 0
    followup_score: int = 0
    command_like_wake: bool = False
    has_recent_context: bool = False


@dataclass
class DecisionEnvelope:
    """统一的决策信封，收口各阶段结果。"""

    snapshot: ConversationCueSnapshot
    status_name: str = ""
    needs_llm_review: bool = True
    llm_review: Dict = field(default_factory=dict)
    final_should_reply: bool = False
    final_reason: str = ""
