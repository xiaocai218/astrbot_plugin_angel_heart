"""
AngelHeart 插件 - 配置管理器
用于集中管理插件的所有配置项。
"""


class ConfigManager:
    """
    配置管理器 - 提供对插件配置的中心化访问
    """

    def __init__(self, config_data: dict):
        """
        初始化配置管理器。

        Args:
            config_data (dict): 原始配置字典。
        """
        self._config = config_data or {}

    @property
    def waiting_time(self) -> float:
        """等待时间（秒）- 冷却时间间隔"""
        return self._config.get("waiting_time", 7.0)

    @property
    def llm_timeout(self) -> float:
        """LLM 处理超时时间（秒）- 会话处理卡死检测阈值"""
        return self._config.get("llm_timeout", 180.0)

    @property
    def no_reply_cooldown(self) -> float:
        """不回复时的冷却时间（秒）"""
        return self._config.get("no_reply_cooldown", 3.0)

    @property
    def cache_expiry(self) -> int:
        """缓存过期时间（秒）"""
        return self._config.get("cache_expiry", 3600)

    @property
    def analyzer_model(self) -> str:
        """用于分析的LLM模型名称"""
        return self._config.get("analyzer_model", "")

    @property
    def deputy_analyzer_model(self) -> str:
        """副秘书模型名称，用于主秘书故障时回退"""
        return self._config.get("deputy_analyzer_model", "")

    @property
    def reply_strategy_guide(self) -> str:
        """回复策略指导文本"""
        return self._config.get("reply_strategy_guide", "")

    @property
    def whitelist_enabled(self) -> bool:
        """是否启用白名单"""
        return self._config.get("whitelist_enabled", False)

    @property
    def chat_ids(self) -> list:
        """白名单聊天ID列表"""
        return self._config.get("chat_ids", [])

    @property
    def debug_mode(self) -> bool:
        """调试模式开关"""
        return self._config.get("debug_mode", False)

    @property
    def strip_markdown_enabled(self) -> bool:
        """是否启用Markdown清洗"""
        return self._config.get("strip_markdown_enabled", True)

    @property
    def alias(self) -> str:
        """AI助手的昵称"""
        return self._config.get("alias", "AngelHeart")

    @property
    def analysis_on_mention_only(self) -> bool:
        """是否仅在被呼唤时才进行分析"""
        return self._config.get("analysis_on_mention_only", False)

    @property
    def force_reply_when_summoned(self) -> bool:
        """被呼唤时是否强制回复"""
        return self._config.get("force_reply_when_summoned", True)

    @property
    def slap_words(self) -> str:
        """用于触发闭嘴的关键词，多个词用'|'分隔"""
        return self._config.get("slap_words", "")

    @property
    def silence_duration(self) -> int:
        """触发闭嘴后的静默时长（秒）"""
        return self._config.get("silence_duration", 600)

    @property
    def group_chat_enhancement(self) -> bool:
        """是否启用群聊上下文增强模式"""
        return self._config.get("group_chat_enhancement", True)

    @property
    def is_reasoning_model(self) -> bool:
        """是否是思维模型（如果是，则直接输出json）"""
        return self._config.get("is_reasoning_model", False)

    @property
    def deputy_is_reasoning_model(self) -> bool:
        """副秘书是否是思维模型；默认跟随主秘书配置"""
        return self._config.get("deputy_is_reasoning_model", self.is_reasoning_model)

    @property
    def ai_self_identity(self) -> str:
        """AI的自我身份定位"""
        return self._config.get(
            "ai_self_identity",
            "你拥有强大的检索能力和庞大的知识储备和记忆能力。\n你喜爱跟群友进行语言游戏沟通。\n群友对AI的善意测试你必须回应满足群友的期待，展示你的能力。",
        )

    @property
    def patience_interval(self) -> int:
        """久等间隔（秒）"""
        return self._config.get("patience_interval", 10)

    @property
    def comfort_words(self) -> str:
        """安心词列表，多个词用'|'分隔"""
        return self._config.get("comfort_words", "嗯嗯|我在|别急")

    @property
    def patience_enabled(self) -> bool:
        """是否启用安抚机制。"""
        return self._config.get("patience_enabled", True)

    @property
    def reminder_future_task_enabled(self) -> bool:
        """是否启用提醒语句到 AstrBot 未来任务的桥接。"""
        return self._config.get("reminder_future_task_enabled", True)

    @property
    def reminder_direct_delivery_enabled(self) -> bool:
        """是否让提醒类任务走确定性直发轨道。"""
        return self._config.get("reminder_direct_delivery_enabled", True)

    # ========== 4状态机制新增配置 ==========

    @property
    def echo_detection_threshold(self) -> int:
        """
        复读检测阈值：连续多少条相同消息触发混脸熟

        Returns:
            int: 阈值，默认3条
        """
        return self._config.get("echo_detection_threshold", 3)

    @property
    def dense_conversation_threshold(self) -> int:
        """
        密集发言阈值：10分钟内多少条消息触发混脸熟

        Returns:
            int: 阈值，默认30条
        """
        return self._config.get("dense_conversation_threshold", 30)

    @property
    def familiarity_timeout(self) -> int:
        """
        混脸熟超时时间：多长时间无活动自动降级（秒）

        Returns:
            int: 超时时间，默认600秒（10分钟）
        """
        return self._config.get("familiarity_timeout", 600)

    @property
    def familiarity_cooldown_duration(self) -> int:
        """
        混脸熟冷却时间：混脸熟状态结束后多久才能再次触发（秒）

        Returns:
            int: 冷却时间，默认1800秒（30分钟）
        """
        return self._config.get("familiarity_cooldown_duration", 1800)

    @property
    def observation_timeout(self) -> int:
        """
        观测中超时时间：多长时间无活动自动降级（秒）

        Returns:
            int: 超时时间，默认600秒（10分钟）
        """
        return self._config.get("observation_timeout", 600)

    @property
    def observation_min_messages(self) -> int:
        """
        观测状态下重新触发分析所需的最少未处理用户消息数

        Returns:
            int: 最少消息数，默认2条
        """
        return max(1, int(self._config.get("observation_min_messages", 2)))

    @property
    def observation_followup_score_threshold(self) -> int:
        """明显续聊 AI 时触发强放行的分数阈值。"""
        return int(self._config.get("observation_followup_score_threshold", 4))

    @property
    def observation_followup_time_window(self) -> int:
        """AI 回复后多长时间内的续聊视为高概率在接 AI。"""
        return max(30, int(self._config.get("observation_followup_time_window", 120)))

    @property
    def observation_followup_short_phrases(self) -> list[str]:
        """明显在接 AI 的短句承接词。"""
        raw = self._config.get(
            "observation_followup_short_phrases",
            "确实|也是|那倒是|有道理|难说|还真是|对啊|对的|是啊|没错",
        )
        return [item.strip() for item in str(raw).split("|") if item.strip()]

    @property
    def observation_followup_question_phrases(self) -> list[str]:
        """明显在继续追问 AI 的词表。"""
        raw = self._config.get(
            "observation_followup_question_phrases",
            "那后面呢|所以你的意思是|那现在咋办|那怎么办|那我这套|那怎么改|你觉得呢|继续说|展开讲讲",
        )
        return [item.strip() for item in str(raw).split("|") if item.strip()]

    @property
    def observation_followup_feedback_phrases(self) -> list[str]:
        """明显在回应 AI 的反馈型词表。"""
        raw = self._config.get(
            "observation_followup_feedback_phrases",
            "你这说得对|我就是这个意思|那你继续说|你继续|你展开讲讲|你说得对|是这个意思",
        )
        return [item.strip() for item in str(raw).split("|") if item.strip()]

    @property
    def echo_detection_window(self) -> int:
        """
        复读检测时间窗口：多长时间内的消息算作复读（秒）

        Returns:
            int: 时间窗口，默认30秒
        """
        return self._config.get("echo_detection_window", 30)

    @property
    def dense_conversation_window(self) -> int:
        """
        密集发言检测时间窗口：多长时间内的消息算作密集（秒）

        Returns:
            int: 时间窗口，默认600秒（10分钟）
        """
        return self._config.get("dense_conversation_window", 600)

    @property
    def min_participant_count(self) -> int:
        """
        密集发言最小参与人数：至少多少不同的人参与才算密集

        Returns:
            int: 最小参与人数，默认5人
        """
        return self._config.get("min_participant_count", 5)

    @property
    def leave_echo_reply(self) -> bool:
        """
        离场应答-复读模式开关

        Returns:
            bool: 是否启用离场时复读应答，默认False
        """
        return self._config.get("leave_echo_reply", False)

    @property
    def leave_dense_reply(self) -> bool:
        """
        离场应答-密集对话参与开关

        Returns:
            bool: 是否启用离场时参与密集对话应答，默认False
        """
        return self._config.get("leave_dense_reply", False)

    @property
    def max_conversation_tokens(self) -> int:
        """当单个会话的估算Token数超过此限制时，触发清理。0为禁用。"""
        return self._config.get("max_conversation_tokens", 100000)

    @property
    def tool_decoration_enabled(self) -> bool:
        """是否启用工具修饰"""
        return self._config.get("tool_decoration_enabled", False)

    @property
    def tool_decoration_cooldown(self) -> float:
        """工具修饰冷却时间（秒）"""
        return self._config.get("tool_decoration_cooldown", 7.0)

    @property
    def air_reading_enabled(self) -> bool:
        """是否启用读空气预筛。"""
        return self._config.get("air_reading_enabled", True)

    @property
    def air_reading_suppress_threshold(self) -> int:
        """读空气压制阈值，分数低于等于该值时优先压制。"""
        return int(self._config.get("air_reading_suppress_threshold", -2))

    @property
    def air_reading_ignore_window_messages(self) -> int:
        """AI 被连续无视多少条用户消息后视为近期被无视。"""
        return max(1, int(self._config.get("air_reading_ignore_window_messages", 3)))

    @property
    def air_reading_suppress_human_to_human(self) -> bool:
        """是否压制明显的人类互聊场景。"""
        return self._config.get("air_reading_suppress_human_to_human", True)

    @property
    def air_reading_suppress_ignored_recently(self) -> bool:
        """是否压制近期被无视后继续主动介入。"""
        return self._config.get("air_reading_suppress_ignored_recently", True)

    @property
    def air_reading_suppress_heated(self) -> bool:
        """是否压制火药味/争执场景。"""
        return self._config.get("air_reading_suppress_heated", True)

    @property
    def air_reading_suppress_smalltalk(self) -> bool:
        """是否压制低信息量寒暄/接梗场景。"""
        return self._config.get("air_reading_suppress_smalltalk", True)

    @property
    def air_reading_heated_keywords(self) -> list[str]:
        """火药味关键词列表。"""
        raw = self._config.get(
            "air_reading_heated_keywords",
            "傻逼|滚|闭嘴|有病|脑残|吵|骂|喷|急了|破防",
        )
        return [item.strip() for item in str(raw).split("|") if item.strip()]

    @property
    def air_reading_smalltalk_patterns(self) -> list[str]:
        """低信息量寒暄/接梗关键词列表。"""
        raw = self._config.get(
            "air_reading_smalltalk_patterns",
            "哈哈|呵呵|牛|6|草|行吧|确实|笑死|晚安|早|早安|哦哦|嗯嗯",
        )
        return [item.strip() for item in str(raw).split("|") if item.strip()]

    @property
    def tool_decorations(self) -> dict:
        """工具修饰语配置字典"""
        import json

        decorations = self._config.get("tool_decorations", "{}")

        # 如果已经是字典，直接返回
        if isinstance(decorations, dict):
            return decorations

        # 如果是字符串，尝试解析为JSON
        if isinstance(decorations, str):
            try:
                return json.loads(decorations)
            except json.JSONDecodeError:
                # JSON解析失败，返回空字典
                return {}

        return {}

    def get_config_summary(self) -> dict:
        """
        获取配置摘要，用于调试和监控

        Returns:
            dict: 配置摘要
        """
        return {
            "basic": {
                "waiting_time": self.waiting_time,
                "cache_expiry": self.cache_expiry,
                "max_conversation_tokens": self.max_conversation_tokens,
                "alias": self.alias,
                "analysis_on_mention_only": self.analysis_on_mention_only,
                "force_reply_when_summoned": self.force_reply_when_summoned,
                "comfort_words": self.comfort_words,
                "patience_enabled": self.patience_enabled,
                "reminder_future_task_enabled": self.reminder_future_task_enabled,
                "reminder_direct_delivery_enabled": self.reminder_direct_delivery_enabled,
                "slap_words": self.slap_words,
                "silence_duration": self.silence_duration,
            },
            "status_mechanism": {
                "echo_detection_threshold": self.echo_detection_threshold,
                "dense_conversation_threshold": self.dense_conversation_threshold,
                "familiarity_timeout": self.familiarity_timeout,
                "observation_timeout": self.observation_timeout,
                "observation_min_messages": self.observation_min_messages,
                "observation_followup_score_threshold": self.observation_followup_score_threshold,
                "observation_followup_time_window": self.observation_followup_time_window,
                "familiarity_cooldown_duration": self.familiarity_cooldown_duration,
                "leave_echo_reply": self.leave_echo_reply,
                "leave_dense_reply": self.leave_dense_reply,
            },
            "detection_windows": {
                "echo_detection_window": self.echo_detection_window,
                "dense_conversation_window": self.dense_conversation_window,
                "min_participant_count": self.min_participant_count,
            },
            "air_reading": {
                "air_reading_enabled": self.air_reading_enabled,
                "air_reading_suppress_threshold": self.air_reading_suppress_threshold,
                "air_reading_ignore_window_messages": self.air_reading_ignore_window_messages,
                "air_reading_suppress_human_to_human": self.air_reading_suppress_human_to_human,
                "air_reading_suppress_ignored_recently": self.air_reading_suppress_ignored_recently,
                "air_reading_suppress_heated": self.air_reading_suppress_heated,
                "air_reading_suppress_smalltalk": self.air_reading_suppress_smalltalk,
                "observation_followup_short_phrases": self.observation_followup_short_phrases,
                "observation_followup_question_phrases": self.observation_followup_question_phrases,
                "observation_followup_feedback_phrases": self.observation_followup_feedback_phrases,
            },
        }
