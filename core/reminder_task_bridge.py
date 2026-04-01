"""
AngelHeart 插件 - 提醒桥接器

将“明确提醒请求”直接桥接到 AstrBot 原生 future task，
避免主模型口头答应但没有真正创建未来任务。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

try:
    from astrbot.api import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from astrbot.api.event import MessageChain
from astrbot.core.message.components import Plain


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

DAY_PATTERN = re.compile(r"(今天|明天|后天|隔天)")
WEEKDAY_PATTERN = re.compile(r"(隔周|下下周|下周|每周)(一|二|三|四|五|六|日|天)")
RELATIVE_PATTERN = re.compile(r"(\d{1,3})\s*(分钟|小时)后")
RELATIVE_CN_PATTERN = re.compile(r"(半小时|一小时|两小时|两分钟|一分钟)后")
EVERY_N_DAYS_PATTERN = re.compile(r"每隔\s*(\d{1,2}|一|二|两|三|四|五|六|七)\s*天")
DEFAULT_PERIOD_PATTERN = re.compile(r"(今早|今晚|明早|明晚)")
DAILY_PATTERN = re.compile(r"(每天|工作日)")
MONTHLY_PATTERN = re.compile(r"每月\s*(\d{1,2})\s*号")
MONTHLY_LAST_DAY_PATTERN = re.compile(r"每月最后一天")
NEXT_MONTH_PATTERN = re.compile(r"下个月\s*(\d{1,2})\s*号")
MONTH_END_PATTERN = re.compile(r"月底")
MONTH_START_PATTERN = re.compile(r"月初")
FIRST_WORKDAY_OF_MONTH_PATTERN = re.compile(r"月初第一个工作日")
QUARTER_END_PATTERN = re.compile(r"季度末")
WEEKEND_PATTERN = re.compile(r"(双休日|周末)")
TIME_PATTERN = re.compile(
    r"(?:(凌晨|早上|早晨|上午|中午|下午|傍晚|晚上)\s*)?"
    r"(\d{1,2})"
    r"(?:\s*(?:[:：点时])\s*(\d{1,2}))?"
    r"\s*(?:分)?"
)
CJK_TIME_PATTERN = re.compile(
    r"(?:(凌晨|早上|早晨|上午|中午|下午|傍晚|晚上)\s*)?"
    r"(零|一|二|两|三|四|五|六|七|八|九|十|十一|十二)"
    r"\s*(?:点|时)"
    r"\s*(半|零五|零十|十五|二十|二十五|三十|三十五|四十|四十五|五十|五十五|一十|一十五)?"
    r"\s*(?:分)?"
)
LEADING_TIME_PATTERN = re.compile(
    r"^\s*(?:(?:今天|明天|后天|隔天)|(?:下周|下下周|每周)[一二三四五六日天]|每天|工作日|每月\s*\d{1,2}\s*号|下个月\s*\d{1,2}\s*号|月底|月初|今早|今晚|明早|明晚)?\s*"
    r"(?:(?:凌晨|早上|早晨|上午|中午|下午|傍晚|晚上)\s*)?"
    r"(?:半小时后|一小时后|两小时后|两分钟后|一分钟后|\d{1,2}\s*(?:分钟|小时)后|\d{1,2}(?:\s*(?:[:：点时])\s*\d{1,2})?\s*(?:分)?)?\s*"
)
EXPLICIT_REMINDER_MARKERS = (
    "提醒我",
    "记得提醒我",
    "到时候提醒我",
    "到点提醒我",
)
ONE_SHOT_DUE_AT_PARSERS = (
    "_parse_relative_due_at",
    "_parse_every_n_days_due_at",
    "_parse_weekday_due_at",
    "_parse_default_period_due_at",
    "_parse_weekend_due_at",
    "_parse_next_month_due_at",
    "_parse_month_end_due_at",
    "_parse_monthly_last_day_due_at",
    "_parse_quarter_end_due_at",
    "_parse_first_workday_of_month_due_at",
    "_parse_month_start_due_at",
)
WEEKDAY_CRON_MAP = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class ReminderIntent:
    due_at: datetime
    reminder_text: str
    task_name: str
    note: str
    cron_expression: str | None = None
    run_once: bool = True


@dataclass
class ReminderParseResult:
    intent: ReminderIntent | None = None
    explicit_request: bool = False
    error_message: str = ""


class ReminderTaskBridge:
    """将显式提醒语句桥接到 AstrBot future task。"""

    def __init__(self, config_manager, angel_context):
        self.config_manager = config_manager
        self.angel_context = angel_context

    def parse(self, text: str, sender_name: str = "", now: datetime | None = None) -> ReminderParseResult:
        raw_text = str(text or "").strip()
        if not raw_text:
            return ReminderParseResult()

        marker = self._find_explicit_marker(raw_text)
        if not marker:
            return ReminderParseResult()

        now_dt = now or datetime.now(SHANGHAI_TZ)
        due_at = self._parse_due_at(raw_text, now_dt)
        if due_at is None:
            return ReminderParseResult(
                explicit_request=True,
                error_message="没看懂提醒时间，暂时只支持今天/明天/后天 + 具体时刻。",
            )

        reminder_text = self._extract_reminder_text(raw_text, marker)
        if not reminder_text:
            reminder_text = "查看待办事项"

        if due_at <= now_dt:
            return ReminderParseResult(
                explicit_request=True,
                error_message="提醒时间已经过去，没法创建未来任务。",
            )

        return ReminderParseResult(
            explicit_request=True,
            intent=self._build_intent(raw_text, sender_name, due_at, reminder_text),
        )

    async def try_handle(self, event: Any) -> bool:
        """尝试直接桥接提醒请求。成功或明确失败都返回 True 并终止后续链路。"""
        if not self.config_manager.reminder_future_task_enabled:
            return False

        chat_id = event.unified_msg_origin
        outline = event.get_message_outline()
        sender_name = str(event.get_sender_name() or "").strip()
        parse_result = self.parse(outline, sender_name=sender_name)

        if not parse_result.explicit_request:
            return False

        if not parse_result.intent:
            logger.info(
                "AngelHeart[%s]: 提醒桥接解析失败。消息: %s | 原因: %s",
                chat_id,
                outline,
                parse_result.error_message,
            )
            await self._send_feedback(
                chat_id,
                f"提醒没创建成功：{parse_result.error_message}",
            )
            self._mark_latest_user_message_processed(chat_id)
            event.stop_event()
            return True

        logger.info(
            "AngelHeart[%s]: 提醒桥接命中。时间: %s | 内容: %s",
            chat_id,
            parse_result.intent.due_at.isoformat(),
            parse_result.intent.reminder_text,
        )

        try:
            job = await self._create_future_task(event, parse_result.intent)
        except Exception as exc:
            logger.error(
                "AngelHeart[%s]: 提醒桥接创建失败: %s",
                chat_id,
                exc,
                exc_info=True,
            )
            await self._send_feedback(chat_id, f"提醒没创建成功：{exc}")
            self._mark_latest_user_message_processed(chat_id)
            event.stop_event()
            return True

        logger.info(
            "AngelHeart[%s]: 提醒桥接创建成功。job_id=%s | next_run=%s",
            chat_id,
            getattr(job, "job_id", "unknown"),
            parse_result.intent.due_at.isoformat(),
        )
        await self._send_feedback(
            chat_id,
            self._build_confirmation(parse_result.intent),
        )
        self._mark_latest_user_message_processed(chat_id)
        event.stop_event()
        return True

    def _find_explicit_marker(self, text: str) -> str:
        for marker in EXPLICIT_REMINDER_MARKERS:
            if marker in text:
                return marker
        return ""

    def _parse_due_at(self, text: str, now: datetime) -> datetime | None:
        for parser_name in ONE_SHOT_DUE_AT_PARSERS:
            due_at = getattr(self, parser_name)(text, now)
            if due_at is not None:
                return due_at

        day_match = DAY_PATTERN.search(text)
        normalized_time = self._extract_normalized_time(text)
        if not normalized_time:
            return None

        day_offset = 0
        if day_match:
            day_word = day_match.group(1)
            day_offset = {"今天": 0, "明天": 1, "后天": 2, "隔天": 1}.get(day_word, 0)

        target_day = (now + timedelta(days=day_offset)).date()
        due_at = self._build_datetime(target_day.year, target_day.month, target_day.day, *normalized_time)

        if not day_match and due_at <= now:
            due_at += timedelta(days=1)

        return due_at

    def _parse_relative_due_at(self, text: str, now: datetime) -> datetime | None:
        match = RELATIVE_PATTERN.search(text)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            if amount <= 0:
                return None
            if unit == "分钟":
                return now + timedelta(minutes=amount)
            if unit == "小时":
                return now + timedelta(hours=amount)
            return None

        cn_match = RELATIVE_CN_PATTERN.search(text)
        if not cn_match:
            return None

        raw = cn_match.group(1)
        mapping = {
            "半小时": timedelta(minutes=30),
            "一小时": timedelta(hours=1),
            "两小时": timedelta(hours=2),
            "一分钟": timedelta(minutes=1),
            "两分钟": timedelta(minutes=2),
        }
        delta = mapping.get(raw)
        return now + delta if delta else None

    def _parse_every_n_days_due_at(self, text: str, now: datetime) -> datetime | None:
        match = EVERY_N_DAYS_PATTERN.search(text)
        if not match:
            return None
        normalized_time = self._extract_normalized_time(text)
        if not normalized_time:
            return None
        hour, minute = normalized_time
        due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due_at <= now:
            due_at = due_at + timedelta(days=1)
        return due_at

    def _parse_interval_days(self, raw_value: str) -> int | None:
        raw_value = str(raw_value or "").strip()
        if raw_value.isdigit():
            return int(raw_value)
        mapping = {
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
        }
        return mapping.get(raw_value)

    def _parse_weekday_due_at(self, text: str, now: datetime) -> datetime | None:
        weekday_match = WEEKDAY_PATTERN.search(text)
        if not weekday_match:
            return None

        normalized_time = self._extract_normalized_time(text)
        if not normalized_time:
            return None

        week_prefix = weekday_match.group(1)
        weekday_text = weekday_match.group(2)
        target_weekday = self._weekday_to_int(weekday_text)
        if target_weekday is None:
            return None

        hour, minute = normalized_time

        current_weekday = now.weekday()
        day_delta = (target_weekday - current_weekday) % 7

        if week_prefix == "下周":
            day_delta += 7
        elif week_prefix == "下下周":
            day_delta += 14
        elif week_prefix == "隔周":
            day_delta += 14
        elif week_prefix == "每周" and day_delta == 0:
            candidate_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate_today <= now:
                day_delta = 7

        target_day = (now + timedelta(days=day_delta)).date()
        return self._build_datetime(target_day.year, target_day.month, target_day.day, hour, minute)

    def _parse_weekend_due_at(self, text: str, now: datetime) -> datetime | None:
        if not WEEKEND_PATTERN.search(text):
            return None
        normalized_time = self._extract_normalized_time(text)
        if not normalized_time:
            return None
        hour, minute = normalized_time

        target_weekday = 5 if now.weekday() <= 5 else 6
        day_delta = (target_weekday - now.weekday()) % 7
        candidate = now + timedelta(days=day_delta)
        due_at = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due_at <= now:
            if target_weekday == 5 and now.weekday() == 5:
                due_at = due_at + timedelta(days=1)
            elif target_weekday == 6 and now.weekday() == 6:
                due_at = due_at + timedelta(days=6)
            else:
                due_at = due_at + timedelta(days=7)
        return due_at

    def _parse_next_month_due_at(self, text: str, now: datetime) -> datetime | None:
        match = NEXT_MONTH_PATTERN.search(text)
        if not match:
            return None
        normalized_time = self._extract_normalized_time(text)
        if not normalized_time:
            return None
        hour, minute = normalized_time
        day = int(match.group(1))
        year, month = self._shift_month(now.year, now.month, 1)
        return self._build_day_of_month_due_at(year, month, day, hour, minute)

    def _parse_month_end_due_at(self, text: str, now: datetime) -> datetime | None:
        if not MONTH_END_PATTERN.search(text):
            return None
        normalized_time = self._extract_normalized_time(text)
        if not normalized_time:
            return None
        hour, minute = normalized_time
        due_at = self._build_day_of_month_due_at(
            now.year,
            now.month,
            self._last_day_of_month(now.year, now.month),
            hour,
            minute,
        )
        if due_at <= now:
            year, month = self._shift_month(now.year, now.month, 1)
            due_at = self._build_day_of_month_due_at(
                year,
                month,
                self._last_day_of_month(year, month),
                hour,
                minute,
            )
        return due_at

    def _parse_month_start_due_at(self, text: str, now: datetime) -> datetime | None:
        if not MONTH_START_PATTERN.search(text):
            return None
        normalized_time = self._extract_normalized_time(text)
        if not normalized_time:
            return None
        hour, minute = normalized_time
        due_at = self._build_datetime(now.year, now.month, 1, hour, minute)
        if due_at <= now:
            year, month = self._shift_month(now.year, now.month, 1)
            due_at = self._build_datetime(year, month, 1, hour, minute)
        return due_at

    def _parse_monthly_last_day_due_at(self, text: str, now: datetime) -> datetime | None:
        if not MONTHLY_LAST_DAY_PATTERN.search(text):
            return None
        normalized_time = self._extract_normalized_time(text)
        if not normalized_time:
            return None
        hour, minute = normalized_time
        due_at = self._build_day_of_month_due_at(
            now.year,
            now.month,
            self._last_day_of_month(now.year, now.month),
            hour,
            minute,
        )
        if due_at <= now:
            year, month = self._shift_month(now.year, now.month, 1)
            due_at = self._build_day_of_month_due_at(
                year,
                month,
                self._last_day_of_month(year, month),
                hour,
                minute,
            )
        return due_at

    def _parse_quarter_end_due_at(self, text: str, now: datetime) -> datetime | None:
        if not QUARTER_END_PATTERN.search(text):
            return None
        normalized_time = self._extract_normalized_time(text)
        if not normalized_time:
            return None
        hour, minute = normalized_time

        quarter_end_months = (3, 6, 9, 12)
        year = now.year
        for month in quarter_end_months:
            if month < now.month:
                continue
            due_at = self._build_day_of_month_due_at(
                year,
                month,
                self._last_day_of_month(year, month),
                hour,
                minute,
            )
            if due_at > now:
                return due_at

        year += 1
        month = 3
        return self._build_day_of_month_due_at(year, month, self._last_day_of_month(year, month), hour, minute)

    def _parse_first_workday_of_month_due_at(self, text: str, now: datetime) -> datetime | None:
        if not FIRST_WORKDAY_OF_MONTH_PATTERN.search(text):
            return None
        normalized_time = self._extract_normalized_time(text)
        if not normalized_time:
            return None
        hour, minute = normalized_time

        def build_first_workday(year: int, month: int) -> datetime:
            day = 1
            while True:
                candidate = self._build_datetime(year, month, day, hour, minute)
                if candidate.weekday() <= 4:
                    return candidate
                day += 1

        due_at = build_first_workday(now.year, now.month)
        if due_at <= now:
            year, month = self._shift_month(now.year, now.month, 1)
            due_at = build_first_workday(year, month)
        return due_at

    def _parse_default_period_due_at(self, text: str, now: datetime) -> datetime | None:
        match = DEFAULT_PERIOD_PATTERN.search(text)
        if not match:
            return None

        keyword = match.group(1)
        explicit_time = self._extract_time_parts(text)
        defaults = {
            "今早": (0, 8, 0),
            "今晚": (0, 20, 0),
            "明早": (1, 8, 0),
            "明晚": (1, 20, 0),
        }
        day_offset, default_hour, default_minute = defaults[keyword]
        if explicit_time:
            fallback_period = "晚上" if "晚" in keyword else "早上"
            normalized_time = self._normalize_time_parts(explicit_time, fallback_period=fallback_period)
            if not normalized_time:
                return None
            hour, minute = normalized_time
        else:
            hour, minute = default_hour, default_minute
        target_day = (now + timedelta(days=day_offset)).date()
        due_at = self._build_datetime(target_day.year, target_day.month, target_day.day, hour, minute)
        if day_offset == 0 and due_at <= now:
            due_at += timedelta(days=1)
        return due_at

    def _weekday_to_int(self, text: str) -> int | None:
        mapping = {
            "一": 0,
            "二": 1,
            "三": 2,
            "四": 3,
            "五": 4,
            "六": 5,
            "日": 6,
            "天": 6,
        }
        return mapping.get(text)

    def _extract_time_parts(self, text: str) -> tuple[str, int, int] | None:
        numeric_matches = list(TIME_PATTERN.finditer(text))
        cjk_matches = list(CJK_TIME_PATTERN.finditer(text))
        candidates = []

        for match in numeric_matches:
            candidates.append((match.start(), (match.group(1) or "", int(match.group(2)), int(match.group(3) or 0))))

        for match in cjk_matches:
            hour = self._parse_cjk_hour(match.group(2))
            minute = self._parse_cjk_minute(match.group(3) or "")
            if hour is None or minute is None:
                continue
            candidates.append((match.start(), (match.group(1) or "", hour, minute)))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[-1][1]

    def _extract_normalized_time(
        self,
        text: str,
        fallback_period: str = "",
    ) -> tuple[int, int] | None:
        return self._normalize_time_parts(self._extract_time_parts(text), fallback_period=fallback_period)

    def _normalize_time_parts(
        self,
        time_parts: tuple[str, int, int] | None,
        fallback_period: str = "",
    ) -> tuple[int, int] | None:
        if not time_parts:
            return None
        period, hour, minute = time_parts
        hour = self._normalize_hour(period or fallback_period, hour)
        if hour is None or minute > 59:
            return None
        return hour, minute

    def _parse_cjk_hour(self, value: str) -> int | None:
        mapping = {
            "零": 0,
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
            "十一": 11,
            "十二": 12,
        }
        return mapping.get(value)

    def _parse_cjk_minute(self, value: str) -> int | None:
        if not value:
            return 0
        mapping = {
            "半": 30,
            "零五": 5,
            "零十": 10,
            "十五": 15,
            "二十": 20,
            "二十五": 25,
            "三十": 30,
            "三十五": 35,
            "四十": 40,
            "四十五": 45,
            "五十": 50,
            "五十五": 55,
        }
        return mapping.get(value)

    def _last_day_of_month(self, year: int, month: int) -> int:
        if month == 12:
            next_month = self._build_datetime(year + 1, 1, 1, 0, 0)
        else:
            next_month = self._build_datetime(year, month + 1, 1, 0, 0)
        return (next_month - timedelta(days=1)).day

    def _shift_month(self, year: int, month: int, offset: int) -> tuple[int, int]:
        month_index = (year * 12 + month - 1) + offset
        return divmod(month_index, 12)[0], divmod(month_index, 12)[1] + 1

    def _build_datetime(self, year: int, month: int, day: int, hour: int, minute: int) -> datetime:
        return datetime(year, month, day, hour, minute, tzinfo=SHANGHAI_TZ)

    def _build_day_of_month_due_at(self, year: int, month: int, day: int, hour: int, minute: int) -> datetime:
        target_day = min(day, self._last_day_of_month(year, month))
        return self._build_datetime(year, month, target_day, hour, minute)

    def _normalize_hour(self, period: str, hour: int) -> int | None:
        if hour > 23:
            return None

        if period in {"凌晨"}:
            if hour == 12:
                return 0
            return hour if hour <= 11 else None

        if period in {"早上", "早晨", "上午"}:
            if hour == 12:
                return 0
            return hour if hour <= 11 else None

        if period == "中午":
            if hour == 12:
                return 12
            if 1 <= hour <= 11:
                return hour + 12
            return None

        if period in {"下午", "傍晚", "晚上"}:
            if hour == 12:
                return 12
            if 1 <= hour <= 11:
                return hour + 12
            return None

        return hour

    def _extract_reminder_text(self, text: str, marker: str) -> str:
        marker_index = text.rfind(marker)
        if marker_index >= 0:
            candidate = text[marker_index + len(marker):]
        else:
            candidate = text

        candidate = LEADING_TIME_PATTERN.sub("", candidate, count=1)
        candidate = candidate.strip(" ，。,.!！?？:：")

        if not candidate:
            stripped = text
            stripped = stripped.replace(marker, "", 1)
            stripped = DAY_PATTERN.sub("", stripped, count=1)
            stripped = TIME_PATTERN.sub("", stripped, count=1)
            candidate = stripped.strip(" ，。,.!！?？:：")

        return candidate[:80]

    def _build_intent(self, raw_text: str, sender_name: str, due_at: datetime, reminder_text: str) -> ReminderIntent:
        task_name = f"提醒:{reminder_text[:18]}"
        cron_expression = None
        run_once = True
        every_n_days_match = EVERY_N_DAYS_PATTERN.search(raw_text)
        daily_match = DAILY_PATTERN.search(raw_text)
        monthly_match = MONTHLY_PATTERN.search(raw_text)
        monthly_last_day_match = MONTHLY_LAST_DAY_PATTERN.search(raw_text)
        weekly_match = "每周" in raw_text

        if weekly_match:
            cron_expression = f"{due_at.minute} {due_at.hour} * * {WEEKDAY_CRON_MAP[due_at.weekday()]}"
            run_once = False
        elif FIRST_WORKDAY_OF_MONTH_PATTERN.search(raw_text):
            cron_expression = None
            run_once = True
        elif QUARTER_END_PATTERN.search(raw_text):
            cron_expression = None
            run_once = True
        elif every_n_days_match:
            interval = self._parse_interval_days(every_n_days_match.group(1))
            if interval is None:
                interval = 1
            interval = max(1, min(interval, 28))
            cron_expression = f"{due_at.minute} {due_at.hour} */{interval} * *"
            run_once = False
        elif daily_match:
            if "工作日" in raw_text:
                cron_expression = f"{due_at.minute} {due_at.hour} * * mon-fri"
            else:
                cron_expression = f"{due_at.minute} {due_at.hour} * * *"
            run_once = False
        else:
            if monthly_last_day_match:
                cron_expression = f"{due_at.minute} {due_at.hour} 28-31 * *"
                run_once = False
            else:
                if monthly_match:
                    day_of_month = int(monthly_match.group(1))
                    cron_expression = f"{due_at.minute} {due_at.hour} {day_of_month} * *"
                    run_once = False

        if sender_name:
            note = (
                f"请提醒{sender_name}：{reminder_text}。"
                "直接提醒核心事项，不要说系统已创建任务。"
            )
        else:
            note = (
                f"请提醒用户：{reminder_text}。"
                "直接提醒核心事项，不要说系统已创建任务。"
            )

        return ReminderIntent(
            due_at=due_at,
            reminder_text=reminder_text,
            task_name=task_name,
            note=note,
            cron_expression=cron_expression,
            run_once=run_once,
        )

    async def _create_future_task(self, event: Any, intent: ReminderIntent) -> Any:
        cron_manager = getattr(self.angel_context.astr_context, "cron_manager", None)
        if cron_manager is None:
            raise RuntimeError("AstrBot cron manager 不可用")

        payload = {
            "session": event.unified_msg_origin,
            "sender_id": event.get_sender_id(),
            "note": intent.note,
            "origin": "tool",
        }

        return await cron_manager.add_active_job(
            name=intent.task_name,
            cron_expression=intent.cron_expression,
            payload=payload,
            description=intent.note,
            timezone="Asia/Shanghai",
            run_once=intent.run_once,
            run_at=intent.due_at if intent.run_once else None,
        )

    async def _send_feedback(self, chat_id: str, text: str):
        chain = MessageChain([Plain(text)])
        await self.angel_context.astr_context.send_message(chat_id, chain)
        self.angel_context.conversation_ledger.add_message(
            chat_id,
            {
                "role": "assistant",
                "content": text,
                "sender_id": "assistant",
                "sender_name": "assistant",
                "timestamp": time.time(),
                "is_processed": True,
            },
        )

    def _mark_latest_user_message_processed(self, chat_id: str):
        _, recent_dialogue, boundary_ts = self.angel_context.conversation_ledger.get_context_snapshot(chat_id)
        if boundary_ts > 0:
            self.angel_context.conversation_ledger.mark_as_processed(chat_id, boundary_ts)
            return

        if not recent_dialogue:
            return

        fallback_ts = max(
            message.get("timestamp", 0) for message in recent_dialogue if message.get("role") == "user"
        )
        if fallback_ts > 0:
            self.angel_context.conversation_ledger.mark_as_processed(chat_id, fallback_ts)

    def _build_confirmation(self, intent: ReminderIntent) -> str:
        time_text = intent.due_at.strftime("%Y-%m-%d %H:%M")
        if intent.run_once:
            return f"好的，已经为你创建未来任务：{time_text} 提醒你{intent.reminder_text}。"
        recurring_text = self._describe_recurring_schedule(intent)
        return f"好的，已经为你创建循环未来任务：{recurring_text} 提醒你{intent.reminder_text}。"

    def _weekday_to_cn(self, weekday: int) -> str:
        mapping = ["一", "二", "三", "四", "五", "六", "日"]
        return mapping[weekday]

    def _describe_recurring_schedule(self, intent: ReminderIntent) -> str:
        cron_expression = intent.cron_expression or ""
        if cron_expression.endswith(" mon-fri"):
            return f"工作日 {intent.due_at.strftime('%H:%M')}"
        if "28-31" in cron_expression:
            return f"每月最后一天 {intent.due_at.strftime('%H:%M')}"
        if "*/" in cron_expression:
            parts = cron_expression.split()
            if len(parts) == 5 and parts[2].startswith("*/"):
                return f"每隔{parts[2][2:]}天 {int(parts[1]):02d}:{int(parts[0]):02d}"

        parts = cron_expression.split()
        if len(parts) == 5:
            minute, hour, day_of_month, _, weekday = parts
            if day_of_month != "*" and weekday == "*":
                return f"每月{int(day_of_month)}号 {int(hour):02d}:{int(minute):02d}"
            if day_of_month == "*" and weekday == "*":
                return f"每天 {int(hour):02d}:{int(minute):02d}"
            if weekday in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
                weekday_idx = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(weekday)
                return f"每周{self._weekday_to_cn(weekday_idx)} {int(hour):02d}:{int(minute):02d}"

        return intent.due_at.strftime("%Y-%m-%d %H:%M")
