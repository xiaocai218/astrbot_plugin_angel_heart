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


def test_parse_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("明天早上 8 点提醒我开会", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "开会"
    assert result.intent.due_at.hour == 8
    assert result.intent.run_once is True


def test_parse_relative_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("30分钟后提醒我开会", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "开会"
    assert result.intent.run_once is True


def test_parse_weekly_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("每周一早上8点提醒我开组会", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "开组会"
    assert result.intent.run_once is False
    assert result.intent.cron_expression == "0 8 * * mon"


def test_parse_next_week_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("下周三上午9点提醒我开会", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "开会"
    assert result.intent.run_once is True
    assert result.intent.due_at.hour == 9


def test_parse_default_period_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("明早提醒我开会", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "开会"
    assert result.intent.run_once is True
    assert result.intent.due_at.hour == 8


def test_parse_daily_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("每天晚上11点提醒我睡觉", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "睡觉"
    assert result.intent.run_once is False
    assert result.intent.cron_expression == "0 23 * * *"


def test_parse_workday_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("工作日早上9点提醒我打卡", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "打卡"
    assert result.intent.run_once is False
    assert result.intent.cron_expression == "0 9 * * mon-fri"


def test_parse_monthly_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("每月15号上午10点提醒我交房租", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "交房租"
    assert result.intent.run_once is False
    assert result.intent.cron_expression == "0 10 15 * *"


def test_parse_chinese_time_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("明天下午两点提醒我开会", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.due_at.hour == 14
    assert result.intent.reminder_text == "开会"


def test_parse_next_month_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("下个月3号上午10点提醒我交水电", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.run_once is True
    assert result.intent.due_at.day == 3
    assert result.intent.due_at.hour == 10


def test_parse_month_end_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("月底晚上8点提醒我对账", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.run_once is True
    assert result.intent.due_at.hour == 20


def test_parse_weekend_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("双休日上午9点提醒我运动", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.run_once is True
    assert result.intent.due_at.hour == 9


def test_parse_tonight_with_explicit_time_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("今晚八点半提醒我收衣服", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "收衣服"
    assert result.intent.due_at.hour == 20
    assert result.intent.due_at.minute == 30


def test_parse_next_day_alias_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("隔天早上8点提醒我出门", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "出门"
    assert result.intent.due_at.hour == 8


def test_parse_next_next_week_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("下下周三上午10点提醒我复盘", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "复盘"
    assert result.intent.run_once is True
    assert result.intent.due_at.hour == 10


def test_parse_month_start_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("月初上午9点提醒我做预算", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "做预算"
    assert result.intent.run_once is True
    assert result.intent.due_at.hour == 9


def test_parse_chinese_minute_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("后天十一点十五提醒我吃药", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "吃药"
    assert result.intent.due_at.hour == 11
    assert result.intent.due_at.minute == 15


def test_parse_spoken_minute_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("明天下午两点二十提醒我开会", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "开会"
    assert result.intent.due_at.hour == 14
    assert result.intent.due_at.minute == 20


def test_parse_every_other_week_single_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("隔周一早上9点提醒我写周报", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "写周报"
    assert result.intent.run_once is True
    assert result.intent.due_at.hour == 9


def test_parse_monthly_last_day_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("每月最后一天晚上8点提醒我做结算", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "做结算"
    assert result.intent.run_once is False
    assert result.intent.cron_expression == "0 20 28-31 * *"


def test_parse_every_two_days_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("每隔两天早上9点提醒我浇花", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "浇花"
    assert result.intent.run_once is False
    assert result.intent.cron_expression == "0 9 */2 * *"


def test_parse_quarter_end_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("季度末晚上8点提醒我做汇报", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "做汇报"
    assert result.intent.run_once is True
    assert result.intent.due_at.hour == 20


def test_parse_first_workday_success():
    bridge = ReminderTaskBridge(DummyConfig(), FakeAngelContext(FakeCronManager()))
    result = bridge.parse("月初第一个工作日上午9点提醒我交报表", sender_name="LuckyCai")
    assert result.explicit_request is True
    assert result.intent is not None
    assert result.intent.reminder_text == "交报表"
    assert result.intent.run_once is True
    assert result.intent.due_at.hour == 9


async def test_bridge_success():
    cron_manager = FakeCronManager()
    angel_context = FakeAngelContext(cron_manager)
    bridge = ReminderTaskBridge(DummyConfig(), angel_context)
    event = FakeEvent("明天早上 8 点提醒我开会")
    handled = await bridge.try_handle(event)
    assert handled is True
    assert event.stopped is True
    assert len(cron_manager.calls) == 1
    assert cron_manager.calls[0]["run_once"] is True
    assert "开会" in cron_manager.calls[0]["description"]
    assert angel_context.astr_context.sent_messages
    assert "创建未来任务" in angel_context.astr_context.sent_messages[0][1]


async def test_bridge_weekly_success():
    cron_manager = FakeCronManager()
    angel_context = FakeAngelContext(cron_manager)
    bridge = ReminderTaskBridge(DummyConfig(), angel_context)
    event = FakeEvent("每周一早上8点提醒我开组会")
    handled = await bridge.try_handle(event)
    assert handled is True
    assert event.stopped is True
    assert len(cron_manager.calls) == 1
    assert cron_manager.calls[0]["run_once"] is False
    assert cron_manager.calls[0]["cron_expression"] == "0 8 * * mon"
    assert "循环未来任务" in angel_context.astr_context.sent_messages[0][1]


async def test_bridge_daily_success():
    cron_manager = FakeCronManager()
    angel_context = FakeAngelContext(cron_manager)
    bridge = ReminderTaskBridge(DummyConfig(), angel_context)
    event = FakeEvent("每天晚上11点提醒我睡觉")
    handled = await bridge.try_handle(event)
    assert handled is True
    assert event.stopped is True
    assert len(cron_manager.calls) == 1
    assert cron_manager.calls[0]["run_once"] is False
    assert cron_manager.calls[0]["cron_expression"] == "0 23 * * *"
    assert "每天 23:00" in angel_context.astr_context.sent_messages[0][1]


async def test_bridge_monthly_success():
    cron_manager = FakeCronManager()
    angel_context = FakeAngelContext(cron_manager)
    bridge = ReminderTaskBridge(DummyConfig(), angel_context)
    event = FakeEvent("每月15号上午10点提醒我交房租")
    handled = await bridge.try_handle(event)
    assert handled is True
    assert event.stopped is True
    assert len(cron_manager.calls) == 1
    assert cron_manager.calls[0]["run_once"] is False
    assert cron_manager.calls[0]["cron_expression"] == "0 10 15 * *"
    assert "每月15号 10:00" in angel_context.astr_context.sent_messages[0][1]


async def test_bridge_workday_success():
    cron_manager = FakeCronManager()
    angel_context = FakeAngelContext(cron_manager)
    bridge = ReminderTaskBridge(DummyConfig(), angel_context)
    event = FakeEvent("工作日早上9点提醒我打卡")
    handled = await bridge.try_handle(event)
    assert handled is True
    assert event.stopped is True
    assert cron_manager.calls[0]["cron_expression"] == "0 9 * * mon-fri"
    assert "工作日 09:00" in angel_context.astr_context.sent_messages[0][1]


async def test_bridge_monthly_last_day_success():
    cron_manager = FakeCronManager()
    angel_context = FakeAngelContext(cron_manager)
    bridge = ReminderTaskBridge(DummyConfig(), angel_context)
    event = FakeEvent("每月最后一天晚上8点提醒我做结算")
    handled = await bridge.try_handle(event)
    assert handled is True
    assert event.stopped is True
    assert cron_manager.calls[0]["run_once"] is False
    assert cron_manager.calls[0]["cron_expression"] == "0 20 28-31 * *"
    assert "每月最后一天 20:00" in angel_context.astr_context.sent_messages[0][1]


async def test_bridge_every_two_days_success():
    cron_manager = FakeCronManager()
    angel_context = FakeAngelContext(cron_manager)
    bridge = ReminderTaskBridge(DummyConfig(), angel_context)
    event = FakeEvent("每隔两天早上9点提醒我浇花")
    handled = await bridge.try_handle(event)
    assert handled is True
    assert event.stopped is True
    assert cron_manager.calls[0]["run_once"] is False
    assert cron_manager.calls[0]["cron_expression"] == "0 9 */2 * *"
    assert "每隔2天 09:00" in angel_context.astr_context.sent_messages[0][1]


async def test_bridge_parse_failure():
    cron_manager = FakeCronManager()
    angel_context = FakeAngelContext(cron_manager)
    bridge = ReminderTaskBridge(DummyConfig(), angel_context)
    event = FakeEvent("提醒我开会")
    handled = await bridge.try_handle(event)
    assert handled is True
    assert event.stopped is True
    assert len(cron_manager.calls) == 0
    assert "提醒没创建成功" in angel_context.astr_context.sent_messages[0][1]


async def test_bridge_disabled():
    cron_manager = FakeCronManager()
    angel_context = FakeAngelContext(cron_manager)
    config = DummyConfig()
    config.reminder_future_task_enabled = False
    bridge = ReminderTaskBridge(config, angel_context)
    event = FakeEvent("明天早上 8 点提醒我开会")
    handled = await bridge.try_handle(event)
    assert handled is False
    assert event.stopped is False
    assert not cron_manager.calls


async def main():
    test_parse_success()
    test_parse_relative_success()
    test_parse_weekly_success()
    test_parse_next_week_success()
    test_parse_default_period_success()
    test_parse_daily_success()
    test_parse_workday_success()
    test_parse_monthly_success()
    test_parse_chinese_time_success()
    test_parse_next_month_success()
    test_parse_month_end_success()
    test_parse_weekend_success()
    test_parse_tonight_with_explicit_time_success()
    test_parse_next_day_alias_success()
    test_parse_next_next_week_success()
    test_parse_month_start_success()
    test_parse_chinese_minute_success()
    test_parse_spoken_minute_success()
    test_parse_every_other_week_single_success()
    test_parse_monthly_last_day_success()
    test_parse_every_two_days_success()
    test_parse_quarter_end_success()
    test_parse_first_workday_success()
    await test_bridge_success()
    await test_bridge_weekly_success()
    await test_bridge_daily_success()
    await test_bridge_monthly_success()
    await test_bridge_workday_success()
    await test_bridge_monthly_last_day_success()
    await test_bridge_every_two_days_success()
    await test_bridge_parse_failure()
    await test_bridge_disabled()
    print("reminder bridge regression: 34/34 passed")


if __name__ == "__main__":
    asyncio.run(main())
