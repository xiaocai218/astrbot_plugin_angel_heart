import sys
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


if "markdown_it" not in sys.modules:
    markdown_it_module = ModuleType("markdown_it")

    class _FakeMarkdownIt:
        def __init__(self, *args, **kwargs):
            pass

        def render(self, text):
            return str(text or "")

    markdown_it_module.MarkdownIt = _FakeMarkdownIt
    sys.modules["markdown_it"] = markdown_it_module


if "mdit_plain.renderer" not in sys.modules:
    mdit_plain_module = ModuleType("mdit_plain")
    mdit_plain_renderer_module = ModuleType("mdit_plain.renderer")

    class _FakeRendererPlain:
        def __init__(self, *args, **kwargs):
            pass

    mdit_plain_renderer_module.RendererPlain = _FakeRendererPlain
    sys.modules["mdit_plain"] = mdit_plain_module
    sys.modules["mdit_plain.renderer"] = mdit_plain_renderer_module


if "pydantic" not in sys.modules:
    pydantic_module = ModuleType("pydantic")

    class _FakeBaseModel:
        def __init__(self, **kwargs):
            annotations = getattr(self.__class__, "__annotations__", {})
            for name in annotations:
                if name in kwargs:
                    value = kwargs[name]
                else:
                    value = getattr(self.__class__, name, None)
                setattr(self, name, value)

        def model_dump(self, *args, **kwargs):
            return dict(self.__dict__)

        def dict(self, *args, **kwargs):
            return dict(self.__dict__)

    def _fake_field(default=None, **kwargs):
        return default

    pydantic_module.BaseModel = _FakeBaseModel
    pydantic_module.Field = _fake_field
    sys.modules["pydantic"] = pydantic_module


if "aiohttp" not in sys.modules:
    aiohttp_module = ModuleType("aiohttp")

    class _FakeClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class _FakeClientSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get(self, *args, **kwargs):
            raise RuntimeError("network disabled in tests")

    aiohttp_module.ClientTimeout = _FakeClientTimeout
    aiohttp_module.ClientSession = _FakeClientSession
    sys.modules["aiohttp"] = aiohttp_module


if "PIL" not in sys.modules:
    pil_module = ModuleType("PIL")
    pil_image_module = ModuleType("PIL.Image")

    class _FakeImageObj:
        mode = "RGB"

        def convert(self, mode):
            return self

        def save(self, output, format=None, quality=None):
            output.write(b"")

    class _FakeImage:
        @staticmethod
        def open(*args, **kwargs):
            return _FakeImageObj()

    pil_image_module.open = _FakeImage.open
    pil_module.Image = pil_image_module
    sys.modules["PIL"] = pil_module
    sys.modules["PIL.Image"] = pil_image_module


if "astrbot" not in sys.modules:
    astrbot_module = ModuleType("astrbot")
    astrbot_api_module = ModuleType("astrbot.api")
    astrbot_api_event_module = ModuleType("astrbot.api.event")
    astrbot_core_module = ModuleType("astrbot.core")
    astrbot_core_star_module = ModuleType("astrbot.core.star")
    astrbot_core_star_context_module = ModuleType("astrbot.core.star.context")
    astrbot_core_message_module = ModuleType("astrbot.core.message")
    astrbot_core_message_components_module = ModuleType("astrbot.core.message.components")

    class _FakeLogger:
        def debug(self, *args, **kwargs):
            return None

        def info(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def error(self, *args, **kwargs):
            return None

    class _FakeAstrMessageEvent:
        pass

    class _FakeMessageChain(list):
        def __init__(self, chain=None):
            items = list(chain or [])
            super().__init__(items)
            self.chain = items


    class _FakeContext:
        async def send_message(self, *args, **kwargs):
            return None

    class _FakeAt:
        def __init__(self, qq=""):
            self.qq = qq
            self.text = f"@{qq}"

    class _FakeImage:
        def __init__(self, url="", file=""):
            self.url = url
            self.file = file

        async def convert_to_base64(self):
            return ""

    class _FakeReply:
        def __init__(self, sender_id=""):
            self.sender_id = sender_id

    class _FakePlain:
        def __init__(self, text=""):
            self.text = text

    astrbot_api_module.logger = _FakeLogger()
    astrbot_api_event_module.AstrMessageEvent = _FakeAstrMessageEvent
    astrbot_api_event_module.MessageChain = _FakeMessageChain
    astrbot_core_star_context_module.Context = _FakeContext
    astrbot_core_message_components_module.At = _FakeAt
    astrbot_core_message_components_module.Image = _FakeImage
    astrbot_core_message_components_module.Reply = _FakeReply
    astrbot_core_message_components_module.Plain = _FakePlain

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = astrbot_api_module
    sys.modules["astrbot.api.event"] = astrbot_api_event_module
    sys.modules["astrbot.core"] = astrbot_core_module
    sys.modules["astrbot.core.star"] = astrbot_core_star_module
    sys.modules["astrbot.core.star.context"] = astrbot_core_star_context_module
    sys.modules["astrbot.core.message"] = astrbot_core_message_module
    sys.modules["astrbot.core.message.components"] = astrbot_core_message_components_module

