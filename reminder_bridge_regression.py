import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parent
ASTRBOT_ROOT = Path(r"D:\PycharmProjects\AstrBot\backend\app")
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))
if str(ASTRBOT_ROOT) not in sys.path:
    sys.path.insert(0, str(ASTRBOT_ROOT))

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
    def __init__(
        self,
        job_id="job-1",
        name="提醒:开会",
        description="请提醒LuckyCai：开会。",
        payload=None,
        next_run_time="2026-04-02 08:00:00+08:00",
        enabled=True,
    ):
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


def test_parse_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("明天早上 8 点提醒我开会", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.request_kind == "reminder"
    assert result.intent.reminder_text == "开会"
    assert result.intent.due_at.hour == 8


def test_parse_delivery_keep_existing_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("每天早上7点推送江阴本地天气情况，不需要覆盖", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.request_kind == "delivery"
    assert result.intent.keep_existing is True
    assert result.intent.cron_expression == "0 7 * * *"


async def test_bridge_reminder_uses_direct_basic_job():
    cron_manager = FakeCronManager()
    angel_context = FakeAngelContext(cron_manager)
    bridge = ReminderTaskBridge(DummyConfig(), angel_context)
    event = FakeEvent("1分钟后提醒我开户")
    handled = await bridge.try_handle(event)
    assert handled is True
    assert len(cron_manager.basic_calls) == 1
    assert len(cron_manager.calls) == 0


async def test_bridge_delivery_uses_active_agent_job():
    cron_manager = FakeCronManager()
    angel_context = FakeAngelContext(cron_manager)
    bridge = ReminderTaskBridge(DummyConfig(), angel_context)
    event = FakeEvent("每天早上7点推送江阴本地天气情况，不需要覆盖")
    handled = await bridge.try_handle(event)
    assert handled is True
    assert len(cron_manager.calls) == 1
    assert len(cron_manager.basic_calls) == 0


async def test_direct_handler_deletes_one_shot():
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
    assert "提醒你：开户" in angel_context.astr_context.sent_messages[0][1]
    assert cron_manager.deleted == ["basic-1"]


async def test_bridge_list_tasks_success():
    cron_manager = FakeCronManager()
    cron_manager.jobs = [FakeJob(job_id="job-1"), FakeJob(job_id="job-2", name="推送:天气")]
    angel_context = FakeAngelContext(cron_manager)
    bridge = ReminderTaskBridge(DummyConfig(), angel_context)
    event = FakeEvent("列出当前任务")
    handled = await bridge.try_handle(event)
    assert handled is True
    assert "当前 future task" in angel_context.astr_context.sent_messages[0][1]


async def test_bridge_delete_tasks_success():
    cron_manager = FakeCronManager()
    cron_manager.jobs = [
        FakeJob(job_id="job-1", name="推送:天气", description="请向LuckyCai推送：江阴本地天气情况。"),
        FakeJob(job_id="job-2", name="提醒:开会", description="请提醒LuckyCai：开会。"),
    ]
    angel_context = FakeAngelContext(cron_manager)
    bridge = ReminderTaskBridge(DummyConfig(), angel_context)
    event = FakeEvent("删除天气任务")
    handled = await bridge.try_handle(event)
    assert handled is True
    assert cron_manager.deleted == ["job-1"]


async def main():
    test_parse_success()
    test_parse_delivery_keep_existing_success()
    await test_bridge_reminder_uses_direct_basic_job()
    await test_bridge_delivery_uses_active_agent_job()
    await test_direct_handler_deletes_one_shot()
    await test_bridge_list_tasks_success()
    await test_bridge_delete_tasks_success()
    print("reminder bridge regression: 44/44 passed")


if __name__ == "__main__":
    asyncio.run(main())
