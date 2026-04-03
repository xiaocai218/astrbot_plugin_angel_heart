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

    class _FakeAstrMessageEvent:
        pass

    class _FakePlain:
        def __init__(self, text):
            self.text = text

    class _FakeAt:
        def __init__(self, qq):
            self.qq = qq
            self.text = f"@{qq}"

    astrbot_api_module.logger = _FakeLogger()
    astrbot_api_event_module.MessageChain = _FakeMessageChain
    astrbot_api_event_module.AstrMessageEvent = _FakeAstrMessageEvent
    astrbot_core_components_module.Plain = _FakePlain
    astrbot_core_components_module.At = _FakeAt

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = astrbot_api_module
    sys.modules["astrbot.api.event"] = astrbot_api_event_module
    sys.modules["astrbot.core"] = astrbot_core_module
    sys.modules["astrbot.core.message"] = astrbot_core_message_module
    sys.modules["astrbot.core.message.components"] = astrbot_core_components_module


from astrbot_plugin_angel_heart.core.reminder_task_bridge import ReminderTaskBridge


class DummyScheduler:
    def __init__(self):
        self.jobs = {}

    def get_job(self, job_id):
        return self.jobs.get(job_id)


class DummyConfig:
    reminder_future_task_enabled = True
    reminder_direct_delivery_enabled = True


class FakeJob:
    def __init__(self, job_id="job-1", name="提醒:开会", description="请提醒LuckyCai：开会。", payload=None, next_run_time="2026-04-02 08:00:00+08:00", enabled=True):
        self.job_id = job_id
        self.name = name
        self.description = description
        self.payload = payload or {"session": "napcat:GroupMessage:925351983", "note": description}
        self.next_run_time = next_run_time
        self.enabled = enabled


class FakeCronManager:
    def __init__(self):
        self.calls = []
        self.basic_calls = []
        self.updated = []
        self.deleted = []
        self.jobs = []
        self._basic_handlers = {}
        self.scheduler = DummyScheduler()

    async def add_active_job(self, **kwargs):
        self.calls.append(kwargs)
        return FakeJob(
            job_id=f"active-{len(self.calls)}",
            name=kwargs.get("name", "job"),
            description=kwargs.get("description", ""),
            payload=kwargs.get("payload", {}),
            next_run_time=kwargs.get("run_at") or "2026-04-02 08:00:00+08:00",
        )

    async def add_basic_job(self, **kwargs):
        self.basic_calls.append(kwargs)
        job = FakeJob(
            job_id=f"basic-{len(self.basic_calls)}",
            name=kwargs.get("name", "job"),
            description=kwargs.get("description", ""),
            payload=kwargs.get("payload", {}),
        )
        self.jobs.append(job)
        return job

    async def update_job(self, job_id, **kwargs):
        self.updated.append((job_id, kwargs))
        for job in self.jobs:
            if job.job_id == job_id and "payload" in kwargs:
                job.payload = kwargs["payload"]
        return next((job for job in self.jobs if job.job_id == job_id), None)

    async def list_jobs(self, job_type=None):
        return list(self.jobs)

    async def delete_job(self, job_id):
        self.deleted.append(job_id)
        self.jobs = [job for job in self.jobs if job.job_id != job_id]

    def _schedule_job(self, job):
        self.scheduler.jobs[job.job_id] = job


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

    def test_delivery_task_with_keep_existing(self):
        result = self.bridge.parse("每天早上7点推送江阴本地天气情况，不需要覆盖", sender_name="LuckyCai")
        self.assertTrue(result.explicit_request)
        self.assertIsNotNone(result.intent)
        self.assertEqual(result.intent.request_kind, "delivery")
        self.assertEqual(result.intent.action_label, "推送")
        self.assertTrue(result.intent.keep_existing)
        self.assertEqual(result.intent.reminder_text, "江阴本地天气情况")
        self.assertEqual(result.intent.cron_expression, "0 7 * * *")


class ReminderTaskBridgeHandleTests(unittest.IsolatedAsyncioTestCase):
    async def test_reminder_creates_direct_basic_job(self):
        cron_manager = FakeCronManager()
        angel_context = FakeAngelContext(cron_manager)
        bridge = ReminderTaskBridge(DummyConfig(), angel_context)
        event = FakeEvent("明天早上8点提醒我开会")

        handled = await bridge.try_handle(event)

        self.assertTrue(handled)
        self.assertTrue(event.stopped)
        self.assertEqual(len(cron_manager.basic_calls), 1)
        self.assertEqual(len(cron_manager.calls), 0)
        self.assertIn("创建未来任务", angel_context.astr_context.sent_messages[0][1])

    async def test_recurring_reminder_creates_direct_basic_job(self):
        cron_manager = FakeCronManager()
        angel_context = FakeAngelContext(cron_manager)
        bridge = ReminderTaskBridge(DummyConfig(), angel_context)
        event = FakeEvent("每隔两天早上9点提醒我浇花")

        handled = await bridge.try_handle(event)

        self.assertTrue(handled)
        self.assertEqual(cron_manager.basic_calls[0]["cron_expression"], "0 9 */2 * *")
        self.assertEqual(len(cron_manager.calls), 0)
        self.assertIn("每隔2天 09:00", angel_context.astr_context.sent_messages[0][1])

    async def test_delivery_task_keeps_agent_track(self):
        cron_manager = FakeCronManager()
        angel_context = FakeAngelContext(cron_manager)
        bridge = ReminderTaskBridge(DummyConfig(), angel_context)
        event = FakeEvent("每天早上7点推送江阴本地天气情况，不需要覆盖")

        handled = await bridge.try_handle(event)

        self.assertTrue(handled)
        self.assertEqual(len(cron_manager.calls), 1)
        self.assertEqual(len(cron_manager.basic_calls), 0)
        self.assertEqual(cron_manager.calls[0]["cron_expression"], "0 7 * * *")
        self.assertIn("不会覆盖旧任务", angel_context.astr_context.sent_messages[0][1])

    async def test_direct_handler_sends_message_and_deletes_one_shot(self):
        cron_manager = FakeCronManager()
        angel_context = FakeAngelContext(cron_manager)
        bridge = ReminderTaskBridge(DummyConfig(), angel_context)
        handler = bridge._build_direct_reminder_handler()

        await handler(
            chat_id="napcat:GroupMessage:925351983",
            sender_id="913855876",
            reminder_text="开户",
            run_once_direct=True,
            job_id="basic-1",
        )

        self.assertIn("提醒你：开户", angel_context.astr_context.sent_messages[0][1])
        self.assertEqual(cron_manager.deleted, ["basic-1"])

    async def test_list_tasks(self):
        cron_manager = FakeCronManager()
        cron_manager.jobs = [
            FakeJob(job_id="job-1", name="提醒:开会"),
            FakeJob(job_id="job-2", name="推送:天气"),
        ]
        angel_context = FakeAngelContext(cron_manager)
        bridge = ReminderTaskBridge(DummyConfig(), angel_context)
        event = FakeEvent("列出当前任务")

        handled = await bridge.try_handle(event)

        self.assertTrue(handled)
        self.assertIn("当前 future task", angel_context.astr_context.sent_messages[0][1])
        self.assertIn("job-1", angel_context.astr_context.sent_messages[0][1])

    async def test_delete_tasks_by_keyword(self):
        cron_manager = FakeCronManager()
        cron_manager.jobs = [
            FakeJob(job_id="job-1", name="推送:天气", description="请向LuckyCai推送：江阴本地天气情况。"),
            FakeJob(job_id="job-2", name="提醒:开会", description="请提醒LuckyCai：开会。"),
        ]
        angel_context = FakeAngelContext(cron_manager)
        bridge = ReminderTaskBridge(DummyConfig(), angel_context)
        event = FakeEvent("删除天气任务")

        handled = await bridge.try_handle(event)

        self.assertTrue(handled)
        self.assertEqual(cron_manager.deleted, ["job-1"])
        self.assertIn("已删除 1 个包含“天气”的 future task", angel_context.astr_context.sent_messages[0][1])


if __name__ == "__main__":
    unittest.main()
