import unittest

from tests import _test_bootstrap  # noqa: F401

from astrbot_plugin_angel_heart.core.air_reading import AirReadingSignal
from astrbot_plugin_angel_heart.roles.secretary import Secretary


class ObservationBypassTests(unittest.TestCase):
    def setUp(self):
        self.secretary = Secretary.__new__(Secretary)

    def test_observation_direct_followup_bypasses_threshold(self):
        historical_context = [
            {
                "role": "assistant",
                "timestamp": 100.0,
                "content": "阿泡这操作放在影之诗2里就是张0费0/1白板",
            }
        ]
        recent_dialogue = [
            {
                "role": "user",
                "timestamp": 120.0,
                "content": [{"type": "text", "text": "他还要去南京参加线下赛事呢"}],
            }
        ]
        air_signal = AirReadingSignal(conversation_mode="directed_to_ai")

        self.assertTrue(
            self.secretary._should_bypass_observation_threshold(
                historical_context,
                recent_dialogue,
                air_signal,
            )
        )

    def test_non_direct_followup_keeps_threshold(self):
        historical_context = [
            {
                "role": "assistant",
                "timestamp": 100.0,
                "content": "这卡挺离谱",
            }
        ]
        recent_dialogue = [
            {
                "role": "user",
                "timestamp": 260.0,
                "content": [{"type": "text", "text": "哈哈"}],
            }
        ]
        air_signal = AirReadingSignal(conversation_mode="small_talk")

        self.assertFalse(
            self.secretary._should_bypass_observation_threshold(
                historical_context,
                recent_dialogue,
                air_signal,
            )
        )


if __name__ == "__main__":
    unittest.main()
