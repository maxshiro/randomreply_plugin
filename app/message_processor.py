import datetime as dt
import re
from typing import Any, Callable, List, Optional, Tuple

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .feature_orchestrator import FeatureOrchestrator
from ..domain.message import MessageContext
from ..infra.media.image_service import ImageService
from ..infra.repo.photo_repo import PhotoRepo
from ..infra.repo.raw_message_repo import RawMessageRepo
from ..infra.repo.text_repo import TextRepo


class MessageProcessor:
    LINK_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)

    def __init__(
        self,
        get_config: Callable[[str, object], object],
        text_repo: TextRepo,
        photo_repo: PhotoRepo,
        raw_repo: RawMessageRepo,
        image_service: ImageService,
        orchestrator: FeatureOrchestrator,
    ):
        self.get_config = get_config
        self.text_repo = text_repo
        self.photo_repo = photo_repo
        self.raw_repo = raw_repo
        self.image_service = image_service
        self.orchestrator = orchestrator

    def _is_supported_platform(self, platform_name: str) -> bool:
        platform_name = (platform_name or "").lower()
        keywords = self.get_config("platform_keywords", ["aiocqhttp", "qqofficial", "telegram"])
        if not keywords:
            return True
        return any(str(k).lower() in platform_name for k in keywords)

    def _is_command_like(self, message: str) -> bool:
        prefixes = self.get_config("command_prefixes", ["/", "!"])
        return any(message.startswith(p) for p in prefixes)

    def _extract_images(self, event: AstrMessageEvent) -> List[Any]:
        chain = getattr(event.message_obj, "message", []) or []
        out: List[Any] = []
        for comp in chain:
            name = comp.__class__.__name__.lower()
            if "image" in name or "sticker" in name:
                out.append(comp)
        return out

    def _is_at_bot(self, event: AstrMessageEvent) -> bool:
        self_id = str(getattr(event.message_obj, "self_id", "") or "")
        if not self_id:
            return False
        chain = getattr(event.message_obj, "message", []) or []
        for comp in chain:
            name = comp.__class__.__name__.lower()
            if "at" not in name:
                continue
            ids = [
                str(getattr(comp, "qq", "") or ""),
                str(getattr(comp, "id", "") or ""),
                str(getattr(comp, "user_id", "") or ""),
                str(getattr(comp, "target", "") or ""),
            ]
            if self_id in ids:
                return True
        return False

    def _allow_private_message(self) -> bool:
        return bool(self.get_config("allow_private_message", False))

    def _is_private(self, group_id: str) -> bool:
        return (group_id or "").strip() in ("", "private")

    def is_group_allowed(self, group_id: str) -> bool:
        if self._is_private(group_id):
            return self._allow_private_message()
        enabled = [str(x).strip() for x in self.get_config("enabled_group_ids", []) if str(x).strip()]
        disabled = {str(x).strip() for x in self.get_config("disabled_group_ids", []) if str(x).strip()}
        gid = str(group_id).strip()
        if gid in disabled:
            return False
        if enabled and gid not in enabled:
            return False
        return True

    def _text_should_store(self, text: str, has_image: bool) -> bool:
        if not text:
            return False
        if has_image:
            return False
        if self.LINK_RE.search(text):
            return False
        max_len = int(self.get_config("max_text_length", 30))
        return len(text) < max_len

    def build_context(self, event: AstrMessageEvent) -> Optional[MessageContext]:
        platform_name = (event.get_platform_name() or "").lower()
        if not self._is_supported_platform(platform_name):
            return None

        message_text = (event.message_str or "").strip()
        if message_text and self._is_command_like(message_text):
            return None

        sender_id = str(event.get_sender_id() or "")
        self_id = str(getattr(event.message_obj, "self_id", "") or "")
        if sender_id and self_id and sender_id == self_id:
            return None

        if not bool(self.get_config("enable_passive_reply", True)):
            return None

        now = dt.datetime.now()
        group_id = str(getattr(event.message_obj, "group_id", "") or "private")
        group_id = re.sub(r"\s+", "", group_id) or "private"
        if not self.is_group_allowed(group_id):
            return None

        user_id = re.sub(r"\s+", "", sender_id) or "unknown"
        platform = re.sub(r"[^a-z0-9]+", "", platform_name) or "unknown"
        images = self._extract_images(event)

        return MessageContext(
            platform=platform,
            platform_name=platform_name,
            group_id=group_id,
            sender_id=sender_id,
            user_id=user_id,
            umo=str(getattr(event, "unified_msg_origin", "") or ""),
            message_text=message_text,
            date_str=now.strftime("%Y%m%d"),
            time_hms=now.strftime("%H%M%S"),
            timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
            has_image=len(images) > 0,
            is_at_bot=self._is_at_bot(event),
        )

    def process(self, event: AstrMessageEvent, context: MessageContext) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        image_components = self._extract_images(event)
        try:
            if self._text_should_store(context.message_text, context.has_image):
                self.text_repo.update_text(context.message_text, context.group_id)
                self.raw_repo.append_record(
                    platform=context.platform,
                    date_str=context.date_str,
                    group_id=context.group_id,
                    record={
                        "sender_id": context.sender_id,
                        "message_type": "text",
                        "message_content": context.message_text,
                        "timestamp": context.timestamp,
                    },
                )

            for image_comp in image_components:
                image_name = self.image_service.save_image_component(
                    image_comp=image_comp,
                    platform=context.platform,
                    date_str=context.date_str,
                    group_id=context.group_id,
                    user_id=context.user_id,
                    time_hms=context.time_hms,
                )
                if not image_name:
                    continue
                self.photo_repo.update_photo(image_name)
                self.raw_repo.append_record(
                    platform=context.platform,
                    date_str=context.date_str,
                    group_id=context.group_id,
                    record={
                        "sender_id": context.sender_id,
                        "message_type": "image",
                        "message_content": image_name,
                        "timestamp": context.timestamp,
                    },
                )
        except Exception as ex:
            logger.error(
                "[randomreply_plugin] 入库异常(不中断主流程): platform=%s group=%s err=%s",
                context.platform,
                context.group_id,
                ex,
            )

        return self.orchestrator.decide_on_message(
            group_id=context.group_id,
            message_text=context.message_text,
            is_at_bot=context.is_at_bot,
        )
