import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from astrbot_plugin_angel_heart.core.air_reading import AirReadingAnalyzer, AirReadingSignal
from astrbot_plugin_angel_heart.core.llm_analyzer import LLMAnalyzer
from astrbot_plugin_angel_heart.core.utils import JsonParser
from astrbot_plugin_angel_heart.core.angel_heart_status import AngelHeartStatus


class DummyConfig:
    alias = "AI|助手"
    air_reading_suppress_threshold = -2
    air_reading_ignore_window_messages = 3
    air_reading_suppress_human_to_human = True
    air_reading_suppress_ignored_recently = True
    air_reading_suppress_heated = True
    air_reading_suppress_smalltalk = True
    air_reading_heated_keywords = ["傻逼", "滚", "急了", "破防"]
    air_reading_smalltalk_patterns = ["哈哈", "6", "哦哦", "嗯嗯", "笑死"]


def _msg(role, text, sender_id="u1", directed=False, summon_source=""):
    return {
        "role": role,
        "content": [{"type": "text", "text": text}],
        "sender_id": sender_id,
        "sender_name": sender_id,
        "is_directed_to_bot": directed,
        "summon_source": summon_source,
        "timestamp": 1,
    }


def build_analyzer_stub():
    analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
    analyzer.MAX_TEXT_FIELD_LENGTH = 120
    analyzer.MAX_LIST_ITEMS = 8
    analyzer.MAX_LIST_ITEM_LENGTH = 40
    analyzer.json_parser = JsonParser()
    return analyzer


def test_direct_summon_not_suppressed():
    air = AirReadingAnalyzer(DummyConfig())
    signal = air.analyze(
        "chat",
        historical_context=[],
        recent_dialogue=[_msg("user", "@AI 你怎么看？", "u1", directed=True, summon_source="at_self")],
        current_status=AngelHeartStatus.OBSERVATION,
    )
    assert signal.should_suppress is False
    assert signal.conversation_mode == "directed_to_ai"


def test_human_to_human_smalltalk_suppressed():
    air = AirReadingAnalyzer(DummyConfig())
    signal = air.analyze(
        "chat",
        historical_context=[],
        recent_dialogue=[
            _msg("user", "哈哈", "u1"),
            _msg("user", "笑死", "u2"),
            _msg("user", "@小王 6", "u3"),
        ],
        current_status=AngelHeartStatus.NOT_PRESENT,
    )
    assert signal.should_suppress is True
    assert signal.conversation_mode in {"human_to_human", "small_talk"}


def test_heated_suppressed():
    air = AirReadingAnalyzer(DummyConfig())
    signal = air.analyze(
        "chat",
        historical_context=[],
        recent_dialogue=[_msg("user", "你急了？别骂了", "u1")],
        current_status=AngelHeartStatus.GETTING_FAMILIAR,
    )
    assert signal.should_suppress is True
    assert signal.conversation_mode == "heated"


def test_ignored_recently_suppressed():
    air = AirReadingAnalyzer(DummyConfig())
    signal = air.analyze(
        "chat",
        historical_context=[
            _msg("assistant", "我觉得可以", "ai"),
            _msg("user", "哈哈", "u1"),
            _msg("user", "嗯嗯", "u2"),
            _msg("user", "行吧", "u3"),
        ],
        recent_dialogue=[_msg("user", "继续聊别的", "u4")],
        current_status=AngelHeartStatus.OBSERVATION,
    )
    assert signal.engagement_hint == "ignored_recently"
    assert signal.should_suppress is True


def test_old_json_defaults_compatible():
    analyzer = build_analyzer_stub()
    decision = analyzer._parse_and_validate_decision(
        json.dumps(
            {
                "should_reply": False,
                "reply_strategy": "继续观察",
                "topic": "闲聊",
                "reply_target": "",
                "entities": [],
                "facts": [],
                "keywords": [],
            },
            ensure_ascii=False,
        ),
        "AI",
    )
    assert decision.air_score == 0
    assert decision.should_suppress is False


def test_suppressed_reply_is_forced_back():
    analyzer = build_analyzer_stub()
    signal = AirReadingSignal(
        air_score=-6,
        should_suppress=True,
        suppression_reason="ignored_recently",
        conversation_mode="human_to_human",
        engagement_hint="ignored_recently",
    )
    decision = analyzer._parse_and_validate_decision(
        json.dumps(
            {
                "should_reply": True,
                "is_directly_addressed": False,
                "is_questioned": False,
                "is_interesting": True,
                "reply_strategy": "补充观点",
                "topic": "闲聊",
                "reply_target": "",
                "entities": [],
                "facts": [],
                "keywords": [],
            },
            ensure_ascii=False,
        ),
        "AI",
        air_signal=signal,
    )
    assert decision.should_reply is False
    assert decision.reply_strategy == "ignored_recently"


def test_disable_human_to_human_suppression():
    class ConfigNoHuman(DummyConfig):
        air_reading_suppress_human_to_human = False
        air_reading_suppress_smalltalk = False

    air = AirReadingAnalyzer(ConfigNoHuman())
    signal = air.analyze(
        "chat",
        historical_context=[],
        recent_dialogue=[
            _msg("user", "哈哈", "u1"),
            _msg("user", "笑死", "u2"),
            _msg("user", "@小王 6", "u3"),
        ],
        current_status=AngelHeartStatus.NOT_PRESENT,
    )
    assert signal.should_suppress is False


def test_disable_ignored_recently_suppression():
    class ConfigNoIgnored(DummyConfig):
        air_reading_suppress_ignored_recently = False
        air_reading_suppress_smalltalk = False

    air = AirReadingAnalyzer(ConfigNoIgnored())
    signal = air.analyze(
        "chat",
        historical_context=[
            _msg("assistant", "我觉得可以", "ai"),
            _msg("user", "哈哈", "u1"),
            _msg("user", "嗯嗯", "u2"),
            _msg("user", "行吧", "u3"),
        ],
        recent_dialogue=[_msg("user", "继续聊别的", "u4")],
        current_status=AngelHeartStatus.OBSERVATION,
    )
    assert signal.engagement_hint == "ignored_recently"
    assert signal.should_suppress is False


if __name__ == "__main__":
    tests = [
        test_direct_summon_not_suppressed,
        test_human_to_human_smalltalk_suppressed,
        test_heated_suppressed,
        test_ignored_recently_suppressed,
        test_old_json_defaults_compatible,
        test_suppressed_reply_is_forced_back,
        test_disable_human_to_human_suppression,
        test_disable_ignored_recently_suppression,
    ]
    for test in tests:
        test()
        print(f"PASS: {test.__name__}")
