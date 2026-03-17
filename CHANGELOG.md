# Changelog

## v1.5.0 - 2026-03-17
- 新增管理员私聊调试命令（默认开启，可配置关闭）：
  - `/random_reply_msg`
  - `/random_reply_img`
  - `/repeat <文本>`
  - `/api_image`
  - `/at_message [文本]`
  - `/timestamp_reply`
  - `/clean_weight [阈值]`
  - `/clean_cache`
  - `/backup_data`
  - `/remote_backup_test`
- 在调度器中新增可复用的调试维护接口：权重清理、缓存清理、备份执行、远端备份测试统计。
- 新增配置项 `enable_admin_debug_commands`。
- 重写 README，按“简介/功能介绍/程序逻辑/使用/管理员命令/关于”结构整理文档。

## v1.4.0 - 2026-03-17
- 将主程序重构为分层模块化结构：入口层、应用层、功能层、领域层、基础设施层。
- 新增应用层模块：`app/message_processor.py`、`app/feature_orchestrator.py`、`app/scheduler.py`。
- 新增功能层模块：`features/random_reply.py`、`features/repeat.py`、`features/at_message.py`、`features/api_image.py`。
- 新增领域层模块：`domain/message.py`、`domain/randomization.py`、`domain/weight_calculator.py`。
- 新增基础设施层模块：
  - `infra/repo`（文本库/图库/原始消息存储）
  - `infra/file_lock`（并发锁）
  - `infra/media`（图片处理与 API 图解析）
  - `infra/remote_storage`（none/local_copy/webdav_http）
- `main.py` 精简为插件注册、依赖装配、事件绑定、生命周期管理。
- `_conf_schema.json` 按功能模块重排并增加分组描述，提升可读性。

## v1.3.0 - 2026-03-17
- 新增每日 01:00 低权重文本清理：支持配置 `weight_cleanup_threshold`，自动清理文本库中低于阈值的记录。
- 新增私聊处理开关：默认不处理私聊消息，可通过 `allow_private_message` 开启。
- 新增群组开关：支持 `enabled_group_ids` 白名单和 `disabled_group_ids` 黑名单控制。
- 新增复读功能：支持 `enable_repeat` 与 `repeat_chance`，并与主随机回复独立。
- 新增 API 图片发送功能：支持 `enable_api_image`、`api_image_chance`、`api_image_url`。
- 新增 @机器人处理：支持在主随机回复、复读、API 图片、固定消息之间按权重随机执行。
- 新增时间戳随机回复：每分钟秒数为 0 时按 `timestamp_reply_probability` 判定触发，支持生效时间段。
- 时间戳功能支持在主随机回复与 API 图片发送之间随机执行。
- 新增群聊独立文本库：`group_isolated_text_db`，支持自动迁移全局文本库并可删除原全局库。
- 插件版本升级至 `1.3.0`。

## v1.2.0 - 2026-03-15
- 新增图片大小限制：支持配置 `photo_max_size_mb`，超过阈值的图片不保存。
- 调整本地模式维护策略：`remote_mode=none` 时不再执行每日远端备份。
- 新增本地保留策略（两种同时支持）：
  - 按保留天数清理：`local_keep_days`
  - 按容量阈值清理：`local_max_storage_mb`
- 维护任务在每日 01:00 执行本地保留策略（本地模式）或远端备份（远端模式）。
- 更新配置 schema，补充新增参数说明。

## v1.1.0 - 2026-03-15
- 完成随机回复插件主流程实现：文本与图片入库、随机抽取、空库保护。
- 新增文本权重计算与更新（W0/Wn 公式）并支持加权回复。
- 实现图片解析 `resolve_photo_path()`：本地优先、远端兜底、失败标记失效。
- 新增 CSV 文件锁 + 原子写，提升并发写入安全。
- 新增原始消息按平台/日期/群组保存 JSON。
- 新增每日维护任务：远端推送清理与缓存过期清理。

## v1.0.0 - 2026-03-15
- 插件初始化版本，提供基础消息监听与随机回复框架。
