import asyncio
from typing import List, Dict
import json
import string
import re
from dataclasses import dataclass

try:
    from astrbot.api import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
from ..core.utils import JsonParser, format_message_for_llm
from ..models.analysis_result import SecretaryDecision
from .prompt_module_loader import PromptModuleLoader
from .air_reading import AirReadingSignal


class SafeFormatter(string.Formatter):
    """
    安全的字符串格式化器，当占位符不存在时返回空字符串或指定的默认值
    """

    def __init__(self, default_value: str = ""):
        """
        初始化安全格式化器

        Args:
            default_value (str): 当占位符不存在时返回的默认值
        """
        self.default_value = default_value

    def get_value(self, key, args, kwargs):
        """
        获取占位符的值

        Args:
            key: 占位符的键
            args: 位置参数
            kwargs: 关键字参数

        Returns:
            占位符的值，如果不存在则返回默认值
        """
        if isinstance(key, str):
            try:
                return kwargs[key]
            except KeyError:
                return self.default_value
        else:
            return string.Formatter.get_value(key, args, kwargs)


@dataclass
class AnalyzerModelCandidate:
    """分析模型候选配置。"""

    model_name: str
    is_reasoning_model: bool
    role_label: str


class LLMAnalyzer:
    """
    LLM分析器 - 执行实时分析和标注
    采用两级AI协作体系：
    1. 轻量级AI（分析员）：低成本、快速地判断是否需要回复。
    2. 重量级AI（专家）：在需要时，生成高质量的回复。
    """

    # 类级别的常量
    MAX_CONVERSATION_LENGTH = 50
    MAX_TEXT_FIELD_LENGTH = 120
    MAX_LIST_ITEMS = 8
    MAX_LIST_ITEM_LENGTH = 40
    DEFAULT_AIR_READING_PROMPT = (
        "- air_score: 0\n"
        "- should_suppress: false\n"
        "- suppression_reason: none\n"
        "- conversation_mode: general_discussion\n"
        "- engagement_hint: unknown\n"
    )

    def __init__(
        self,
        analyzer_model_name: str,
        context,
        strategy_guide: str = None,
        config_manager=None,
    ):
        self.analyzer_model_name = analyzer_model_name
        self.context = context  # 存储 context 对象，用于动态获取 provider
        self.strategy_guide = strategy_guide or ""  # 存储策略指导文本
        self.config_manager = config_manager  # 存储 config_manager 对象，用于访问配置
        self.is_ready = False  # 默认认为分析器未就绪
        self._prompt_template_cache: Dict[bool, str] = {}

        # 初始化提示词模块加载器
        self.prompt_loader = PromptModuleLoader()

        # 初始化JSON解析器
        self.json_parser = JsonParser()

        # 加载外部 Prompt 模板
        try:
            # 使用 PromptModuleLoader 构建提示词模板
            is_reasoning_model = config_manager.is_reasoning_model if config_manager else False
            self.base_prompt_template = self.prompt_loader.build_prompt_template(is_reasoning_model)
            self._prompt_template_cache[is_reasoning_model] = self.base_prompt_template

            if self.base_prompt_template:
                self.is_ready = True
                output_type = "指令" if is_reasoning_model else "推理"
                logger.info(f"AngelHeart分析器: Prompt模块组装成功，使用 {output_type} 版本。")
            else:
                self.is_ready = False
                logger.critical("AngelHeart分析器: Prompt模块组装失败，未生成有效模板。分析器将无法工作。")
        except Exception as e:
            self.is_ready = False
            logger.critical(f"AngelHeart分析器: Prompt模块组装时发生错误: {e}。分析器将无法工作。")

        if not self.analyzer_model_name:
            logger.warning("AngelHeart的分析模型未配置，功能将受限。")

    def reload_config(self, new_config_manager):
        """重新加载配置"""
        self.config_manager = new_config_manager

        # 重新加载提示词模块
        try:
            self.prompt_loader.reload_modules()
            is_reasoning_model = new_config_manager.is_reasoning_model if new_config_manager else False
            self.base_prompt_template = self.prompt_loader.build_prompt_template(is_reasoning_model)
            self._prompt_template_cache = {is_reasoning_model: self.base_prompt_template}

            if self.base_prompt_template:
                self.is_ready = True
                output_type = "指令" if is_reasoning_model else "推理"
                logger.info(f"AngelHeart分析器: Prompt模板重新加载成功，使用 {output_type} 版本。")
            else:
                self.is_ready = False
                logger.warning("AngelHeart分析器: Prompt模板重新加载失败，分析器未就绪。")
        except Exception as e:
            self.is_ready = False
            logger.error(f"AngelHeart分析器: Prompt模板重新加载时发生错误: {e}")

    def _get_prompt_template(self, is_reasoning_model: bool) -> str:
        """按模型类型获取提示词模板，并做简单缓存。"""
        cached = self._prompt_template_cache.get(is_reasoning_model)
        if cached:
            return cached

        template = self.prompt_loader.build_prompt_template(is_reasoning_model)
        self._prompt_template_cache[is_reasoning_model] = template
        return template

    async def _call_ai_model(self, prompt: str, chat_id: str, model_name: str) -> str:
        """
        调用AI模型并返回响应文本，包含3秒后自动重试1次机制
        """
        # 3. 如果启用了提示词日志增强，则记录最终构建的完整提示词
        if False:  # prompt_logging_enabled 已废弃
            logger.info(
                f"[AngelHeart][{chat_id}]:最终构建的完整提示词 ----------------"
            )
            logger.info(prompt)
            logger.info("----------------------------------------")

        # 动态获取 provider
        provider = self.context.get_provider_by_id(model_name)
        if not provider:
            logger.warning(
                f"AngelHeart分析器: 未找到名为 '{model_name}' 的分析模型提供商。"
            )
            raise Exception("未找到分析模型提供商")

        # 重试机制：最多重试1次，间隔3秒
        max_retries = 1
        retry_delay = 3  # 秒

        for attempt in range(max_retries + 1):
            try:
                token = await provider.text_chat(prompt=prompt)
                response_text = token.completion_text.strip()

                # 记录AI模型的完整响应内容
                logger.debug(
                    f"[AngelHeart][{chat_id}]: 轻量模型的分析推理 ----------------"
                )
                logger.debug(response_text)
                logger.debug("----------------------------------------")

                return response_text

            except Exception as e:
                if attempt < max_retries:
                    logger.warning(
                        f"AngelHeart分析器: 第{attempt + 1}次调用AI模型失败，{retry_delay}秒后重试: {e}"
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(
                        f"💥 AngelHeart分析器: 调用AI模型失败(model={model_name})，已重试{max_retries}次: {e}",
                        exc_info=True,
                    )
                    raise

    def _build_prompt(
        self,
        historical_context: List[Dict],
        recent_dialogue: List[Dict],
        air_signal: AirReadingSignal | None = None,
        is_reasoning_model: bool | None = None,
    ) -> str:
        """
        使用给定的对话历史构建分析提示词

        Args:
            conversations (List[Dict]): 对话历史

        Returns:
            str: 构建好的提示词
        """
        # 分别格式化历史上下文和最近对话，并添加 XML 包裹
        historical_body = self._format_conversation_history(historical_context)
        recent_body = self._format_conversation_history(recent_dialogue)

        historical_text = f"<已回应消息>\n{historical_body}\n</已回应消息>" if historical_body else " "
        recent_text = f"<未回应消息>\n{recent_body}\n</未回应消息>" if recent_body else " "
        air_reading_text = (
            air_signal.to_prompt_block() if air_signal else self.DEFAULT_AIR_READING_PROMPT
        )

        # 增强检查：如果历史文本为空，则记录警告日志
        if not historical_text and not recent_text:
            logger.warning(
                "AngelHeart分析器: 格式化后的对话历史为空，将生成一个空的分析提示词。"
            )

        # 获取配置中的昵称
        alias = self.config_manager.alias if self.config_manager else "AngelHeart"

        # 使用直接的字符串替换来构建提示词，规避.format()方法对特殊字符的解析问题
        if is_reasoning_model is None:
            is_reasoning_model = self.config_manager.is_reasoning_model if self.config_manager else False

        base_prompt = self._get_prompt_template(is_reasoning_model)
        base_prompt = base_prompt.replace("{historical_context}", historical_text)
        base_prompt = base_prompt.replace("{recent_dialogue}", recent_text)
        base_prompt = base_prompt.replace("{reply_strategy_guide}", self.strategy_guide)
        base_prompt = base_prompt.replace("{alias}", alias)
        base_prompt = base_prompt.replace("{air_reading_signal}", air_reading_text)
        base_prompt = base_prompt.replace(
            "{ai_self_identity}",
            self.config_manager.ai_self_identity if self.config_manager else "",
        )

        return base_prompt

    def _build_model_candidates(self) -> List[AnalyzerModelCandidate]:
        """构建主秘书/副秘书候选列表。"""
        candidates: List[AnalyzerModelCandidate] = []

        if self.analyzer_model_name:
            candidates.append(
                AnalyzerModelCandidate(
                    model_name=self.analyzer_model_name,
                    is_reasoning_model=self.config_manager.is_reasoning_model if self.config_manager else False,
                    role_label="主秘书",
                )
            )

        deputy_model = self.config_manager.deputy_analyzer_model if self.config_manager else ""
        if deputy_model and deputy_model != self.analyzer_model_name:
            candidates.append(
                AnalyzerModelCandidate(
                    model_name=deputy_model,
                    is_reasoning_model=self.config_manager.deputy_is_reasoning_model if self.config_manager else False,
                    role_label="副秘书",
                )
            )

        return candidates

    def _should_try_next_candidate(self, error: Exception) -> bool:
        """仅在基础设施故障时回退到副秘书。"""
        if isinstance(error, asyncio.TimeoutError):
            return True

        message = str(error).lower()
        failure_markers = (
            "429",
            "rate limit",
            "too many requests",
            "resource_exhausted",
            "quota exceeded",
            "quota",
            "timeout",
            "timed out",
            "unavailable",
            "overload",
            "overloaded",
            "connection",
            "network",
            "refused",
            "reset",
            "not found",
            "未找到分析模型提供商",
            "不可用",
            "超时",
            "限流",
            "限速",
            "速率限制",
        )
        return any(marker in message for marker in failure_markers)

    async def analyze_and_decide(
        self,
        historical_context: List[Dict],
        recent_dialogue: List[Dict],
        chat_id: str,
        air_signal: AirReadingSignal | None = None,
    ) -> SecretaryDecision:
        """
        分析对话历史，做出结构化的决策 (JSON)
        """
        # 获取昵称
        alias = self.config_manager.alias if self.config_manager else "AngelHeart"

        if not self.analyzer_model_name:
            logger.debug("AngelHeart分析器: 分析模型未配置, 跳过分析。")
            # 返回一个默认的不参与决策
            return SecretaryDecision(
                should_reply=False, reply_strategy="未配置", topic="未知",
                entities=[], facts=[], keywords=[]
            )

        if not self.is_ready:
            logger.debug("AngelHeart分析器: 由于核心Prompt模板丢失，分析器已禁用。")
            return SecretaryDecision(
                should_reply=False,
                reply_strategy="分析器未就绪",
                topic="未知",
                entities=[], facts=[], keywords=[]
            )

        model_candidates = self._build_model_candidates()
        if not model_candidates:
            logger.debug("AngelHeart分析器: 主秘书和副秘书模型均未配置。")
            return SecretaryDecision(
                should_reply=False, reply_strategy="未配置", topic="未知",
                entities=[], facts=[], keywords=[]
            )

        last_error: Exception | None = None
        for index, candidate in enumerate(model_candidates):
            logger.debug(
                f"AngelHeart分析器: 准备调用{candidate.role_label}模型 '{candidate.model_name}' 进行分析..."
            )
            prompt = self._build_prompt(
                historical_context,
                recent_dialogue,
                air_signal=air_signal,
                is_reasoning_model=candidate.is_reasoning_model,
            )

            if not prompt:
                logger.warning(
                    f"AngelHeart分析器: 为{candidate.role_label}生成的分析提示词为空，将跳过该模型。"
                )
                continue

            response_text = ""
            try:
                response_text = await self._call_ai_model(prompt, chat_id, candidate.model_name)
                return self._parse_response(response_text, alias, air_signal=air_signal)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(
                    f"AngelHeart分析器: {candidate.role_label}返回的JSON格式或内容有误: {e}. 原始响应: {response_text[:200]}..."
                )
                last_error = e
                break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last_error = e
                has_next_candidate = index < len(model_candidates) - 1
                if has_next_candidate and self._should_try_next_candidate(e):
                    next_candidate = model_candidates[index + 1]
                    logger.warning(
                        f"AngelHeart分析器: {candidate.role_label}模型 '{candidate.model_name}' 调用失败 ({e})，切换到{next_candidate.role_label}模型 '{next_candidate.model_name}'。"
                    )
                    continue

                logger.error(
                    f"💥 AngelHeart分析器: {candidate.role_label}分析失败: {e}",
                    exc_info=True,
                )
                break

        # 如果发生任何错误，都返回一个默认的不参与决策
        if last_error:
            logger.warning(f"AngelHeart分析器: 主秘书/副秘书链路最终失败，回退为不回复。错误: {last_error}")
        return SecretaryDecision(
            should_reply=False, reply_strategy="分析失败", topic="未知",
            entities=[], facts=[], keywords=[]
        )

    def _parse_response(
        self,
        response_text: str,
        alias: str,
        air_signal: AirReadingSignal | None = None,
    ) -> SecretaryDecision:
        """
        解析AI模型的响应文本并返回SecretaryDecision对象

        Args:
            response_text (str): AI模型的响应文本
            alias (str): AI的昵称
            air_signal (AirReadingSignal | None): 本地读空气信号

        Returns:
            SecretaryDecision: 解析后的决策对象
        """
        return self._parse_and_validate_decision(response_text, alias, air_signal=air_signal)

    def _parse_and_validate_decision(
        self, response_text: str, alias: str, air_signal: AirReadingSignal | None = None
    ) -> SecretaryDecision:
        """解析并验证来自AI的响应文本，构建SecretaryDecision对象"""

        # 定义SecretaryDecision的字段要求
        required_fields = ["should_reply", "reply_strategy", "topic", "reply_target", "entities", "facts", "keywords"]
        optional_fields = [
            "is_directly_addressed",
            "is_questioned",
            "is_interesting",
            "air_score",
            "should_suppress",
            "suppression_reason",
            "conversation_mode",
            "engagement_hint",
        ]

        # 使用JsonParser提取JSON数据
        try:
            decision_data = self.json_parser.extract_json(
                text=response_text,
                required_fields=required_fields,
                optional_fields=optional_fields,
            )
        except Exception as e:
            logger.warning(
                f"AngelHeart分析器: JsonParser提取JSON时发生异常: {e}. 原始响应: {response_text[:200]}..."
            )
            decision_data = None

        # 如果JsonParser未能提取到有效的JSON
        if decision_data is None:
            logger.warning(
                f"AngelHeart分析器: JsonParser无法从响应中提取有效的JSON。原始响应: {response_text[:200]}..."
            )
            # 返回一个默认的不参与决策
            return SecretaryDecision(
                should_reply=False,
                reply_strategy="分析内容无有效JSON",
                topic="未知",
                entities=[], facts=[], keywords=[]
            )

        # 对来自 AI 的 JSON 做健壮性处理，防止字段为 null 或类型不符合导致 pydantic 校验失败
        raw = decision_data
        should_reply = self._normalize_bool(raw.get("should_reply", False))
        is_directly_addressed = self._normalize_bool(raw.get("is_directly_addressed", False))
        is_questioned = self._normalize_bool(raw.get("is_questioned", False))
        is_interesting = self._normalize_bool(raw.get("is_interesting", False))
        air_score = self._normalize_int(raw.get("air_score", 0), 0, -10, 10)
        should_suppress = self._normalize_bool(raw.get("should_suppress", False))
        suppression_reason = self._normalize_text_field(raw.get("suppression_reason"), "")
        conversation_mode = self._normalize_enum_text(
            raw.get("conversation_mode"),
            {"directed_to_ai", "human_to_human", "heated", "small_talk", "general_discussion"},
            "general_discussion",
        )
        engagement_hint = self._normalize_enum_text(
            raw.get("engagement_hint"),
            {"unknown", "ignored_recently", "welcomed_recently"},
            "unknown",
        )

        reply_strategy = self._normalize_text_field(raw.get("reply_strategy"), "未知策略")
        topic = self._normalize_text_field(raw.get("topic"), "未知话题")
        reply_target = self._normalize_text_field(raw.get("reply_target"), "")

        entities = self._normalize_string_list(raw.get("entities", []))
        facts = self._normalize_string_list(raw.get("facts", []))
        keywords = self._normalize_string_list(raw.get("keywords", []))

        # 创建决策对象
        decision = SecretaryDecision(
            should_reply=should_reply,
            is_directly_addressed=is_directly_addressed,
            is_questioned=is_questioned,
            is_interesting=is_interesting,
            air_score=air_score,
            should_suppress=should_suppress,
            suppression_reason=suppression_reason,
            conversation_mode=conversation_mode,
            engagement_hint=engagement_hint,
            reply_strategy=reply_strategy,
            topic=topic,
            reply_target=reply_target,
            entities=entities,
            facts=facts,
            keywords=keywords,
        )

        if air_signal:
            decision.air_score = air_signal.air_score
            decision.should_suppress = air_signal.should_suppress
            decision.suppression_reason = air_signal.suppression_reason
            decision.conversation_mode = air_signal.conversation_mode
            decision.engagement_hint = air_signal.engagement_hint

        # 代码校验和修正逻辑
        if (
            decision.should_reply
            and not decision.is_directly_addressed
            and not decision.is_questioned
            and not decision.is_interesting
        ):
            logger.warning(
                "AngelHeart分析器: AI判断有矛盾 - should_reply=true 但没有触发原因，强制设为不回复"
            )
            decision.should_reply = False
            decision.reply_strategy = "继续观察"

        if (
            decision.should_reply
            and decision.should_suppress
            and not decision.is_directly_addressed
            and not decision.is_questioned
        ):
            logger.info(
                f"AngelHeart分析器: 读空气压制，拦截秘书参与。"
                f"score={decision.air_score} mode={decision.conversation_mode} "
                f"reason={decision.suppression_reason or 'continue_observing'}"
            )
            decision.should_reply = False
            decision.reply_strategy = decision.suppression_reason or "继续观察"

        return decision

    def _normalize_int(self, value: object, default: int, min_value: int, max_value: int) -> int:
        """规范化整数并限制范围。"""
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return default
        return max(min_value, min(max_value, normalized))

    def _normalize_enum_text(self, value: object, allowed: set[str], default: str) -> str:
        """规范化枚举样式文本字段。"""
        normalized = self._normalize_text_field(value, default)
        return normalized if normalized in allowed else default

    def _normalize_bool(self, value: object) -> bool:
        """仅接受明确的布尔字面量，避免数值型脏数据误入。"""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in ("true", "yes", "是", "对"):
                return True
            if normalized in ("false", "no", "否", "不", ""):
                return False
        return False

    def _normalize_text_field(self, value: object, default: str) -> str:
        """规范化文本字段，去控制字符并限制长度。"""
        if value is None:
            return default

        text = str(value).strip()
        if not text:
            return default

        text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > self.MAX_TEXT_FIELD_LENGTH:
            text = text[: self.MAX_TEXT_FIELD_LENGTH].rstrip()
        return text or default

    def _normalize_string_list(self, value: object) -> List[str]:
        """仅保留字符串项，并限制条数与单项长度。"""
        if not isinstance(value, list):
            if isinstance(value, str) and value.strip():
                value = [value]
            else:
                return []

        normalized_items: List[str] = []
        for item in value:
            if not isinstance(item, str):
                continue

            cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", item)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if not cleaned:
                continue

            if len(cleaned) > self.MAX_LIST_ITEM_LENGTH:
                cleaned = cleaned[: self.MAX_LIST_ITEM_LENGTH].rstrip()

            normalized_items.append(cleaned)
            if len(normalized_items) >= self.MAX_LIST_ITEMS:
                break

        return normalized_items

    def _format_conversation_history(self, conversations: List[Dict]) -> str:
        """
        格式化对话历史，生成统一的日志式格式。

        Args:
            conversations (List[Dict]): 包含对话历史的字典列表。

        Returns:
            str: 格式化后的对话历史字符串。
        """
        # Phase 3: 增加空数据保护机制 - 开始
        # 防止空数据导致崩溃的保护机制
        if not conversations:
            return ""
        # Phase 3: 增加空数据保护机制 - 结束

        lines = []
        # 定义历史与新消息的分隔符对象
        SEPARATOR_OBJ = {"role": "system", "content": "history_separator"}

        # 遍历最近的 MAX_CONVERSATION_LENGTH 条对话
        for conv in conversations[-self.MAX_CONVERSATION_LENGTH :]:
            # 确保 conv 是一个字典
            if not isinstance(conv, dict):
                logger.warning(f"跳过非字典类型的对话项: {type(conv)}")
                continue

            # 检查是否遇到分隔符
            if conv == SEPARATOR_OBJ:
                lines.append("\n--- 以上是历史消息，仅作为策略参考，不需要回应 ---\n")
                lines.append(
                    "\n--- 后续的最新对话，你需要分辨出里面的人是不是在对你说话 ---\n"
                )
                continue  # 跳过分隔符本身，不添加到最终输出

            # 使用公共的工具函数格式化消息，确保使用统一的 XML 格式
            alias = self.config_manager.alias if self.config_manager else "AngelHeart"
            formatted_message = format_message_for_llm(conv, alias)
            lines.append(formatted_message)

        # 将所有格式化后的行连接成一个字符串并返回
        return "\n".join(lines)
