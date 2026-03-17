import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register

from .app.feature_orchestrator import FeatureOrchestrator
from .app.message_processor import MessageProcessor
from .app.scheduler import SchedulerService
from .features.api_image import ApiImageFeature
from .features.random_reply import RandomReplyFeature
from .features.repeat import RepeatFeature
from .infra.media.image_service import ImageService
from .infra.remote_storage.factory import build_remote_storage
from .infra.repo.photo_repo import PhotoRepo
from .infra.repo.raw_message_repo import RawMessageRepo
from .infra.repo.text_repo import TextRepo
from .domain.randomization import choose_weighted


@register("randomreply_plugin", "maxshiro", "跨平台随机回复插件（QQ/Telegram）", "1.5.0")
class RandomReplyPlugin(Star):
    def __init__(self, context: Context, config: Optional[AstrBotConfig] = None):
        super().__init__(context)
        self.config = config or {}

        self.plugin_dir = Path(__file__).resolve().parent
        self.data_dir = self.plugin_dir / "data"
        self.original_dir = self.data_dir / "original_data"
        self.cache_media_dir = self.data_dir / "cache_media"
        self.group_db_migrated_flag = self.data_dir / ".group_db_migrated.flag"

        self._maintenance_task: Optional[asyncio.Task] = None
        self._maintenance_stop = asyncio.Event()
        self._active_session_group_map: Dict[str, str] = {}

        self.text_repo: Optional[TextRepo] = None
        self.photo_repo: Optional[PhotoRepo] = None
        self.raw_repo: Optional[RawMessageRepo] = None
        self.image_service: Optional[ImageService] = None
        self.random_reply_feature: Optional[RandomReplyFeature] = None
        self.repeat_feature: Optional[RepeatFeature] = None
        self.api_image_feature: Optional[ApiImageFeature] = None
        self.orchestrator: Optional[FeatureOrchestrator] = None
        self.message_processor: Optional[MessageProcessor] = None
        self.scheduler: Optional[SchedulerService] = None

    def _get_config(self, key: str, default: Any) -> Any:
        if isinstance(self.config, dict):
            return self.config.get(key, default)
        return default

    def _ensure_data_layout(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.original_dir.mkdir(parents=True, exist_ok=True)
        self.cache_media_dir.mkdir(parents=True, exist_ok=True)

    def _setup_dependencies(self):
        remote_storage = build_remote_storage(self._get_config)

        self.text_repo = TextRepo(self.data_dir, self._get_config)
        self.photo_repo = PhotoRepo(self.data_dir)
        self.raw_repo = RawMessageRepo(self.data_dir)
        self.image_service = ImageService(
            original_dir=self.original_dir,
            cache_media_dir=self.cache_media_dir,
            get_config=self._get_config,
            remote_storage=remote_storage,
        )

        self.text_repo.ensure_csv("private")
        self.photo_repo.ensure_csv()

        self.random_reply_feature = RandomReplyFeature(
            text_repo=self.text_repo,
            photo_repo=self.photo_repo,
            image_service=self.image_service,
            get_config=self._get_config,
        )
        self.repeat_feature = RepeatFeature(self._get_config)
        self.api_image_feature = ApiImageFeature(self.image_service, self._get_config)

        self.orchestrator = FeatureOrchestrator(
            get_config=self._get_config,
            random_reply_feature=self.random_reply_feature,
            repeat_feature=self.repeat_feature,
            api_image_feature=self.api_image_feature,
        )

        self.message_processor = MessageProcessor(
            get_config=self._get_config,
            text_repo=self.text_repo,
            photo_repo=self.photo_repo,
            raw_repo=self.raw_repo,
            image_service=self.image_service,
            orchestrator=self.orchestrator,
        )

        self.scheduler = SchedulerService(
            data_dir=self.data_dir,
            original_dir=self.original_dir,
            cache_media_dir=self.cache_media_dir,
            get_config=self._get_config,
            text_repo=self.text_repo,
            remote_storage=remote_storage,
            orchestrator=self.orchestrator,
            send_proactive=self._send_proactive,
            get_active_sessions=lambda: self._active_session_group_map,
        )

    def _maybe_migrate_group_db(self):
        if not self.text_repo or not self.raw_repo:
            return
        if not bool(self._get_config("group_isolated_text_db", False)):
            return
        if not bool(self._get_config("group_db_auto_migrate", False)):
            return
        if self.group_db_migrated_flag.exists():
            return

        group_ids = self.raw_repo.discover_groups()
        if group_ids:
            self.text_repo.merge_global_to_group(
                group_ids=group_ids,
                delete_global=bool(self._get_config("group_db_delete_global_after_migrate", True)),
            )
        self.group_db_migrated_flag.write_text("done", encoding="utf-8")

    async def _send_proactive(self, umo: str, kind: str, content: str):
        chain = MessageChain()
        if kind == "photo":
            chain = chain.file_image(content)
        else:
            chain = chain.message(content)
        await self.context.send_message(umo, chain)

    async def initialize(self):
        self._ensure_data_layout()
        self._setup_dependencies()
        self._maybe_migrate_group_db()

        async def maintenance_loop():
            while not self._maintenance_stop.is_set():
                try:
                    if self.scheduler:
                        await self.scheduler.tick()
                except Exception as ex:
                    logger.error("[randomreply_plugin] 定时任务异常: %s", ex)
                await asyncio.sleep(1)

        self._maintenance_task = asyncio.create_task(maintenance_loop())
        logger.info("[randomreply_plugin] 插件已加载并完成模块化初始化。")

    @filter.command("rrtest", alias={"rr", "randomreply"})
    async def rr_test(self, event: AstrMessageEvent):
        if not self.orchestrator:
            yield event.plain_result("插件尚未初始化完成。")
            return

        group_id = str(getattr(event.message_obj, "group_id", "") or "private")
        reply, reply_type, _ = self.orchestrator.random_reply_feature.pick(group_id=group_id, force_trigger=True)
        if reply and reply_type == "text":
            yield event.plain_result(reply)
            return
        if reply and reply_type == "photo":
            yield event.image_result(reply)
            return

        repeat_text = self.orchestrator.repeat_feature.pick((event.message_str or "").strip())
        if repeat_text:
            yield event.plain_result(repeat_text)
            return

        api_ref = self.orchestrator.api_image_feature.pick(force_trigger=True)
        if api_ref:
            yield event.image_result(api_ref)
            return

        yield event.plain_result("当前未命中可回复内容。")

    def _is_admin_debug_enabled(self) -> bool:
        return bool(self._get_config("enable_admin_debug_commands", True))

    def _pick_debug_text_reply(self, group_id: str) -> Optional[str]:
        if not self.text_repo:
            return None
        texts, weights = self.text_repo.load_pool(group_id)
        if not texts:
            return None
        weighted = choose_weighted(texts, weights)
        return weighted if weighted else texts[0]

    def _pick_debug_image_reply(self) -> Optional[str]:
        if not self.photo_repo or not self.image_service:
            return None
        photos = self.photo_repo.load_available()
        if not photos:
            return None
        import random

        random.shuffle(photos)
        for image_name in photos:
            path, _ = self.image_service.resolve_photo_path(image_name)
            if path:
                return path
        return None

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("random_reply_msg")
    async def debug_random_reply_msg(self, event: AstrMessageEvent):
        if not self._is_admin_debug_enabled():
            return
        reply = self._pick_debug_text_reply("private")
        if not reply:
            yield event.plain_result("文本库为空，暂无可测试文本。")
            return
        yield event.plain_result(reply)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("random_reply_img")
    async def debug_random_reply_img(self, event: AstrMessageEvent):
        if not self._is_admin_debug_enabled():
            return
        image_path = self._pick_debug_image_reply()
        if not image_path:
            yield event.plain_result("图片库为空或图片不可用。")
            return
        yield event.image_result(image_path)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("repeat")
    async def debug_repeat(self, event: AstrMessageEvent, text: str = ""):
        if not self._is_admin_debug_enabled():
            return
        message = text.strip() if text else ""
        if not message:
            yield event.plain_result("请在命令后输入要复读的文本，例如 /repeat hello")
            return
        yield event.plain_result(message)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("api_image")
    async def debug_api_image(self, event: AstrMessageEvent):
        if not self._is_admin_debug_enabled() or not self.api_image_feature:
            return
        image_ref = self.api_image_feature.pick(force_trigger=True)
        if not image_ref:
            yield event.plain_result("API 图片获取失败或未配置。")
            return
        yield event.image_result(image_ref)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("at_message")
    async def debug_at_message(self, event: AstrMessageEvent, text: str = ""):
        if not self._is_admin_debug_enabled() or not self.orchestrator:
            return
        kind, content, _ = self.orchestrator.at_feature.pick(group_id="private", message_text=text.strip())
        if not kind or not content:
            yield event.plain_result("@测试未命中任何动作。")
            return
        if kind == "photo":
            yield event.image_result(content)
            return
        yield event.plain_result(content)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("timestamp_reply")
    async def debug_timestamp_reply(self, event: AstrMessageEvent):
        if not self._is_admin_debug_enabled() or not self.orchestrator:
            return
        if not self.orchestrator.timestamp_should_trigger():
            yield event.plain_result("时间戳测试：未命中触发概率。")
            return
        kind, content, _ = self.orchestrator.decide_on_timestamp(group_id="private")
        if not kind or not content:
            yield event.plain_result("时间戳测试：未命中可发送内容。")
            return
        if kind == "photo":
            yield event.image_result(content)
            return
        yield event.plain_result(content)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("clean_weight")
    async def debug_clean_weight(self, event: AstrMessageEvent, threshold: float = 0.2):
        if not self._is_admin_debug_enabled() or not self.scheduler:
            return
        self.scheduler.debug_cleanup_weight(threshold=threshold)
        yield event.plain_result(f"已完成低权重清理，阈值={threshold:.3f}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("clean_cache")
    async def debug_clean_cache(self, event: AstrMessageEvent):
        if not self._is_admin_debug_enabled() or not self.scheduler:
            return
        self.scheduler.debug_cleanup_cache()
        yield event.plain_result("缓存清理完成。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("backup_data")
    async def debug_backup_data(self, event: AstrMessageEvent):
        if not self._is_admin_debug_enabled() or not self.scheduler:
            return
        mode = self.scheduler.debug_backup_data()
        if mode == "local_retention":
            yield event.plain_result("当前为本地模式，已执行本地保留清理。")
            return
        yield event.plain_result("已执行远端备份与本地过期清理。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("remote_backup_test")
    async def debug_remote_backup_test(self, event: AstrMessageEvent):
        if not self._is_admin_debug_enabled() or not self.scheduler:
            return
        pushed, failed, mode = self.scheduler.debug_remote_backup_test()
        yield event.plain_result(f"远端备份测试完成 mode={mode} 成功={pushed} 失败={failed}")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if not self.message_processor:
            return

        context = self.message_processor.build_context(event)
        if not context:
            return

        if context.umo:
            self._active_session_group_map[context.umo] = context.group_id

        content, kind, source = self.message_processor.process(event, context)
        if not content or not kind:
            return

        if kind == "text":
            logger.info(
                "[randomreply_plugin] 文本回复: platform=%s group=%s source=%s reply=%s",
                context.platform,
                context.group_id,
                source,
                content,
            )
            yield event.plain_result(content)
        elif kind == "photo":
            logger.info(
                "[randomreply_plugin] 图片回复: platform=%s group=%s source=%s path=%s",
                context.platform,
                context.group_id,
                source,
                content,
            )
            yield event.image_result(content)

    async def terminate(self):
        self._maintenance_stop.set()
        if self._maintenance_task:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass
        logger.info("[randomreply_plugin] 插件已卸载。")
