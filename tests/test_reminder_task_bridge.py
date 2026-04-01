import asyncio
import sys
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_PARENT = ROOT.parent
ASTRBOT_ROOT = Path(r"D:\PycharmProjects\AstrBot\backend\app")

for path in (WORKSPACE_PARENT, ASTRBOT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


if "zoneinfo" not in sys.modules:
    zoneinfo_module = ModuleType("zoneinfo")

    def _fake_zone_info(key):
        return timezone(timedelta(hours=8), name=key)

    zoneinfo_module.ZoneInfo = _fake_zone_info
    sys.modules["zoneinfo"] = zoneinfo_module


if "astrbot" not in sys.modules:
    astrbot_module = ModuleType("astrbot")
    astrbot_api_module = ModuleType("astrbot.api")
    astrbot_api_event_module = ModuleType("astrbot.api.event")
    astrbot_core_module = ModuleType("astrbot.core")
    astrbot_core_message_module = ModuleType("astrbot.core.message")
    astrbot_core_components_module = ModuleType("astrbot.core.message.components")

    class _FakeLogger:
        def debug(self, *args, **kwargs):
            return None

        def info(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def error(self, *args, **kwargs):
            return None

    class _FakeMessageChain:
        def __init__(self, chain=None):
            self.chain = list(chain or [])

    class _FakePlain:
        def __init__(self, text):
            self.text = text

    astrbot_api_module.logger = _FakeLogger()
    astrbot_api_event_module.MessageChain = _FakeMessageChain
    astrbot_core_components_module.Plain = _FakePlain

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = astrbot_api_module
    sys.modules["astrbot.api.event"] = astrbot_api_event_module
    sys.modules["astrbot.core"] = astrbot_core_module
    sys.modules["astrbot.core.message"] = astrbot_core_message_module
    sys.modules["astrbot.core.message.components"] = astrbot_core_components_module


from astrbot_plugin_angel_heart.core.reminder_task_bridge import ReminderTaskBridge


class DummyConfig:
    reminder_future_task_enabled = True


class FakeJob:
    def __init__(self, job_id="job-1"):
        self.job_id = job_id


class FakeCronManager:
    def __init__(self):
        self.calls = []

    async def add_active_job(self, **kwargs):
        self.calls.append(kwargs)
        return FakeJob()


class FakeAstrContext:
    def __init__(self, cron_manager):
        self.cron_manager = cron_manager
        self.sent_messages = []

    async def send_message(self, chat_id, chain):
        texts = []
        for component in getattr(chain, "chain", []) or []:
            text = getattr(component, "text", "")
            if text:
                texts.append(text)
        self.sent_messages.append((chat_id, "".join(texts)))


class FakeLedger:
    def __init__(self):
        self.messages = []
        self.marked = []

    def add_message(self, chat_id, message, should_prune=False):
        self.messages.append((chat_id, message))

    def get_context_snapshot(self, chat_id):
        recent = [
            {
                "role": "user",
                "timestamp": 100.0,
                "content": [{"type": "text", "text": "明天早上8点提醒我开会"}],
            }
        ]
        return [], recent, 100.0

    def mark_as_processed(self, chat_id, boundary_timestamp):
        self.marked.append((chat_id, boundary_timestamp))


class FakeAngelContext:
    def __init__(self, cron_manager):
        self.astr_context = FakeAstrContext(cron_manager)
        self.conversation_ledger = FakeLedger()


class FakeEvent:
    def __init__(self, text, sender_name="LuckyCai"):
        self.unified_msg_origin = "napcat:GroupMessage:925351983"
        self._text = text
        self._sender_name = sender_name
        self.stopped = False

    def get_message_outline(self):
        return self._text

    def get_sender_name(self):
        return self._sender_name

    def get_sender_id(self):
        return "913855876"

    def stop_event(self):
        self.stopped = True


class ReminderTaskBridgeParseTests(unittest.TestCase):
    def setUp(self):
        self.bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))

    def test_relative_minutes(self):
        result = self.bridge.parse("30分钟后提醒我开会", sender_name="LuckyCai")
        self.assertTrue(result.explicit_request)
        self.assertIsNotNone(result.intent)
        self.assertEqual(result.intent.reminder_text, "开会")
        self.assertTrue(result.intent.run_once)

    def test_weekly(self):
        result = self.bridge.parse("每周一早上8点提醒我开组会", sender_name="LuckyCai")
        self.assertEqual(result.intent.cron_expression, "0 8 * * mon")
        self.assertFalse(result.intent.run_once)

    def test_workday(self):
        result = self.bridge.parse("工作日早上9点提醒我打卡", sender_name="LuckyCai")
        self.assertEqual(result.intent.cron_expression, "0 9 * * mon-fri")
        self.assertFalse(result.intent.run_once)

    def test_monthly_last_day(self):
        result = self.bridge.parse("每月最后一天晚上8点提醒我做结算", sender_name="LuckyCai")
        self.assertEqual(result.intent.cron_expression, "0 20 28-31 * *")
        self.assertFalse(result.intent.run_once)

    def test_every_two_days(self):
        result = self.bridge.parse("每隔两天早上9点提醒我浇花", sender_name="LuckyCai")
        self.assertEqual(result.intent.cron_expression, "0 9 */2 * *")
        self.assertFalse(result.intent.run_once)

    def test_chinese_time(self):
        result = self.bridge.parse("明天下午两点二十提醒我开会", sender_name="LuckyCai")
        self.assertEqual(result.intent.due_at.hour, 14)
        self.assertEqual(result.intent.due_at.minute, 20)

    def test_quarter_end_is_one_shot(self):
        result = self.bridge.parse("季度末晚上8点提醒我做汇报", sender_name="LuckyCai")
        self.assertTrue(result.intent.run_once)

    def test_first_workday_is_one_shot(self):
        now = self.bridge._build_datetime(2026, 5, 28, 10, 0)
        result = self.bridge.parse("月初第一个工作日上午9点提醒我交报表", sender_name="LuckyCai", now=now)
        self.assertTrue(result.intent.run_once)
        self.assertLessEqual(result.intent.due_at.day, 7)
        self.assertLessEqual(result.intent.due_at.weekday(), 4)


class ReminderTaskBridgeHandleTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_creates_future_task(self):
        cron_manager = FakeCronManager()
        angel_context = FakeAngelContext(cron_manager)
        bridge = ReminderTaskBridge(DummyConfig(), angel_context)
        event = FakeEvent("明天早上8点提醒我开会")

        handled = await bridge.try_handle(event)

        self.assertTrue(handled)
        self.assertTrue(event.stopped)
        self.assertEqual(len(cron_manager.calls), 1)
        self.assertTrue(cron_manager.calls[0]["run_once"])
        self.assertIn("创建未来任务", angel_context.astr_context.sent_messages[0][1])

    async def test_every_two_days_creates_recurring_task(self):
        cron_manager = FakeCronManager()
        angel_context = FakeAngelContext(cron_manager)
        bridge = ReminderTaskBridge(DummyConfig(), angel_context)
        event = FakeEvent("每隔两天早上9点提醒我浇花")

        handled = await bridge.try_handle(event)

        self.assertTrue(handled)
        self.assertFalse(cron_manager.calls[0]["run_once"])
        self.assertEqual(cron_manager.calls[0]["cron_expression"], "0 9 */2 * *")
        self.assertIn("每隔2天 09:00", angel_context.astr_context.sent_messages[0][1])

    async def test_parse_failure_sends_explicit_feedback(self):
        cron_manager = FakeCronManager()
        angel_context = FakeAngelContext(cron_manager)
        bridge = ReminderTaskBridge(DummyConfig(), angel_context)
        event = FakeEvent("提醒我开会")

        handled = await bridge.try_handle(event)

        self.assertTrue(handled)
        self.assertEqual(len(cron_manager.calls), 0)
        self.assertIn("提醒没创建成功", angel_context.astr_context.sent_messages[0][1])

    async def test_disabled_does_not_take_over(self):
        cron_manager = FakeCronManager()
        angel_context = FakeAngelContext(cron_manager)
        config = DummyConfig()
        config.reminder_future_task_enabled = False
        bridge = ReminderTaskBridge(config, angel_context)
        event = FakeEvent("明天早上8点提醒我开会")

        handled = await bridge.try_handle(event)

        self.assertFalse(handled)
        self.assertFalse(event.stopped)
        self.assertEqual(len(cron_manager.calls), 0)


if __name__ == "__main__":
    unittest.main()

